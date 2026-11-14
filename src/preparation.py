"""Persist matched evaluation subsets and prepare public inputs."""

from collections import Counter
import json
from pathlib import Path
from .data_io import read_rows, index_rows, write_json, write_rows, sha256, select_per_relation
from .prompts import emit_qa, emit_editing

MODES = ("geojson_exact", "map_annotated", "hybrid_geojson_exact")


def case_files(task):
    if task not in ("qa", "editing", "both"):
        raise ValueError("Task must be qa, editing or both")
    files = []
    if task in ("qa", "both"):
        files += ["qa/items.jsonl", "qa/gold_open.jsonl", "qa/gold_mcq4.jsonl"]
    if task in ("editing", "both"):
        files += ["editing/tasks.jsonl"]
    return files


def fingerprint(case, task="both"):
    return {name: sha256(Path(case) / name) for name in case_files(task)}


def prepare_case(source, target, per_relation, task="both"):
    """Persist the selected scenes and matching gold, without modifying the source."""
    if per_relation < 0:
        raise ValueError("Per-relation count must be nonnegative")
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError("Prepared case must be separate from its source")
    identity = {"source_sha256": fingerprint(source, task), "per_relation": per_relation}
    marker = target / "selection.json"
    if marker.exists():
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if saved["identity"] != identity or saved["selected_sha256"] != fingerprint(target, task):
            raise ValueError("Input subset changed; use a new output directory")
        return saved
    if target.exists() and any(target.iterdir()):
        raise ValueError("Prepared case directory must be new or empty")
    items = (
        select_per_relation(read_rows(source / "qa/items.jsonl"), per_relation)
        if task in ("qa", "both")
        else []
    )
    tasks = (
        select_per_relation(read_rows(source / "editing/tasks.jsonl"), per_relation)
        if task in ("editing", "both")
        else []
    )
    if task in ("qa", "both") and not items or task in ("editing", "both") and not tasks:
        raise ValueError("Each selected task needs nonempty source data")
    index_rows(items, "item_id")
    index_rows(tasks, "task_id")
    # Validate matching references before writing any output.
    gold_tables = {}
    if items:
        for form in ("open", "mcq4"):
            gold = index_rows(read_rows(source / f"qa/gold_{form}.jsonl"), "item_id")
            missing = [item["item_id"] for item in items if item["item_id"] not in gold]
            if missing:
                raise ValueError(f"Missing {form} gold for selected item: {missing[0]}")
            gold_tables[form] = [gold[item["item_id"]] for item in items]
        write_rows(target / "qa/items.jsonl", items)
        for form, rows in gold_tables.items():
            write_rows(target / f"qa/gold_{form}.jsonl", rows)
    if tasks:
        write_rows(target / "editing/tasks.jsonl", tasks)
    selection = {
        "identity": identity,
        "selected_sha256": fingerprint(target, task),
        "qa_items": len(items),
        "editing_tasks": len(tasks),
        "qa_relation_counts": dict(Counter(item["relation_id"] for item in items)),
        "editing_relation_counts": dict(Counter(row["relation_id"] for row in tasks)),
    }
    write_json(marker, selection)
    return selection


def prepare_modes(
    case,
    prompt_root,
    modes,
    task="both",
    basemap="none",
    basemap_style=None,
    basemap_zoom=19,
    basemap_cache=None,
):
    from .rendering import render_case

    case, prompt_root = Path(case), Path(prompt_root)
    if any(mode not in MODES for mode in modes):
        raise ValueError("Unknown input modality")
    if any(mode != "geojson_exact" for mode in modes):
        render_case(
            case,
            task,
            basemap=basemap,
            basemap_style=basemap_style,
            basemap_zoom=basemap_zoom,
            basemap_cache=basemap_cache,
        )
    result = {}
    for mode in modes:
        target = prompt_root / mode
        result[mode] = {}
        if task in ("qa", "both"):
            result[mode]["qa"] = emit_qa(case, target, mode)
        if task in ("editing", "both"):
            result[mode]["editing"] = emit_editing(case, target, mode)
    return result


def check_public_inputs(prompts):
    forbidden = (
        "ground_truth",
        "gold_answer",
        "predicted_F0_layer",
        "source_object_id",
        "OSM_Geofabrik:",
        '"oracle"',
    )
    for path in Path(prompts).rglob("*.jsonl"):
        for row in read_rows(path):
            text = json.dumps(row["messages"], ensure_ascii=False)
            if any(token in text for token in forbidden):
                raise ValueError(f"Reference or source identifier leaked into {path.name}")

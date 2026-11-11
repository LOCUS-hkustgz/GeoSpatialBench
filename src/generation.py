"""Generate independent QA scenes and Editing tasks from one city configuration."""

from collections import Counter
from pathlib import Path
from .config import load_config
from .data_io import write_json, write_rows


def editing_pools(frames, config):
    """Build a second feature pool directly from vectors, independently of QA scenes."""
    import geopandas as gpd
    from .editing.pools import cap_pools

    role_kind = {"buildings": "building", "landuse": "green", "roads": "road", "pois": "point"}
    pools = []
    for role in ("buildings", "landuse", "roads", "pois"):
        rows = []
        for _, row in frames[role].iterrows():
            label = role_kind[role]
            rows.append(
                {
                    "fid": str(row["_source_name"]) + ":" + str(row["_source_row_id"]),
                    "kind": label,
                    "semantics": {"category": label, "role": label, "label": label},
                    "geometry": row.geometry,
                }
            )
        pools.append(gpd.GeoDataFrame(rows, geometry="geometry", crs=frames[role].crs))
    return cap_pools(
        tuple(pools),
        max_buildings=8000,
        max_green=4000,
        max_roads=6000,
        max_points=12000,
        seed=int(config["seed"]),
    )


def mine_editing(frames, config, per_relation=25):
    from .editing.miner import CityEditMiner
    from .relations import CORE_28_IDS
    from .editing.constraints import evaluate_edit

    miner = CityEditMiner(
        editing_pools(frames, config),
        target=per_relation,
        seed=int(config["seed"]),
        city=config["city_name"],
        task_id_prefix=config["id_prefix"].upper() + "-ED-",
    )
    miner.run_all()
    for _ in range(8):
        short = [rid for rid in CORE_28_IDS if miner.counts[rid] < per_relation]
        if not short:
            break
        before = len(miner.tasks)
        for rid in short:
            getattr(miner, "gen_" + rid)()
        if len(miner.tasks) == before:
            break
    short = {rid: miner.counts[rid] for rid in CORE_28_IDS if miner.counts[rid] != per_relation}
    if short:
        raise RuntimeError(
            f"Editing candidates insufficient (required {per_relation} per relation): {short}; enlarge the city clip or adjust filters"
        )
    tasks = []
    for task in miner.tasks:
        task = {k: v for k, v in task.items() if not k.startswith("_")}
        task["crs_source"] = config["target_crs"]
        task["coordinate_system"] = (
            "local Cartesian metres; translated from projected source geometry"
        )
        # Explicitly use the reference layer only for checking a reference edit.
        reference_context = task.get("context", {})
        ev = evaluate_edit(task, task["ground_truth_wkt"], extra_context=reference_context)
        if ev["score"] != 1:
            raise RuntimeError(f"Editing reference fails its constraints: {task['task_id']}")
        tasks.append(task)
    tasks.sort(key=lambda t: (CORE_28_IDS.index(t["relation_id"]), t["task_id"]))
    return tasks


def generate_city(config_path, task="both", editing_per_relation=25, out=None):
    from .qa.generator import QAGenerator
    from .qa.forms import make_gold
    from .qa.audit import audit

    if task not in ("qa", "editing", "both") or editing_per_relation < 1:
        raise ValueError("Invalid task or editing quota")
    config, crs, configured_out, frames, diagnostics = load_config(config_path)
    out = Path(out).resolve() if out is not None else configured_out
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"Output directory is not empty: {out}; choose a new output_dir")
    report = {
        "city": config["city_name"],
        "seed": config["seed"],
        "crs": crs.to_string(),
        "status": "BUILDING",
        "data_diagnostics": diagnostics,
        "qa_editing_instances_paired": False,
    }
    write_json(out / "build_report.json", report)
    if task in ("qa", "both"):
        config = {**config, "target_crs": crs.to_string()}
        items = QAGenerator(config).generate(frames)
        open_gold, mcq_gold = make_gold(items)
        write_rows(out / "qa/items.jsonl", items)
        write_rows(out / "qa/gold_open.jsonl", open_gold)
        write_rows(out / "qa/gold_mcq4.jsonl", mcq_gold)
        qa_audit = audit(out)
        write_json(out / "qa/audit.json", qa_audit)
        if qa_audit["status"] != "PASS":
            raise RuntimeError("Generated QA failed audit: " + "; ".join(qa_audit["errors"]))
        report["qa"] = {
            "items": len(items),
            "relations": 28,
            "audit_status": "PASS",
            "geometry_balance": qa_audit["geometry_balance"],
        }
    if task in ("editing", "both"):
        tasks = mine_editing(frames, config, editing_per_relation)
        write_rows(out / "editing/tasks.jsonl", tasks)
        report["editing"] = {
            "tasks": len(tasks),
            "reference_constraints_pass": len(tasks),
            "by_relation": dict(Counter(t["relation_id"] for t in tasks)),
        }
    report["status"] = "PASS"
    write_json(out / "build_report.json", report)
    return report

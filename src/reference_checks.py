"""Reference-answer and coordinate diagnostics for benchmark cases."""

from pathlib import Path
from .data_io import read_rows, write_rows, write_json
from .evaluation import evaluate_qa, evaluate_editing


def reference_checks(case, out, task="both"):
    """Gold-only diagnostics; these files never enter the inference runner."""
    from shapely import wkt
    from shapely.geometry import mapping
    from .editing.constraints import evaluate_edit
    from .rendering import frame_for, to_pixels, from_pixels

    case, out = Path(case), Path(out)
    summary = {}
    for form in ("open", "mcq4") if task in ("qa", "both") else ():
        gold = read_rows(case / f"qa/gold_{form}.jsonl")
        predictions = out / f"qa_{form}_reference.jsonl"
        write_rows(
            predictions,
            [
                {
                    "item_id": row["item_id"],
                    "prediction": row["answer"] if form == "open" else row["answer_letter"],
                }
                for row in gold
            ],
        )
        result = evaluate_qa(
            case / "qa/items.jsonl",
            case / f"qa/gold_{form}.jsonl",
            predictions,
            form,
            out / f"qa_{form}.json",
        )
        if result["correct"] != len(gold):
            raise RuntimeError(f"{form} reference self-check failed")
        summary[form] = {"correct": result["correct"], "total": result["total"]}
    if task == "qa":
        write_json(out / "summary.json", summary)
        return summary
    tasks = read_rows(case / "editing/tasks.jsonl")
    reference_count, outside, roundtrip = 0, [], 0.0
    predictions = []
    for task in tasks:
        context = task.get("context", {})
        result = evaluate_edit(task, task["ground_truth_wkt"], extra_context=context)
        reference_count += result["score"] == 1
        geometry = wkt.loads(task["ground_truth_wkt"])
        frame = frame_for(task)
        pixel = to_pixels(geometry, frame)
        roundtrip = max(roundtrip, from_pixels(pixel, frame).hausdorff_distance(geometry))
        if any(value < 0 or value > 1536 for value in pixel.bounds):
            outside.append(task["task_id"])
        payload = {"geometry": mapping(pixel)}
        if task.get("operation") == "attribute_edit":
            layer = context.get("predicted_F0_layer", task.get("ground_truth_layer"))
            if layer is None:
                raise ValueError(f"Reference layer is missing: {task['task_id']}")
            payload["layer"] = layer
        predictions.append({"task_id": task["task_id"], "pixel_output": payload})
    if reference_count != len(tasks) or roundtrip > 1e-6:
        raise RuntimeError("Editing reference or coordinate roundtrip check failed")
    write_rows(out / "editing_pixel_reference.jsonl", predictions)
    result = evaluate_editing(
        case / "editing/tasks.jsonl",
        out / "editing_pixel_reference.jsonl",
        out / "editing_pixel.json",
        raster=True,
    )
    if result["correct"] != len(tasks):
        raise RuntimeError("Pixel reference self-check failed")
    summary["editing"] = {
        "correct": reference_count,
        "total": len(tasks),
        "pixel_correct": result["correct"],
        "max_roundtrip_metres": roundtrip,
        "reference_outside_canvas": len(outside),
        "outside_examples": outside[:5],
        "outside_policy": "Finite off-canvas coordinates are allowed; strict constraints admit alternative edits. Frames depend only on initial geometry.",
    }
    write_json(out / "summary.json", summary)
    return summary

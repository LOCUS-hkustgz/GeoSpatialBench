"""Score model predictions against a matching benchmark case."""

import argparse
from pathlib import Path
from _common import run
from src.data_io import EXAMPLE, write_json
from src.evaluation import evaluate_qa, evaluate_editing
from src.preparation import MODES


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=EXAMPLE)
    parser.add_argument(
        "--predictions",
        type=Path,
        help="Directory of qa_open/qa_mcq4/editing.jsonl, or one file with --task",
    )
    parser.add_argument("--task", choices=["all", "qa_open", "qa_mcq4", "editing"], default="all")
    parser.add_argument("--out", type=Path, default=Path("outputs/stockholm_example"))
    parser.add_argument("--mode", choices=MODES, default="geojson_exact")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--scoring", choices=["current", "legacy"], default="current")
    args = parser.parse_args(argv)
    predictions = args.predictions or args.case / "predictions"
    if predictions.is_file() and args.task == "all":
        parser.error("Use --task when scoring one prediction file")
    names = ("qa_open", "qa_mcq4", "editing") if args.task == "all" else (args.task,)
    results = {}
    for name in names:
        prediction = predictions if predictions.is_file() else predictions / f"{name}.jsonl"
        if name == "editing":
            result = evaluate_editing(
                args.case / "editing/tasks.jsonl",
                prediction,
                args.out / "editing.json",
                args.allow_partial,
                args.mode == "map_annotated",
            )
        else:
            form = name.removeprefix("qa_")
            result = evaluate_qa(
                args.case / "qa/items.jsonl",
                args.case / f"qa/gold_{form}.jsonl",
                prediction,
                form,
                args.out / f"{name}.json",
                args.mode,
                args.allow_partial,
                args.scoring,
            )
        results[name] = {
            key: result[key] for key in ("metric", "correct", "total", "score", "scoring_version")
        }
    write_json(args.out / "summary.json", results)
    return results


if __name__ == "__main__":
    raise SystemExit(run(main))

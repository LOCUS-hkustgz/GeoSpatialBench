"""Generate QA scenes and independent Editing tasks from city vectors."""

import argparse
from pathlib import Path
from _common import run
from src.generation import generate_city
from src.data_io import CONFIGS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, help="City config; defaults to bundled Stockholm vectors"
    )
    parser.add_argument("--out", type=Path, help="Override the configured output directory")
    parser.add_argument("--task", choices=["qa", "editing", "both"], default="both")
    parser.add_argument("--editing-per-relation", type=int, default=25)
    args = parser.parse_args(argv)
    if args.editing_per_relation < 1:
        parser.error("--editing-per-relation must be positive")
    out = args.out or (Path("outputs/stockholm_new_build") if args.config is None else None)
    return generate_city(
        args.config or CONFIGS / "stockholm.example.json",
        args.task,
        args.editing_per_relation,
        out,
    )


if __name__ == "__main__":
    raise SystemExit(run(main))

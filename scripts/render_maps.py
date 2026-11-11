"""Render annotated maps for a benchmark case without network tile requests."""

import argparse
from pathlib import Path
from _common import run
from src.rendering import render_case


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", type=Path, required=True, help="Case directory; images are written under it"
    )
    parser.add_argument("--task", choices=["qa", "editing", "both"], default="both")
    parser.add_argument("--per-relation", type=int, default=0)
    args = parser.parse_args(argv)
    if args.per_relation < 0:
        parser.error("--per-relation must be nonnegative")
    return render_case(args.case, args.task, args.per_relation)


if __name__ == "__main__":
    raise SystemExit(run(main))

"""Render task maps, optionally using Geoapify or Stadia backgrounds."""

import argparse
from pathlib import Path
from _common import run, basemap_arguments
from src.rendering import render_case


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", type=Path, required=True, help="Case directory; images are written under it"
    )
    parser.add_argument("--task", choices=["qa", "editing", "both"], default="both")
    parser.add_argument("--per-relation", type=int, default=0)
    basemap_arguments(parser)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan images, downloads and credits without network calls",
    )
    args = parser.parse_args(argv)
    if args.per_relation < 0:
        parser.error("--per-relation must be nonnegative")
    return render_case(
        args.case,
        args.task,
        args.per_relation,
        args.basemap,
        args.basemap_style,
        args.basemap_zoom,
        args.basemap_cache,
        args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(run(main))

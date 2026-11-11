"""Validate source vectors or check the reference answers of a generated case."""

import argparse
from pathlib import Path
from _common import run
from src.data_io import CONFIGS
from src.config import load_config
from src.reference_checks import reference_checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--config", type=Path, help="Validate source vectors using this city config"
    )
    source.add_argument(
        "--case", type=Path, help="Check reference answers and pixel-coordinate roundtrips"
    )
    parser.add_argument(
        "--out", type=Path, help="Reference diagnostic directory; defaults to CASE/validation"
    )
    parser.add_argument("--task", choices=["qa", "editing", "both"], default="both")
    args = parser.parse_args(argv)
    if args.case:
        return {
            "status": "PASS",
            "references": reference_checks(
                args.case, args.out or args.case / "validation", args.task
            ),
        }
    if args.out:
        parser.error("--out requires --case")
    config, crs, _, _, diagnostics = load_config(args.config or CONFIGS / "stockholm.example.json")
    return {
        "status": "PASS",
        "city": config["city_name"],
        "target_crs": crs.to_string(),
        "data": diagnostics,
        "note": "Feature-count checks passed; full relation availability is checked during generation",
    }


if __name__ == "__main__":
    raise SystemExit(run(main))

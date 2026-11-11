"""Infer an editable city configuration from a four-layer GeoPackage."""

import argparse
from pathlib import Path
from _common import run
from src.config import init_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--id-prefix", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target-crs")
    args = parser.parse_args(argv)
    return init_config(args.data, args.city, args.id_prefix, args.out, args.target_crs)


if __name__ == "__main__":
    raise SystemExit(run(main))

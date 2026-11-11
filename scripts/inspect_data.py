"""List source-vector layers, feature counts, CRS and fields."""

import argparse
from pathlib import Path
from _common import run
import pyogrio


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    result = []
    for layer, geometry_type in pyogrio.list_layers(args.path):
        info = pyogrio.read_info(args.path, layer=layer)
        result.append(
            {
                "layer": layer,
                "geometry_type": geometry_type,
                "crs": info.get("crs"),
                "features": info.get("features"),
                "fields": list(info["fields"]),
            }
        )
    return result


if __name__ == "__main__":
    raise SystemExit(run(main))

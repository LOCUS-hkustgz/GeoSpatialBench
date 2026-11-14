"""Select matching scenes and references, then emit public inputs for each modality."""

import argparse
from pathlib import Path
from _common import run, basemap_arguments
from src.data_io import EXAMPLE, write_json
from src.preparation import MODES, prepare_case, prepare_modes, check_public_inputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=EXAMPLE)
    parser.add_argument(
        "--out", type=Path, required=True, help="Prepared case and prompt directory"
    )
    parser.add_argument("--mode", choices=["all", *MODES], default="geojson_exact")
    parser.add_argument("--task", choices=["qa", "editing", "both"], default="both")
    parser.add_argument(
        "--per-relation", type=int, default=0, help="0 selects all; 1 selects a 28-relation preview"
    )
    basemap_arguments(parser)
    args = parser.parse_args(argv)
    if args.per_relation < 0:
        parser.error("--per-relation must be nonnegative")
    modes = MODES if args.mode == "all" else (args.mode,)
    if args.basemap != "none" and modes == ("geojson_exact",):
        parser.error("--basemap requires --mode map_annotated, hybrid_geojson_exact or all")
    if args.basemap == "none" and (
        args.basemap_style or args.basemap_cache or args.basemap_zoom != 19
    ):
        parser.error("Basemap settings require --basemap geoapify or stadia")
    selection = prepare_case(args.case, args.out / "case", args.per_relation, args.task)
    prompts = prepare_modes(
        args.out / "case",
        args.out / "prompts",
        modes,
        args.task,
        args.basemap,
        args.basemap_style,
        args.basemap_zoom,
        args.basemap_cache,
    )
    check_public_inputs(args.out / "prompts")
    result = {"status": "PASS", "selection": selection, "prompts": prompts}
    write_json(args.out / "preparation.json", result)
    return result


if __name__ == "__main__":
    raise SystemExit(run(main))

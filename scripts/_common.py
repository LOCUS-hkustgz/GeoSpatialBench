"""Shared script imports and concise command errors."""

import json
from pathlib import Path
import sys
from dotenv import load_dotenv

# Scripts run directly from a checkout; no package installation is required.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def basemap_arguments(parser):
    parser.add_argument("--basemap", choices=["none", "geoapify", "stadia"], default="none")
    parser.add_argument(
        "--basemap-style", help="Map style; defaults to osm-bright-grey / alidade_smooth"
    )
    parser.add_argument("--basemap-zoom", type=int, default=19, help="Maximum XYZ zoom, 1–19")
    parser.add_argument(
        "--basemap-cache", type=Path, help="Download cache; defaults to outputs/basemap_cache"
    )


def run(main):
    try:
        result = main()
        if isinstance(result, int):
            return result
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

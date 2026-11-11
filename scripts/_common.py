"""Shared script imports and concise command errors."""

import json
from pathlib import Path
import sys

# Scripts run directly from a checkout; no package installation is required.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

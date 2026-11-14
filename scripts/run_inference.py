"""Run one public prompt file against a Chat Completions or Responses endpoint."""

import argparse
from pathlib import Path
from _common import run
from src.inference import run_inference


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompts", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", required=True, help="API root including /v1 where required")
    ap.add_argument("--api-format", choices=["chat", "responses"], default="chat")
    ap.add_argument(
        "--key-env",
        default="MODEL_API_KEY",
        help="API key environment variable (default: MODEL_API_KEY)",
    )
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument(
        "--temperature", type=float, default=None, help="Omit by default for provider compatibility"
    )
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--transport-retries", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--dry-run", action="store_true", help="Validate requests locally; make no network calls"
    )
    args = ap.parse_args(argv)
    return run_inference(args)


if __name__ == "__main__":
    raise SystemExit(run(main))

"""CLI entrypoint for deterministic evals."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .runner import run_seed_evals


def main() -> None:
    parser = argparse.ArgumentParser(description="Run lite-interpreter deterministic evals.")
    parser.add_argument("--output-dir", default="", help="Optional directory for JSON/Markdown eval reports.")
    args = parser.parse_args()
    report_dir = Path(args.output_dir) if str(args.output_dir).strip() else Path(tempfile.mkdtemp(prefix="lite-interpreter-evals-"))
    payload = run_seed_evals(output_dir=report_dir)
    payload["report_dir"] = str(report_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

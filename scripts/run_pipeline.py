"""One-click runner for the full literature-review pipeline.

This script orchestrates the existing stages in order:
1) fetch_arxiv.py
2) generate_cards.py
3) cluster_analysis.py
4) weekly_survey_generator.py
5) final_survey_generator.py (optional)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full literature-review pipeline.")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip fetch_arxiv.py and start from generate_cards.py.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="Max papers for fetch_arxiv.py when fetch stage is enabled.",
    )
    parser.add_argument(
        "--no-final-survey",
        action="store_true",
        help="Do not run final_survey_generator.py.",
    )
    return parser


def run_stage(script_name: str, args: list[str] | None = None) -> None:
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name)]
    if args:
        cmd.extend(args)

    print(f"[RUN] {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=PROJECT_ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Stage failed: {script_name} (exit code={completed.returncode})")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.skip_fetch:
            run_stage("fetch_arxiv.py", ["--max-results", str(args.max_results)])

        run_stage("generate_cards.py")
        run_stage("cluster_analysis.py")
        run_stage("weekly_survey_generator.py")

        if not args.no_final_survey:
            run_stage("final_survey_generator.py")

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Pipeline failed: {exc}", flush=True)
        return 1

    print("[OK] Pipeline finished successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

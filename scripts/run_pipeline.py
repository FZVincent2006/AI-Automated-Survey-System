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
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
CARDS_PATH = PROJECT_ROOT / "data" / "paper_cards.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "output"
MIN_FINAL_PAPERS = 50
MIN_FINAL_DIGESTS = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full literature-review pipeline.")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip fetch_arxiv.py and start from generate_cards.py.",
    )
    parser.add_argument(
        "--append-fetch",
        action="store_true",
        help="Merge fetched papers into the existing raw corpus and deduplicate them.",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Optional fetch query; defaults to ARXIV_SEARCH_QUERY env or script default.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Max papers for fetch_arxiv.py when fetch stage is enabled.",
    )
    parser.add_argument(
        "--years-back",
        type=int,
        default=None,
        help="Optional recent-year window for fetch_arxiv.py.",
    )
    parser.add_argument(
        "--no-final-survey",
        action="store_true",
        help="Do not run final_survey_generator.py.",
    )
    parser.add_argument(
        "--force-final-draft",
        action="store_true",
        help="Generate an incomplete final draft before 50 cards and 3 weekly digests exist.",
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


def build_fetch_args(args: argparse.Namespace) -> list[str]:
    """Build fetch stage CLI args with CLI > env precedence."""

    fetch_args: list[str] = []
    if getattr(args, "append_fetch", False):
        fetch_args.append("--append")

    query = (args.query or "").strip() or (os.getenv("ARXIV_SEARCH_QUERY") or "").strip()
    if query:
        fetch_args.extend(["--query", query])

    max_results = args.max_results
    if max_results is None:
        env_max = os.getenv("ARXIV_MAX_RESULTS")
        if env_max:
            fetch_args.extend(["--max-results", env_max])
    elif max_results > 0:
        fetch_args.extend(["--max-results", str(max_results)])

    years_back = args.years_back
    if years_back is None:
        env_years = os.getenv("ARXIV_YEARS_BACK")
        if env_years:
            fetch_args.extend(["--years-back", env_years])
    elif years_back > 0:
        fetch_args.extend(["--years-back", str(years_back)])

    return fetch_args


def count_nonempty_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def final_submission_ready() -> tuple[bool, int, int]:
    """Return whether the hard course thresholds for the final report are met."""

    card_count = count_nonempty_lines(CARDS_PATH)
    digest_count = len(list(OUTPUT_DIR.glob("weekly_digest_第*周.md")))
    ready = card_count >= MIN_FINAL_PAPERS and digest_count >= MIN_FINAL_DIGESTS
    return ready, card_count, digest_count


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    try:
        if not args.skip_fetch:
            run_stage("fetch_arxiv.py", build_fetch_args(args))

        run_stage("generate_cards.py")
        run_stage("cluster_analysis.py")
        run_stage("weekly_survey_generator.py")

        if not args.no_final_survey:
            if args.force_final_draft:
                run_stage("final_survey_generator.py", ["--allow-incomplete"])
            else:
                ready, card_count, digest_count = final_submission_ready()
                if ready:
                    run_stage("final_survey_generator.py")
                else:
                    print(
                        "[SKIP] Final survey requires at least "
                        f"{MIN_FINAL_PAPERS} cards and {MIN_FINAL_DIGESTS} weekly digests "
                        f"(current: cards={card_count}, digests={digest_count}).",
                        flush=True,
                    )

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Pipeline failed: {exc}", flush=True)
        return 1

    print("[OK] Pipeline finished successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

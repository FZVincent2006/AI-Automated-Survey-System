"""Validate generated artifacts against the course submission requirements."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from literature_review_system.schema import PaperCard


DEFAULT_MIN_PAPERS = 50
DEFAULT_MIN_DIGESTS = 3
DEFAULT_MIN_WEEKLY_CHARS = 900
DEFAULT_MIN_FINAL_CHARS = 5000


def count_content_characters(markdown: str) -> int:
    plain_text = re.sub(r"[#>*_`\-\[\]()]", "", markdown)
    return len(re.sub(r"\s+", "", plain_text))


def main_report_markdown(markdown: str) -> str:
    boundaries = [
        position
        for marker in ("\n## Appendix:", "\n## References")
        if (position := markdown.find(marker)) >= 0
    ]
    return markdown[: min(boundaries)] if boundaries else markdown


def load_cards(path: Path) -> list[PaperCard]:
    cards: list[PaperCard] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                cards.append(PaperCard.model_validate_json(line))
            except Exception as exc:
                raise ValueError(f"Invalid paper card on line {line_number}: {exc}") from exc
    return cards


def validate_submission(
    data_dir: Path,
    output_dir: Path,
    min_papers: int = DEFAULT_MIN_PAPERS,
    min_digests: int = DEFAULT_MIN_DIGESTS,
    min_weekly_chars: int = DEFAULT_MIN_WEEKLY_CHARS,
    min_final_chars: int = DEFAULT_MIN_FINAL_CHARS,
) -> list[str]:
    errors: list[str] = []
    raw_path = data_dir / "papers_raw.json"
    cards_path = data_dir / "paper_cards.jsonl"
    taxonomy_path = data_dir / "taxonomy.md"
    comparison_path = data_dir / "comparison_table.csv"
    final_path = output_dir / "final_survey.md"

    required_paths = [raw_path, cards_path, taxonomy_path, comparison_path, final_path]
    for path in required_paths:
        if not path.exists():
            errors.append(f"Missing required artifact: {path}")
    if errors:
        return errors

    raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_papers = raw_payload.get("papers", []) if isinstance(raw_payload, dict) else []
    if len(raw_papers) < min_papers:
        errors.append(f"Raw corpus has {len(raw_papers)} papers; at least {min_papers} are required.")

    try:
        cards = load_cards(cards_path)
    except ValueError as exc:
        errors.append(str(exc))
        cards = []

    if len(cards) < min_papers:
        errors.append(f"Only {len(cards)} valid paper cards found; at least {min_papers} are required.")
    normalized_titles = {" ".join(card.title.lower().split()) for card in cards}
    if len(normalized_titles) != len(cards):
        errors.append("Paper cards contain duplicate titles.")

    taxonomy_text = taxonomy_path.read_text(encoding="utf-8")
    if taxonomy_text.count("#") < 2:
        errors.append("Taxonomy does not contain a usable multi-level Markdown hierarchy.")

    with comparison_path.open("r", encoding="utf-8-sig", newline="") as handle:
        comparison_rows = list(csv.DictReader(handle))
    required_columns = {
        "paper_title",
        "method_name",
        "time_space_complexity",
        "application_scenario",
        "pros_cons",
        "data_driven",
    }
    actual_columns = set(comparison_rows[0]) if comparison_rows else set()
    missing_columns = required_columns - actual_columns
    if missing_columns:
        errors.append(f"Comparison table is missing columns: {', '.join(sorted(missing_columns))}")
    minimum_rows = max(1, int(len(cards) * 0.9)) if cards else min_papers
    if len(comparison_rows) < minimum_rows:
        errors.append(
            f"Comparison table covers {len(comparison_rows)} papers; at least {minimum_rows} are required."
        )

    digest_paths = sorted(output_dir.glob("weekly_digest_第*周.md"))
    if len(digest_paths) < min_digests:
        errors.append(f"Only {len(digest_paths)} weekly digests found; at least {min_digests} are required.")
    for path in digest_paths:
        content_chars = count_content_characters(path.read_text(encoding="utf-8"))
        if content_chars < min_weekly_chars:
            errors.append(
                f"{path.name} is too short: {content_chars} characters; minimum is {min_weekly_chars}."
            )

    final_text = final_path.read_text(encoding="utf-8")
    final_chars = count_content_characters(main_report_markdown(final_text))
    if final_chars < min_final_chars:
        errors.append(
            f"Final survey is too short: {final_chars} characters; minimum is {min_final_chars}."
        )
    for section in [
        "Taxonomy Analysis",
        "Comparative Analysis",
        "Trend Insights",
        "Future Directions",
        "Conclusion",
        "References",
    ]:
        if section not in final_text:
            errors.append(f"Final survey is missing section: {section}")

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate final course submission artifacts.")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output")
    parser.add_argument("--min-papers", type=int, default=DEFAULT_MIN_PAPERS)
    parser.add_argument("--min-digests", type=int, default=DEFAULT_MIN_DIGESTS)
    parser.add_argument("--min-weekly-chars", type=int, default=DEFAULT_MIN_WEEKLY_CHARS)
    parser.add_argument("--min-final-chars", type=int, default=DEFAULT_MIN_FINAL_CHARS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    errors = validate_submission(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        min_papers=args.min_papers,
        min_digests=args.min_digests,
        min_weekly_chars=args.min_weekly_chars,
        min_final_chars=args.min_final_chars,
    )
    if errors:
        print("[FAILED] Submission validation found the following problems:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[OK] Submission artifacts satisfy the configured course requirements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

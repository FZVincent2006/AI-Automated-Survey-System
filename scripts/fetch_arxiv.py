"""Fetch raw arXiv papers and persist them as JSON.

This script uses the official ``arxiv`` Python package to search recent
papers by keyword, sort them by submission time, and save the raw result
payload to ``data/papers_raw.json`` for downstream stages.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

import arxiv


LOGGER = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT_DIR / "data" / "papers_raw.json"


@dataclass(slots=True)
class FetchResult:
    """A small container for the final persisted payload."""

    query: str
    fetched_at: str
    years_back: int
    max_results: int
    total_papers: int
    papers: list[dict[str, object]]


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line interface for the fetch step."""

    parser = argparse.ArgumentParser(
        description="Fetch recent arXiv papers and save raw records to JSON."
    )
    parser.add_argument(
        "--query",
        type=str,
        default="Multi-Agent Collaboration",
        help="Search keyword or query string, for example: 'Agentic Workflow'.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="Maximum number of papers to keep in the output file.",
    )
    parser.add_argument(
        "--years-back",
        type=int,
        default=2,
        help="Only keep papers submitted within the last N years.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination JSON file for raw arXiv records.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Number of results to request per arXiv API page.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=3.0,
        help="Delay between API requests, used by the arxiv client.",
    )
    parser.add_argument(
        "--num-retries",
        type=int,
        default=3,
        help="How many times to retry failed arXiv requests.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Merge with existing output and deduplicate by arXiv entry ID.",
    )
    return parser


def result_to_record(result: arxiv.Result) -> dict[str, object]:
    """Convert an arxiv.Result object into a JSON-serializable dictionary."""

    return {
        "entry_id": result.entry_id,
        "title": result.title,
        "authors": [author.name for author in result.authors],
        "summary": result.summary,
        "published": result.published.isoformat() if result.published else None,
        "updated": result.updated.isoformat() if result.updated else None,
        "pdf_url": result.pdf_url,
        "primary_category": result.primary_category,
        "categories": list(result.categories),
        "doi": getattr(result, "doi", None),
        "journal_ref": getattr(result, "journal_ref", None),
        "comment": getattr(result, "comment", None),
        "arxiv_url": result.entry_id,
    }


def load_existing_papers(output_path: Path) -> list[dict[str, object]]:
    """Load previously saved papers when append mode is enabled."""

    if not output_path.exists():
        return []

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("Existing file %s is not valid JSON; ignoring it.", output_path)
        return []

    papers = payload.get("papers", []) if isinstance(payload, dict) else []
    if not isinstance(papers, list):
        return []
    return [paper for paper in papers if isinstance(paper, dict)]


def deduplicate_papers(papers: list[dict[str, object]]) -> list[dict[str, object]]:
    """Deduplicate papers by arXiv entry ID while preserving order."""

    seen: set[str] = set()
    deduped: list[dict[str, object]] = []

    for paper in papers:
        key = str(paper.get("entry_id") or paper.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(paper)

    return deduped


def fetch_papers(
    query: str,
    max_results: int,
    years_back: int,
    page_size: int,
    delay_seconds: float,
    num_retries: int,
) -> list[dict[str, object]]:
    """Fetch recent papers from arXiv and stop once the date window is crossed."""

    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years_back)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    client = arxiv.Client(
        page_size=page_size,
        delay_seconds=delay_seconds,
        num_retries=num_retries,
    )

    papers: list[dict[str, object]] = []
    for result in client.results(search):
        published = result.published
        if published is not None and published < cutoff:
            # Results are already sorted by submission date, so we can stop early.
            break

        papers.append(result_to_record(result))
        if len(papers) >= max_results:
            break

    return papers


def save_payload(output_path: Path, payload: FetchResult) -> None:
    """Write the fetch result to disk as pretty-printed JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    """Run the fetch step from the command line."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    started_at = perf_counter()
    try:
        LOGGER.info("Fetching arXiv papers for query: %s", args.query)
        fetched_papers = fetch_papers(
            query=args.query,
            max_results=args.max_results,
            years_back=args.years_back,
            page_size=args.page_size,
            delay_seconds=args.delay_seconds,
            num_retries=args.num_retries,
        )

        if args.append:
            existing_papers = load_existing_papers(args.output)
            fetched_papers = deduplicate_papers(existing_papers + fetched_papers)

        payload = FetchResult(
            query=args.query,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            years_back=args.years_back,
            max_results=args.max_results,
            total_papers=len(fetched_papers),
            papers=fetched_papers,
        )
        save_payload(args.output, payload)

    except Exception as exc:  # noqa: BLE001 - keep the CLI failure mode simple.
        LOGGER.exception("Failed to fetch arXiv papers: %s", exc)
        return 1

    elapsed_seconds = perf_counter() - started_at
    LOGGER.info(
        "Fetched %d papers in %.2f seconds and saved to %s",
        len(fetched_papers),
        elapsed_seconds,
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

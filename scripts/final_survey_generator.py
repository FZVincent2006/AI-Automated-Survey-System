"""Generate a final survey report from pipeline artifacts.

Inputs:
- data/paper_cards.jsonl
- data/taxonomy.md
- data/comparison_table.csv
- output/weekly_digest_第*周.md (optional)

Output:
- output/final_survey.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS_PATH = PROJECT_ROOT / "data" / "paper_cards.jsonl"
DEFAULT_TAXONOMY_PATH = PROJECT_ROOT / "data" / "taxonomy.md"
DEFAULT_COMPARISON_PATH = PROJECT_ROOT / "data" / "comparison_table.csv"
DEFAULT_WEEKLY_DIR = PROJECT_ROOT / "output"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "output" / "final_survey.md"
DEFAULT_DEBUG_DIR = PROJECT_ROOT / "data" / "debug"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_MAX_COMPARISON_ROWS = 60
DEFAULT_MAX_WEEKLY_DIGESTS = 6
DEFAULT_MAX_TITLES = 120


FINAL_SURVEY_SYSTEM_PROMPT = """You are an academic survey writer.
You must produce a rigorous, concise final survey draft based ONLY on user-provided materials.
No external facts.
Maintain formal academic style.
Return JSON only.
JSON keys required: title, abstract, introduction, taxonomy_analysis, comparison_analysis, trend_insights, future_directions, conclusion.
The list fields must be arrays of strings.
Keep each field concise. Each list item should be short and non-redundant.
Do not wrap response in markdown code fences.
"""


@dataclass(slots=True)
class CardRecord:
    title: str
    key_idea: str
    method: str
    best_fit_category: str


class FinalSurveyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str
    abstract: str
    introduction: str
    taxonomy_analysis: list[str] = Field(min_length=2)
    comparison_analysis: list[str] = Field(min_length=2)
    trend_insights: list[str] = Field(min_length=2)
    future_directions: list[str] = Field(min_length=2)
    conclusion: str


def call_with_retry(func, *args, **kwargs):
    """Run external API call with bounded retry/backoff."""

    for attempt in Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    ):
        with attempt:
            return func(*args, **kwargs)


def dump_failure_payload(stage: str, content_text: str, extra: dict[str, object] | None = None) -> Path:
    """Persist failing model payload for parser debugging."""

    DEFAULT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    output_path = DEFAULT_DEBUG_DIR / f"{stage}_{timestamp}.json"
    payload = {"stage": stage, "response_text": content_text}
    if extra:
        payload["meta"] = extra
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate final survey markdown report.")
    parser.add_argument("--cards-path", type=Path, default=DEFAULT_CARDS_PATH)
    parser.add_argument("--taxonomy-path", type=Path, default=DEFAULT_TAXONOMY_PATH)
    parser.add_argument("--comparison-path", type=Path, default=DEFAULT_COMPARISON_PATH)
    parser.add_argument("--weekly-dir", type=Path, default=DEFAULT_WEEKLY_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.2)
    return parser


def load_cards(cards_path: Path) -> list[CardRecord]:
    if not cards_path.exists():
        raise FileNotFoundError(f"Card file not found: {cards_path}")

    cards: list[CardRecord] = []
    with cards_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            cards.append(
                CardRecord(
                    title=str(payload.get("title", "")).strip(),
                    key_idea=str(payload.get("key_idea", "")).strip(),
                    method=str(payload.get("method", "")).strip(),
                    best_fit_category=str(payload.get("best_fit_category", "")).strip(),
                )
            )
    return cards


def load_weekly_digests(weekly_dir: Path) -> list[str]:
    if not weekly_dir.exists():
        return []
    files = sorted(weekly_dir.glob("weekly_digest_第*周.md"))
    return [file.read_text(encoding="utf-8") for file in files]


def adaptive_sample_count(total: int, floor: int, ceiling: int, ratio: float) -> int:
    """Choose a representative sample size that grows with corpus size."""

    if total <= 0:
        return 0

    estimated = max(floor, int(round(total * ratio)))
    return min(total, max(floor, min(ceiling, estimated)))


def sample_evenly_spaced_indices(total: int, sample_size: int) -> list[int]:
    """Return stable indices spread across the full range."""

    if total <= 0 or sample_size <= 0:
        return []
    if sample_size >= total:
        return list(range(total))
    if sample_size == 1:
        return [total // 2]

    last_index = total - 1
    step = last_index / (sample_size - 1)
    indices: list[int] = []

    for position in range(sample_size):
        index = round(position * step)
        if index not in indices:
            indices.append(index)

    cursor = 0
    while len(indices) < sample_size and cursor < total:
        if cursor not in indices:
            indices.append(cursor)
        cursor += 1

    return sorted(indices[:sample_size])


def sample_evenly_spaced(items: list[object], sample_size: int) -> list[object]:
    """Sample items evenly across the corpus for representative context."""

    return [items[index] for index in sample_evenly_spaced_indices(len(items), sample_size)]


def build_prompt_payload(
    cards: list[CardRecord],
    taxonomy_md: str,
    comparison_df: pd.DataFrame,
    weekly_digests: list[str],
) -> str:
    category_counter = Counter(card.best_fit_category for card in cards if card.best_fit_category)
    comparison_sample_size = adaptive_sample_count(len(comparison_df), 20, DEFAULT_MAX_COMPARISON_ROWS, 0.2)
    digest_sample_size = adaptive_sample_count(len(weekly_digests), 3, DEFAULT_MAX_WEEKLY_DIGESTS, 0.5)
    title_sample_size = adaptive_sample_count(len(cards), 30, DEFAULT_MAX_TITLES, 0.2)

    lines: list[str] = []
    lines.append(f"Total papers: {len(cards)}")
    lines.append("Top categories:")
    for category, count in category_counter.most_common(10):
        lines.append(f"- {category}: {count}")

    lines.append("\nRepresentative corpus sampling strategy:")
    lines.append(f"- comparison table rows sampled: {comparison_sample_size} of {len(comparison_df)}")
    lines.append(f"- weekly digest snapshots sampled: {digest_sample_size} of {len(weekly_digests)}")
    lines.append(f"- paper titles sampled: {title_sample_size} of {len(cards)}")

    lines.append("\nTaxonomy markdown:\n")
    lines.append(taxonomy_md.strip())

    lines.append(f"\nComparison table sample ({comparison_sample_size} representative rows):")
    if comparison_sample_size > 0 and not comparison_df.empty:
        comparison_indices = sample_evenly_spaced_indices(len(comparison_df), comparison_sample_size)
        comparison_subset = comparison_df.iloc[comparison_indices]
        for _, row in comparison_subset.iterrows():
            lines.append(
                " | ".join(
                    [
                        f"paper_title={row.get('paper_title', '')}",
                        f"method_name={row.get('method_name', '')}",
                        f"time_space_complexity={row.get('time_space_complexity', '')}",
                        f"application_scenario={row.get('application_scenario', '')}",
                        f"pros_cons={row.get('pros_cons', '')}",
                        f"data_driven={row.get('data_driven', '')}",
                    ]
                )
            )
    else:
        lines.append("- no comparison rows available")

    if weekly_digests:
        lines.append("\nWeekly digest snapshots:")
        digest_char_limit = max(800, min(2400, 12000 // max(digest_sample_size, 1)))
        for idx, digest in enumerate(weekly_digests[-digest_sample_size:], start=1):
            lines.append(f"--- Weekly Snapshot {idx} ---")
            lines.append(digest[:digest_char_limit])

    lines.append("\nPaper title list:")
    for idx, card in enumerate(sample_evenly_spaced(cards, title_sample_size), start=1):
        lines.append(f"{idx}. {card.title}")

    return "\n".join(lines)


def create_client() -> OpenAI:
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    api_key = os.getenv("OPENAI_API_KEY")
    try:
        return OpenAI(api_key=api_key, base_url=base_url) if (api_key or base_url) else OpenAI()
    except TypeError:
        return OpenAI()


def clean_json_text(content_text: str) -> str:
    content_text = content_text.strip()
    if content_text.startswith("```"):
        lines = content_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content_text = "\n".join(lines).strip()

    m_block = re.search(r"```\s*json\s*([\s\S]*?)```", content_text, flags=re.IGNORECASE)
    if m_block:
        content_text = m_block.group(1).strip()

    start_idx = content_text.find("{")
    end_idx = content_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        content_text = content_text[start_idx : end_idx + 1]

    return content_text


def generate_final_survey(
    client: OpenAI,
    model: str,
    temperature: float,
    cards: list[CardRecord],
    taxonomy_md: str,
    comparison_df: pd.DataFrame,
    weekly_digests: list[str],
) -> FinalSurveyResponse | str:
    messages = [
        {"role": "system", "content": FINAL_SURVEY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_prompt_payload(cards, taxonomy_md, comparison_df, weekly_digests),
        },
    ]

    completion = call_with_retry(
        client.chat.completions.create,
        model=model,
        temperature=temperature,
        messages=messages,
    )
    message = completion.choices[0].message

    content_text = None
    if hasattr(message, "content"):
        content_text = getattr(message, "content")
    elif isinstance(message, dict):
        content_text = message.get("content")

    if isinstance(content_text, list):
        content_text = "".join(str(part) for part in content_text)

    if not isinstance(content_text, str) or not content_text.strip():
        raise ValueError("No valid content returned by model for final survey.")

    cleaned = clean_json_text(content_text)
    try:
        payload = json.loads(cleaned)
    except Exception:
        debug_path = dump_failure_payload(
            "final_survey_parse",
            content_text,
            {"cards_count": len(cards), "weekly_digests_count": len(weekly_digests)},
        )
        raise ValueError(f"Failed to parse final survey JSON; payload saved to {debug_path}")

    if isinstance(payload, dict) and "final_survey" in payload:
        return str(payload["final_survey"])

    return FinalSurveyResponse.model_validate(payload)


def render_markdown(report: FinalSurveyResponse | str, cards: list[CardRecord]) -> str:
    if isinstance(report, str):
        return report.strip() + "\n"

    lines: list[str] = []
    lines.append(f"# {report.title}")
    lines.append("")
    lines.append("## Abstract")
    lines.append(report.abstract)
    lines.append("")

    lines.append("## 1. Introduction")
    lines.append(report.introduction)
    lines.append("")

    lines.append("## 2. Taxonomy Analysis")
    for item in report.taxonomy_analysis:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 3. Comparative Analysis")
    for item in report.comparison_analysis:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 4. Trend Insights")
    for item in report.trend_insights:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 5. Future Directions")
    for item in report.future_directions:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 6. Conclusion")
    lines.append(report.conclusion)
    lines.append("")

    lines.append("## Appendix: Included Paper Titles")
    for card in cards:
        lines.append(f"- {card.title}")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_fallback_report(cards: list[CardRecord], taxonomy_md: str, comparison_df: pd.DataFrame) -> str:
    category_counter = Counter(card.best_fit_category for card in cards if card.best_fit_category)

    lines: list[str] = []
    lines.append("# Final Survey Report (Fallback)")
    lines.append("")
    lines.append("## Abstract")
    lines.append(
        f"This report summarizes {len(cards)} papers with a taxonomy-driven analysis and a comparative table over {len(comparison_df)} rows."
    )
    lines.append("")
    lines.append("## 1. Taxonomy Snapshot")
    lines.append(taxonomy_md.strip())
    lines.append("")
    lines.append("## 2. Category Distribution")
    for category, count in category_counter.most_common(10):
        lines.append(f"- {category}: {count}")
    lines.append("")
    lines.append("## 3. Conclusion")
    lines.append("The current corpus indicates active exploration of multi-agent collaboration, workflow orchestration, and evaluation robustness.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    model = os.getenv("OPENAI_MODEL", args.model)

    cards = load_cards(args.cards_path)
    taxonomy_md = args.taxonomy_path.read_text(encoding="utf-8")
    comparison_df = pd.read_csv(args.comparison_path)
    weekly_digests = load_weekly_digests(args.weekly_dir)

    try:
        client = create_client()
        report = generate_final_survey(
            client=client,
            model=model,
            temperature=args.temperature,
            cards=cards,
            taxonomy_md=taxonomy_md,
            comparison_df=comparison_df,
            weekly_digests=weekly_digests,
        )
        markdown = render_markdown(report, cards)
    except Exception:
        markdown = build_fallback_report(cards, taxonomy_md, comparison_df)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(f"[OK] Final survey saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

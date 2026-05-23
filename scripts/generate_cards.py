"""Generate structured JSONL paper cards from raw arXiv data.

This stage reads ``data/papers_raw.json``, skips papers that have already been
processed, calls an LLM with a strict schema, and appends each validated card
to ``data/paper_cards.jsonl`` immediately after it is produced.
"""

from __future__ import annotations

import argparse
import os
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep

from dotenv import load_dotenv
# Load .env early so OpenAI client can read credentials at import time
load_dotenv()
from openai import OpenAI
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from literature_review_system.schema import PaperCard


LOGGER = logging.getLogger(__name__)
DEFAULT_RAW_PATH = PROJECT_ROOT / "data" / "papers_raw.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "paper_cards.jsonl"
DEFAULT_SLEEP_SECONDS = 2.0


SYSTEM_PROMPT = """你是一个严谨的学术论文信息抽取助手。

你的唯一任务是：仅根据用户提供的论文 title 和 summary（摘要）进行提炼，
生成符合给定字段结构的论文卡片。

硬性要求：
1. 只允许基于 title 和 summary 推断，不要使用外部知识补全论文内容。
2. 不要直接拼接、复制或大段改写原文句子，必须做抽象、归纳和原创性提炼。
3. 如果摘要信息不足，允许保守表达，但不得编造实验细节、数据集、指标或结论。
4. 所有字段都必须填写，语言要简洁、学术、可读。
5. 输出必须严格符合结构化字段要求，不得额外添加字段，不得输出解释性文本。

字段写作要求：
- problem: 论文在解决什么核心问题。
- key_idea: 论文的核心思想或视角。
- method: 论文提出的方法或流程。
- dataset_or_scenario: 文中使用的数据集、任务或应用场景。
- metrics: 论文使用的评价指标。
- results_summary: 论文实验结果的概括性总结。
- innovation_type: 创新类型，尽量用简洁短语概括。
- limitations: 从摘要中能看出的局限，或明确写“摘要未明确说明”。
- best_fit_category: 最符合后续聚类使用的分类标签。
- confidence_level: 置信度评分，优先使用 1-5 的整数；若信息太少可写低置信度文本，但必须保持稳定、可解释。
"""


@dataclass(slots=True)
class RawPaper:
    """Normalized raw paper record loaded from the fetch stage."""

    entry_id: str
    title: str
    summary: str
    arxiv_url: str


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI for the card generation stage."""

    parser = argparse.ArgumentParser(
        description="Generate structured paper cards and save them as JSONL."
    )
    parser.add_argument(
        "--raw-path",
        type=Path,
        default=DEFAULT_RAW_PATH,
        help="Path to the raw arXiv JSON file produced by fetch_arxiv.py.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output JSONL file for structured paper cards.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="deepseek-v4-pro",
        help="OpenAI-compatible model name.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Pause between LLM calls to reduce rate-limit pressure.",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=0,
        help="Optional cap on how many new papers to process this run; 0 means no cap.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="LLM temperature used for structured extraction.",
    )
    return parser


def load_raw_payload(raw_path: Path) -> list[RawPaper]:
    """Load and normalize raw papers from the fetch stage output."""

    if not raw_path.exists():
        raise FileNotFoundError(f"Raw paper file not found: {raw_path}")

    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    papers = payload.get("papers", []) if isinstance(payload, dict) else []

    normalized: list[RawPaper] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue

        title = str(paper.get("title") or "").strip()
        summary = str(paper.get("summary") or "").strip()
        entry_id = str(paper.get("entry_id") or paper.get("arxiv_url") or title).strip()
        arxiv_url = str(paper.get("arxiv_url") or paper.get("entry_id") or "").strip()

        if not title or not summary:
            LOGGER.warning("Skipping malformed raw paper record without title/summary: %s", paper)
            continue

        normalized.append(
            RawPaper(
                entry_id=entry_id,
                title=title,
                summary=summary,
                arxiv_url=arxiv_url,
            )
        )

    return normalized


def normalize_text(value: str) -> str:
    """Normalize strings for duplicate detection."""

    return " ".join(value.lower().split())


def load_processed_signatures(output_path: Path) -> set[str]:
    """Load titles and source URLs already present in the JSONL output."""

    signatures: set[str] = set()
    if not output_path.exists():
        return signatures

    with output_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.warning("Skipping invalid JSONL line in %s", output_path)
                continue

            if not isinstance(record, dict):
                continue

            title = str(record.get("title") or "").strip()
            if title:
                signatures.add(f"title::{normalize_text(title)}")

            # Support URL-based deduplication if a future version stores it.
            source_url = str(record.get("arxiv_url") or record.get("entry_id") or "").strip()
            if source_url:
                signatures.add(f"url::{normalize_text(source_url)}")

    return signatures


def build_user_prompt(paper: RawPaper) -> str:
    """Format the paper payload for the LLM."""

    return (
        "请基于下面这篇论文的 title 和 summary 生成结构化论文卡片。\n\n"
        f"title: {paper.title}\n"
        f"summary: {paper.summary}\n"
    )


def create_client() -> OpenAI:
    """Create an OpenAI-compatible client from environment variables."""

    load_dotenv()
    return OpenAI()


def parse_card(client: OpenAI, model: str, temperature: float, paper: RawPaper) -> PaperCard:
    """Call the LLM with structured output parsing into PaperCard."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(paper)},
    ]

    # First try provider-side structured parse (fast if supported)
    try:
        completion = client.beta.chat.completions.parse(
            model=model,
            temperature=temperature,
            messages=messages,
            response_format=PaperCard,
        )
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is not None:
            if not isinstance(parsed, PaperCard):
                parsed = PaperCard.model_validate(parsed)
            return parsed
    except Exception as exc:  # fall back to text parsing for providers that don't support response_format
        LOGGER.debug("Structured parse failed, falling back to text parse: %s", exc)

    # Fallback: call standard chat completion and extract JSON from text
    completion = client.chat.completions.create(model=model, temperature=temperature, messages=messages)
    # content can be in several forms depending on SDK/provider
    message = completion.choices[0].message
    content_text = None
    if hasattr(message, "content"):
        content_text = getattr(message, "content")
    elif hasattr(message, "text"):
        content_text = getattr(message, "text")
    elif isinstance(message, dict):
        content_text = message.get("content") or message.get("text")

    if isinstance(content_text, list):
        content_text = "".join(str(p) for p in content_text)

    if not isinstance(content_text, str) or not content_text.strip():
        raise ValueError("The model response did not contain any text to parse into PaperCard.")

    # Try direct JSON parse, else extract first {...} block
    try:
        payload = json.loads(content_text)
    except Exception:
        m = re.search(r"(\{[\s\S]*\})", content_text)
        if not m:
            raise ValueError("Failed to locate JSON object in model text response.")
        try:
            payload = json.loads(m.group(1))
        except Exception as exc:
            raise ValueError(f"Failed to parse JSON object from model text: {exc}")

    if not isinstance(payload, dict):
        raise ValueError("Parsed JSON payload is not an object/dict for PaperCard.")

    # Defensive: ensure title exists in payload; fall back to original paper title
    if isinstance(payload, dict) and "title" not in payload:
        payload["title"] = getattr(paper, "title", "Unknown Title")

    return PaperCard.model_validate(payload)


def append_jsonl(output_path: Path, card: PaperCard) -> None:
    """Append one validated PaperCard to the output JSONL file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(card.model_dump_json(ensure_ascii=False))
        handle.write("\n")


def should_skip(paper: RawPaper, processed_signatures: set[str]) -> bool:
    """Check whether a paper has already been processed."""

    title_signature = f"title::{normalize_text(paper.title)}"
    url_signature = f"url::{normalize_text(paper.arxiv_url)}" if paper.arxiv_url else None
    return title_signature in processed_signatures or (
        url_signature is not None and url_signature in processed_signatures
    )


def main() -> int:
    """Run the card generation pipeline from the command line."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    # Strictly prefer OPENAI_MODEL env var; fallback to deepseek-v4-pro
    args.model = os.getenv("OPENAI_MODEL", "deepseek-v4-pro")

    try:
        raw_papers = load_raw_payload(args.raw_path)
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint should fail loudly.
        LOGGER.exception("Failed to load raw papers: %s", exc)
        return 1

    processed_signatures = load_processed_signatures(args.output)
    client = create_client()

    started_at = perf_counter()
    new_count = 0
    skipped_count = 0

    LOGGER.info("Loaded %d raw papers from %s", len(raw_papers), args.raw_path)
    LOGGER.info("Already processed signatures: %d", len(processed_signatures))

    for index, paper in enumerate(raw_papers, start=1):
        if args.max_papers > 0 and new_count >= args.max_papers:
            LOGGER.info("Reached the requested limit of %d new papers.", args.max_papers)
            break

        if should_skip(paper, processed_signatures):
            skipped_count += 1
            LOGGER.info("Skipping already processed paper: %s", paper.title)
            continue

        try:
            card = parse_card(
                client=client,
                model=args.model,
                temperature=args.temperature,
                paper=paper,
            )
            append_jsonl(args.output, card)

            processed_signatures.add(f"title::{normalize_text(paper.title)}")
            if paper.arxiv_url:
                processed_signatures.add(f"url::{normalize_text(paper.arxiv_url)}")

            new_count += 1
            LOGGER.info("成功解析第 %d 篇论文：%s", index, paper.title)

        except Exception as exc:  # noqa: BLE001 - keep the per-paper failure visible.
            LOGGER.exception("大模型解析失败：%s | 原因：%s", paper.title, exc)

        sleep(max(0.0, args.sleep_seconds))

    elapsed_seconds = perf_counter() - started_at
    LOGGER.info(
        "Finished generate_cards: new=%d skipped=%d total_raw=%d elapsed=%.2fs output=%s",
        new_count,
        skipped_count,
        len(raw_papers),
        elapsed_seconds,
        args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generate a weekly literature digest from taxonomy, comparison table, and new cards.

This script reads ``data/taxonomy.md``, ``data/comparison_table.csv`` and the
latest appended cards in ``data/paper_cards.jsonl``. It detects the newly added
cards since the last run, asks an LLM for a concise academic digest, and saves
the final Markdown to ``output/weekly_digest_第X周.md``.
"""

from __future__ import annotations

import argparse
import os
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep

import pandas as pd
from dotenv import load_dotenv
# Load .env early so OpenAI client can read credentials at import time
load_dotenv()
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


LOGGER = logging.getLogger(__name__)
DEFAULT_TAXONOMY_PATH = PROJECT_ROOT / "data" / "taxonomy.md"
DEFAULT_COMPARISON_PATH = PROJECT_ROOT / "data" / "comparison_table.csv"
DEFAULT_CARDS_PATH = PROJECT_ROOT / "data" / "paper_cards.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_STATE_PATH = DEFAULT_OUTPUT_DIR / "weekly_digest_state.json"
DEFAULT_DEBUG_DIR = PROJECT_ROOT / "data" / "debug"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_SLEEP_SECONDS = 1.5
DEFAULT_LOOKBACK_CARDS = 10
DEFAULT_MIN_CONTENT_CHARS = 900
DEFAULT_MAX_CONTENT_CHARS = 4000


WEEKLY_SYSTEM_PROMPT = """你是一位精通学术论文写作与科研趋势分析的 AI 科学家。

你的任务是：基于输入的 taxonomy、comparison table 以及新增论文卡片，写出一篇简洁但有洞见的 weekly digest。

硬性要求：
1. 必须严格用 Markdown 输出，语言要像学术综述，不要像产品汇报。
2. 只能依据输入材料进行归纳和批判性分析，不要引入外部事实。
3. 必须输出至少 2 点非表面化的“研究空白与未来方向”，并且要有批判性。
4. 要明确回应新论文对既有 taxonomy 的冲击或补充，例如新的二级方向、跨类融合、旧类细化等。
5. 对技术路线演进的讨论必须结合复杂度、应用场景和 data-driven 属性。
6. 文字要克制、凝练、原创，不要大段复述原始摘要。
7. 正文控制在约 1000–1800 个中文字符，确保排版后约为 1–2 页。
"""


@dataclass(slots=True)
class CardRecord:
    """Normalized paper card loaded from the JSONL file."""

    title: str
    problem: str
    key_idea: str
    method: str
    dataset_or_scenario: str
    metrics: str
    results_summary: str
    innovation_type: str
    limitations: str
    best_fit_category: str
    confidence_level: int | str


class WeeklyDigestResponse(BaseModel):
    """Structured weekly digest sections returned by the LLM."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    digest_title: str = Field(description="周报标题")
    overview: str = Field(description="本周研究动态总览的一句话或短段落")
    technical_evolution: list[str] = Field(
        description="核心技术路线演进要点",
        min_length=2,
    )
    taxonomy_impact: list[str] = Field(
        description="对既有 taxonomy 的冲击或补充",
        min_length=2,
    )
    research_gaps: list[str] = Field(
        description="研究空白与未来方向",
        min_length=2,
    )
    closing_sentence: str = Field(description="收束性总结句")


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
    """Build the command-line interface for the weekly digest stage."""

    parser = argparse.ArgumentParser(
        description="Generate a weekly digest from taxonomy, comparison table, and new cards."
    )
    parser.add_argument(
        "--taxonomy-path",
        type=Path,
        default=DEFAULT_TAXONOMY_PATH,
        help="Input taxonomy markdown file.",
    )
    parser.add_argument(
        "--comparison-path",
        type=Path,
        default=DEFAULT_COMPARISON_PATH,
        help="Input comparison table CSV file.",
    )
    parser.add_argument(
        "--cards-path",
        type=Path,
        default=DEFAULT_CARDS_PATH,
        help="Input paper cards JSONL file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for weekly digest outputs and state files.",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Path to the incremental progress state file.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help="OpenAI-compatible model name.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Pause before the LLM call to keep the script throttled when rerun repeatedly.",
    )
    parser.add_argument(
        "--lookback-cards",
        type=int,
        default=DEFAULT_LOOKBACK_CARDS,
        help="How many latest cards to use when no incremental delta is available.",
    )
    parser.add_argument(
        "--allow-repeat",
        action="store_true",
        help="Regenerate the current digest from recent cards when no new cards exist.",
    )
    parser.add_argument(
        "--min-content-chars",
        type=int,
        default=DEFAULT_MIN_CONTENT_CHARS,
        help="Minimum non-whitespace characters required in the rendered digest.",
    )
    parser.add_argument(
        "--max-content-chars",
        type=int,
        default=DEFAULT_MAX_CONTENT_CHARS,
        help="Maximum non-whitespace characters allowed in the rendered digest.",
    )
    parser.add_argument(
        "--generation-attempts",
        type=int,
        default=2,
        help="Maximum generation attempts when the digest fails quality validation.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.25,
        help="LLM temperature for digest generation.",
    )
    return parser


def load_taxonomy(taxonomy_path: Path) -> str:
    """Read the taxonomy markdown file."""

    if not taxonomy_path.exists():
        raise FileNotFoundError(f"Taxonomy file not found: {taxonomy_path}")
    return taxonomy_path.read_text(encoding="utf-8")


def load_comparison_table(comparison_path: Path) -> pd.DataFrame:
    """Read the comparison table CSV file."""

    if not comparison_path.exists():
        raise FileNotFoundError(f"Comparison table not found: {comparison_path}")
    return pd.read_csv(comparison_path)


def load_cards(cards_path: Path) -> list[CardRecord]:
    """Load and normalize paper cards from JSONL in file order."""

    if not cards_path.exists():
        raise FileNotFoundError(f"Card file not found: {cards_path}")

    cards: list[CardRecord] = []
    with cards_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.warning("Skipping invalid JSONL line %d in %s", line_number, cards_path)
                continue

            if not isinstance(payload, dict):
                continue

            try:
                card = CardRecord(
                    title=str(payload["title"]).strip(),
                    problem=str(payload["problem"]).strip(),
                    key_idea=str(payload["key_idea"]).strip(),
                    method=str(payload["method"]).strip(),
                    dataset_or_scenario=str(payload["dataset_or_scenario"]).strip(),
                    metrics=str(payload["metrics"]).strip(),
                    results_summary=str(payload["results_summary"]).strip(),
                    innovation_type=str(payload["innovation_type"]).strip(),
                    limitations=str(payload["limitations"]).strip(),
                    best_fit_category=str(payload["best_fit_category"]).strip(),
                    confidence_level=payload["confidence_level"],
                )
            except KeyError as exc:
                LOGGER.warning("Skipping incomplete card on line %d: missing %s", line_number, exc)
                continue

            if not card.title:
                continue

            cards.append(card)

    return cards


def create_client() -> OpenAI:
    """Create an OpenAI-compatible client from environment variables."""

    load_dotenv()
    return OpenAI()


def load_state(state_path: Path) -> dict[str, object]:
    """Load incremental progress state if it exists."""

    if not state_path.exists():
        return {"digest_index": 0, "last_processed_count": 0}

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("State file %s is invalid JSON; resetting state.", state_path)
        return {"digest_index": 0, "last_processed_count": 0}

    if not isinstance(payload, dict):
        return {"digest_index": 0, "last_processed_count": 0}

    return {
        "digest_index": int(payload.get("digest_index", 0) or 0),
        "last_processed_count": int(payload.get("last_processed_count", 0) or 0),
    }


def save_state(state_path: Path, digest_index: int, last_processed_count: int) -> None:
    """Persist incremental progress state after a successful run."""

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "digest_index": digest_index,
                "last_processed_count": last_processed_count,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def normalize_text(value: str) -> str:
    """Normalize whitespace for title matching."""

    return " ".join(value.lower().split())


def select_new_cards(cards: list[CardRecord], state: dict[str, object], lookback: int) -> list[CardRecord]:
    """Select the newly appended cards, or fall back to the latest cards if none exist."""

    last_processed_count = int(state.get("last_processed_count", 0) or 0)
    if last_processed_count < len(cards):
        return cards[last_processed_count:]

    if not cards:
        return []

    fallback_count = min(max(lookback, 1), len(cards))
    LOGGER.warning(
        "No new cards detected since the last digest; using the latest %d cards as fallback.",
        fallback_count,
    )
    return cards[-fallback_count:]


def extract_taxonomy_headings(taxonomy_md: str) -> list[str]:
    """Pull headings from the taxonomy markdown for compact context."""

    headings: list[str] = []
    for line in taxonomy_md.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append(match.group(2))
    return headings


def build_prompt_payload(
    taxonomy_md: str,
    comparison_df: pd.DataFrame,
    new_cards: list[CardRecord],
) -> str:
    """Build a compact, information-dense prompt payload for the LLM."""

    category_counter = Counter(card.best_fit_category for card in new_cards)
    taxonomy_headings = extract_taxonomy_headings(taxonomy_md)

    comparison_subset = comparison_df.copy()
    comparison_subset["paper_title"] = comparison_subset["paper_title"].astype(str).str.strip()
    new_titles = {card.title for card in new_cards}
    comparison_subset = comparison_subset[comparison_subset["paper_title"].isin(new_titles)]

    lines: list[str] = []
    lines.append("【taxonomy.md 摘要】")
    lines.append(f"taxonomy headings: {', '.join(taxonomy_headings[:20])}")
    lines.append("taxonomy markdown:")
    lines.append(taxonomy_md.strip())

    lines.append("\n【本周新增论文卡片】")
    lines.append(f"新增卡片数: {len(new_cards)}")
    for index, card in enumerate(new_cards, start=1):
        lines.append(
            f"{index}. title={card.title} | category={card.best_fit_category} | key_idea={card.key_idea} | method={card.method} | limits={card.limitations}"
        )

    lines.append("\n【本周新增类别分布】")
    for category, count in category_counter.most_common():
        lines.append(f"- {category}: {count}")

    lines.append("\n【comparison_table.csv 中对应行】")
    if comparison_subset.empty:
        lines.append("- 未能在 comparison_table.csv 中匹配到新增论文行。")
    else:
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

    return "\n".join(lines)


def generate_weekly_digest(
    client: OpenAI,
    model: str,
    temperature: float,
    taxonomy_md: str,
    comparison_df: pd.DataFrame,
    new_cards: list[CardRecord],
) -> WeeklyDigestResponse:
    """Call the LLM and parse the structured weekly digest response."""
    # Build enforced prompt that makes the model output a single JSON object only
    enforced_prompt = (
        WEEKLY_SYSTEM_PROMPT
        + "\nYou must respond with a single, valid JSON object containing the weekly digest. "
        + "Do not include any markdown wrappers like ```json ... ``` or conversational filler. "
        + "Return ONLY the raw JSON string."
    )

    messages = [
        {"role": "system", "content": enforced_prompt},
        {
            "role": "user",
            "content": (
                "请基于以下材料写一篇 Markdown 周报，并满足结构要求：\n"
                "1. 本周研究动态总览\n"
                "2. 核心技术路线演进\n"
                "3. 分类体系冲击与补充\n"
                "4. 研究空白与未来方向（至少 2 点，必须有批判性）\n\n"
                + build_prompt_payload(taxonomy_md, comparison_df, new_cards)
            ),
        },
    ]

    # Prefer structured parse only when not explicitly using DeepSeek (which rejects response_format)
    base_url = os.getenv("OPENAI_BASE_URL", os.getenv("OPENAI_API_BASE", "")).lower()
    completion = None
    if base_url and "deepseek" in base_url:
        # DeepSeek: avoid server-side structured parse, use plain chat completion
        completion = call_with_retry(
            client.chat.completions.create,
            model=model,
            temperature=temperature,
            messages=messages,
        )
    else:
        # Try provider-side structured parse first (useful for MockClient in tests)
        try:
            response = call_with_retry(
                client.beta.chat.completions.parse,
                model=model,
                temperature=temperature,
                messages=messages,
                response_format=WeeklyDigestResponse,
            )
            # If parse succeeded and returned a parsed object, validate and return directly
            message = response.choices[0].message
            parsed = getattr(message, "parsed", None)
            if parsed is not None:
                # Convert Pydantic model to dict if necessary
                if isinstance(parsed, WeeklyDigestResponse):
                    payload = parsed.model_dump()
                else:
                    payload = parsed
                digest = WeeklyDigestResponse.model_validate(payload)
                if len(digest.research_gaps) < 2:
                    raise ValueError("The model returned fewer than 2 research gaps, which is not acceptable.")
                return digest
        except Exception:
            completion = call_with_retry(
                client.chat.completions.create,
                model=model,
                temperature=temperature,
                messages=messages,
            )
            message = completion.choices[0].message
    # If we used chat completion (completion set), extract message; otherwise
    # 'message' should have been set by the structured-parse branch above.
    if 'completion' in locals() and completion is not None:
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
        raise ValueError("The model response did not contain a parsable weekly digest payload.")

    # Remove surrounding code fences if present
    content_text = content_text.strip()
    if content_text.startswith("```"):
        lines = content_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content_text = "\n".join(lines).strip()

    # Remove any ```json ... ``` blocks anywhere
    import re

    m_block = re.search(r"```\s*json\s*([\s\S]*?)```", content_text, flags=re.IGNORECASE)
    if m_block:
        content_text = m_block.group(1).strip()

    # Final fallback: slice to outermost { ... }
    start_idx = content_text.find("{")
    end_idx = content_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        content_text = content_text[start_idx:end_idx + 1]

    try:
        payload = json.loads(content_text)
    except Exception as exc:
        debug_path = dump_failure_payload(
            "weekly_digest_parse",
            content_text,
            {"new_cards_count": len(new_cards), "new_titles": [card.title for card in new_cards[:20]]},
        )
        LOGGER.error("Saved failing weekly digest payload to %s", debug_path)
        raise ValueError(f"Failed to parse weekly digest JSON from model text: {exc}")

    # 容错降级：如果大模型直接返回了完整的 Markdown 综述内容（shortcut），则直接返回该文本
    if isinstance(payload, dict) and "weekly_digest" in payload:
        print("[INFO] Detected 'weekly_digest' shortcut field, bypassing structured validate.")
        return payload["weekly_digest"]

    digest = WeeklyDigestResponse.model_validate(payload)
    if len(digest.research_gaps) < 2:
        raise ValueError("The model returned fewer than 2 research gaps, which is not acceptable.")
    return digest


def render_markdown(digest: WeeklyDigestResponse, week_index: int, new_cards: list[CardRecord]) -> str:
    """Compose the final Markdown digest from the structured response."""
    # Backwards-compatible: if caller passed a raw markdown string (degraded mode),
    # return it directly.
    if isinstance(digest, str):
        return digest.strip() + "\n"

    lines: list[str] = []
    lines.append(f"# {digest.digest_title or f'Weekly Digest 第{week_index}周'}")
    lines.append("")
    lines.append(f"*生成于第 {week_index} 周，共纳入 {len(new_cards)} 篇新增论文卡片。*")
    lines.append("")

    lines.append("## 1. 本周研究动态总览")
    lines.append(digest.overview)
    lines.append("")

    lines.append("## 2. 核心技术路线演进")
    for item in digest.technical_evolution:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 3. 分类体系冲击与补充")
    for item in digest.taxonomy_impact:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 4. 研究空白与未来方向")
    for item in digest.research_gaps:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## 5. 本周新增样本")
    for card in new_cards[:12]:
        lines.append(f"- {card.title} · {card.best_fit_category}")
    lines.append("")

    lines.append(f"> {digest.closing_sentence}")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def count_content_characters(markdown: str) -> int:
    """Approximate report length after removing Markdown syntax and whitespace."""

    plain_text = re.sub(r"[#>*_`\-\[\]()]", "", markdown)
    return len(re.sub(r"\s+", "", plain_text))


def validate_weekly_markdown(markdown: str, min_chars: int, max_chars: int) -> None:
    """Reject weekly artifacts that do not satisfy the assignment structure."""

    required_sections = [
        "本周研究动态总览",
        "核心技术路线演进",
        "分类体系冲击与补充",
        "研究空白与未来方向",
    ]
    missing = [section for section in required_sections if section not in markdown]
    if missing:
        raise ValueError(f"Weekly digest is missing required sections: {', '.join(missing)}")

    content_chars = count_content_characters(markdown)
    if content_chars < max(1, min_chars):
        raise ValueError(
            f"Weekly digest is too short: {content_chars} characters; minimum is {min_chars}."
        )
    if max_chars > 0 and content_chars > max_chars:
        raise ValueError(
            f"Weekly digest is too long: {content_chars} characters; maximum is {max_chars}."
        )


def main() -> int:
    """Run the weekly digest generator from the command line."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    # Strictly prefer OPENAI_MODEL env var; fallback to deepseek-v4-pro
    args.model = os.getenv("OPENAI_MODEL", "deepseek-v4-pro")

    try:
        taxonomy_md = load_taxonomy(args.taxonomy_path)
        comparison_df = load_comparison_table(args.comparison_path)
        cards = load_cards(args.cards_path)
    except Exception as exc:  # noqa: BLE001 - explicit CLI failure reporting.
        LOGGER.exception("Failed to load inputs: %s", exc)
        return 1

    if not cards:
        LOGGER.error("No paper cards found in %s", args.cards_path)
        return 1

    state = load_state(args.state_path)
    has_incremental_update = int(state.get("last_processed_count", 0) or 0) < len(cards)
    if not has_incremental_update and not args.allow_repeat:
        LOGGER.info("No new paper cards detected; no weekly digest was generated.")
        return 0

    new_cards = select_new_cards(cards, state, args.lookback_cards)
    if not new_cards:
        LOGGER.error("No usable cards available for weekly digest generation.")
        return 1

    digest_index = int(state.get("digest_index", 0) or 0)
    if has_incremental_update:
        digest_index += 1
    elif digest_index <= 0:
        digest_index = 1

    client = create_client()
    started_at = perf_counter()

    LOGGER.info("Loaded taxonomy from %s", args.taxonomy_path)
    LOGGER.info("Loaded comparison table from %s with %d rows", args.comparison_path, len(comparison_df))
    LOGGER.info("Loaded %d paper cards; selected %d cards for this digest", len(cards), len(new_cards))

    try:
        attempts = max(1, args.generation_attempts)
        markdown = ""
        last_error: Exception | None = None
        for attempt_index in range(1, attempts + 1):
            sleep(max(0.0, args.sleep_seconds))
            try:
                digest = generate_weekly_digest(
                    client=client,
                    model=args.model,
                    temperature=args.temperature,
                    taxonomy_md=taxonomy_md,
                    comparison_df=comparison_df,
                    new_cards=new_cards,
                )
                markdown = render_markdown(digest, digest_index, new_cards)
                validate_weekly_markdown(
                    markdown,
                    min_chars=args.min_content_chars,
                    max_chars=args.max_content_chars,
                )
                break
            except Exception as exc:  # noqa: BLE001 - retry quality failures as well as API failures.
                last_error = exc
                LOGGER.warning(
                    "Weekly digest attempt %d/%d failed validation: %s",
                    attempt_index,
                    attempts,
                    exc,
                )
        else:
            raise RuntimeError(f"Weekly digest did not pass validation: {last_error}")

        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / f"weekly_digest_第{digest_index}周.md"
        output_path.write_text(markdown, encoding="utf-8")
        LOGGER.info("Saved weekly digest to %s", output_path)

        # Keep the state file aligned with the generated weekly artifact even when
        # the run is a fallback re-generation with no new cards.
        save_state(args.state_path, digest_index, len(cards))

    except Exception as exc:  # noqa: BLE001 - keep the failure reason visible.
        LOGGER.exception("weekly survey generation failed: %s", exc)
        return 1

    elapsed_seconds = perf_counter() - started_at
    LOGGER.info(
        "Finished weekly digest generation: digest_index=%d cards=%d selected=%d elapsed=%.2fs",
        digest_index,
        len(cards),
        len(new_cards),
        elapsed_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

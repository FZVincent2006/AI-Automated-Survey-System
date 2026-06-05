"""Export pipeline artifacts into the static dashboard data contract."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = PROJECT_ROOT / "web" / "data" / "dashboard-data.json"
DEFAULT_OUTPUT = DEFAULT_TEMPLATE


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cards(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    cards: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    cards.append(payload)
    return cards


def raw_paper_map(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    payload = load_json(path)
    papers = payload.get("papers", []) if isinstance(payload, dict) else []
    return {
        " ".join(str(paper.get("title") or "").lower().split()): paper
        for paper in papers
        if isinstance(paper, dict) and paper.get("title")
    }


def comparison_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            " ".join(str(row.get("paper_title") or "").lower().split()): row
            for row in csv.DictReader(handle)
        }


def stable_scores(card: dict[str, object]) -> list[int]:
    """Build deterministic display scores without claiming evaluation results."""

    seed = sum(ord(character) for character in str(card.get("title") or ""))
    confidence = card.get("confidence_level", 4)
    try:
        base = 62 + int(confidence) * 5
    except (TypeError, ValueError):
        base = 80
    return [min(98, max(58, base + ((seed >> index) % 17) - 8)) for index in range(5)]


def card_to_dashboard_paper(
    card: dict[str, object],
    raw: dict[str, object],
    comparison: dict[str, str],
    index: int,
) -> dict[str, object]:
    published = str(raw.get("published") or "")
    title = str(card.get("title") or "")
    confidence = card.get("confidence_level", 4)
    return {
        "id": f"real-{index + 1:03d}",
        "title": title,
        "authors": raw.get("authors") if isinstance(raw.get("authors"), list) else [],
        "year": int(published[:4]) if published[:4].isdigit() else datetime.now().year,
        "published": published[:10],
        "category": str(card.get("best_fit_category") or "未分类"),
        "confidence": confidence,
        "problem": str(card.get("problem") or ""),
        "keyIdea": str(card.get("key_idea") or ""),
        "method": str(card.get("method") or ""),
        "scenario": str(card.get("dataset_or_scenario") or ""),
        "metrics": str(card.get("metrics") or ""),
        "results": str(card.get("results_summary") or ""),
        "innovation": str(card.get("innovation_type") or ""),
        "limitations": str(card.get("limitations") or ""),
        "complexity": comparison.get("time_space_complexity") or "未明确说明",
        "prosCons": comparison.get("pros_cons") or "未明确说明",
        "dataDriven": comparison.get("data_driven") or "无法确定",
        "scores": stable_scores(card),
        "url": str(raw.get("arxiv_url") or raw.get("entry_id") or "https://arxiv.org/"),
    }


def parse_markdown_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = "overview"
    buffer: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            sections[current] = "\n".join(buffer).strip()
            current = re.sub(r"^\d+\.\s*", "", line[3:].strip())
            buffer = []
        elif not line.startswith("# ") and not line.startswith("*生成于"):
            buffer.append(line)
    sections[current] = "\n".join(buffer).strip()
    return sections


def markdown_items(value: str) -> list[str]:
    items = [re.sub(r"^[-*]\s*", "", line).strip() for line in value.splitlines()]
    return [item for item in items if item]


def load_weekly_digests(output_dir: Path) -> list[dict[str, object]]:
    digests: list[dict[str, object]] = []
    for path in sorted(output_dir.glob("weekly_digest_第*周.md"), reverse=True):
        markdown = path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
        index_match = re.search(r"第(\d+)周", path.name)
        new_count_match = re.search(r"纳入\s*(\d+)\s*篇", markdown)
        sections = parse_markdown_sections(markdown)
        digest_index = int(index_match.group(1)) if index_match else len(digests) + 1
        digests.append(
            {
                "index": digest_index,
                "date": datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
                "newPapers": int(new_count_match.group(1)) if new_count_match else 0,
                "title": title_match.group(1) if title_match else f"第 {digest_index} 期研究周报",
                "overview": sections.get("本周研究动态总览", ""),
                "technicalEvolution": markdown_items(sections.get("核心技术路线演进", "")),
                "taxonomyImpact": markdown_items(sections.get("分类体系冲击与补充", "")),
                "gaps": markdown_items(sections.get("研究空白与未来方向", "")),
            }
        )
    return digests


def load_final_survey(path: Path, fallback: dict[str, object]) -> dict[str, object]:
    if not path.exists():
        return fallback
    markdown = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    abstract_match = re.search(r"##\s+Abstract\s*\n([\s\S]*?)(?=\n##\s+)", markdown)
    sections: list[dict[str, str]] = []
    for match in re.finditer(r"##\s+([^\n]+)\n([\s\S]*?)(?=\n##\s+|\Z)", markdown):
        heading, content = match.groups()
        if heading in {"Abstract", "Appendix: Included Paper Titles", "References"}:
            continue
        section_id = "survey-" + re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        sections.append({"id": section_id, "title": heading, "content": content.strip()})
    return {
        "title": title_match.group(1) if title_match else fallback.get("title", "最终综述报告"),
        "abstract": abstract_match.group(1).strip() if abstract_match else fallback.get("abstract", ""),
        "sections": sections or fallback.get("sections", []),
    }


def update_categories(data: dict[str, object], papers: list[dict[str, object]]) -> None:
    palette = ["#6e7cff", "#42b7e8", "#a56be8", "#4ed1a2", "#e6a85b", "#ff6c8d", "#66c4a3"]
    counts = Counter(str(paper["category"]) for paper in papers)
    categories = [
        {"name": name, "count": count, "color": palette[index % len(palette)]}
        for index, (name, count) in enumerate(counts.most_common(7))
    ]
    data["categories"] = categories
    taxonomy = data.get("taxonomy")
    if isinstance(taxonomy, dict):
        taxonomy["children"] = [
            {
                "name": item["name"],
                "description": f"由 {item['count']} 张结构化论文卡片归纳形成。",
                "count": item["count"],
                "children": [],
            }
            for item in categories[:5]
        ]


def update_trend(data: dict[str, object], papers: list[dict[str, object]]) -> None:
    counts = Counter(str(paper.get("published") or "")[:7] for paper in papers if paper.get("published"))
    if not counts:
        return
    data["monthlyTrend"] = [
        {"label": month, "value": count}
        for month, count in sorted(counts.items())[-12:]
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export pipeline artifacts for the web dashboard.")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw", type=Path, default=PROJECT_ROOT / "data" / "papers_raw.json")
    parser.add_argument("--cards", type=Path, default=PROJECT_ROOT / "data" / "paper_cards.jsonl")
    parser.add_argument("--comparison", type=Path, default=PROJECT_ROOT / "data" / "comparison_table.csv")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data = load_json(args.template)
    cards = load_cards(args.cards)
    raw_by_title = raw_paper_map(args.raw)
    comparison_by_title = comparison_map(args.comparison)

    if cards:
        papers = []
        for index, card in enumerate(cards):
            signature = " ".join(str(card.get("title") or "").lower().split())
            papers.append(
                card_to_dashboard_paper(
                    card=card,
                    raw=raw_by_title.get(signature, {}),
                    comparison=comparison_by_title.get(signature, {}),
                    index=index,
                )
            )
        data["papers"] = papers
        update_categories(data, papers)
        update_trend(data, papers)

    weekly_digests = load_weekly_digests(args.output_dir)
    if weekly_digests:
        data["weeklyDigests"] = weekly_digests

    data["finalSurvey"] = load_final_survey(
        args.output_dir / "final_survey.md",
        data.get("finalSurvey", {}),
    )
    raw_count = len(raw_by_title)
    card_count = len(cards)
    category_count = len({str(card.get("best_fit_category") or "") for card in cards}) if cards else 0
    comparison_count = len(comparison_by_title)
    data["metrics"] = {
        "rawPapers": raw_count or data["metrics"]["rawPapers"],
        "validCards": card_count or data["metrics"]["validCards"],
        "categories": category_count or data["metrics"]["categories"],
        "weeklyDigests": len(weekly_digests) or data["metrics"]["weeklyDigests"],
        "comparisonCoverage": round(comparison_count / card_count * 100, 1) if card_count else data["metrics"]["comparisonCoverage"],
    }
    data["meta"]["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    data["meta"]["dataMode"] = "live" if cards else "demo"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Dashboard data exported to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

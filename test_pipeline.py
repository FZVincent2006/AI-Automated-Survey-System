"""Full-chain offline integration test for the literature review pipeline.

The script creates mock arXiv-style raw data, simulates structured LLM output
for card generation, runs taxonomy/comparison/weekly digest generation, asserts
that all artifacts are valid, and removes the temporary ``test_*`` files after
everything passes.
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SRC_DIR = PROJECT_ROOT / "src"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from literature_review_system.schema import PaperCard

import generate_cards
import cluster_analysis
import weekly_survey_generator


DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEST_RAW_PATH = DATA_DIR / "test_papers_raw.json"
TEST_CARDS_PATH = DATA_DIR / "test_paper_cards.jsonl"
TEST_TAXONOMY_PATH = DATA_DIR / "test_taxonomy.md"
TEST_COMPARISON_PATH = DATA_DIR / "test_comparison_table.csv"
TEST_WEEKLY_DIGEST_PATH = OUTPUT_DIR / "test_weekly_digest.md"
TEST_STATE_PATH = OUTPUT_DIR / "test_weekly_digest_state.json"


def log_step(message: str) -> None:
    """Print a stable progress log for the integration test."""

    print(f"[INFO] {message}", flush=True)


def ensure_parent_dirs() -> None:
    """Create project data/output directories when missing."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_test_artifacts() -> None:
    """Remove only the temporary test artifacts created by this script."""

    for path in [
        TEST_RAW_PATH,
        TEST_CARDS_PATH,
        TEST_TAXONOMY_PATH,
        TEST_COMPARISON_PATH,
        TEST_WEEKLY_DIGEST_PATH,
        TEST_STATE_PATH,
    ]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def make_mock_raw_papers() -> list[dict[str, Any]]:
    """Hard-code a small set of synthetic arXiv-style raw paper records."""

    return [
        {
            "entry_id": "http://arxiv.org/abs/2601.00001v1",
            "title": "Multi-Agent Debate for Long-Horizon Planning",
            "authors": ["A. Example", "B. Example"],
            "summary": (
                "We study how a group of agents can debate candidate plans to improve "
                "long-horizon task execution under sparse feedback. The method alternates "
                "proposal, critique, and refinement phases and reports stronger planning "
                "stability on reasoning-heavy benchmarks."
            ),
            "published": "2025-02-14T00:00:00+00:00",
            "updated": "2025-02-18T00:00:00+00:00",
            "pdf_url": "http://arxiv.org/pdf/2601.00001v1",
            "primary_category": "cs.AI",
            "categories": ["cs.AI", "cs.CL"],
            "doi": None,
            "journal_ref": None,
            "comment": "Synthetic test record",
            "arxiv_url": "http://arxiv.org/abs/2601.00001v1",
        },
        {
            "entry_id": "http://arxiv.org/abs/2601.00002v1",
            "title": "Tool-Augmented Workflow Planning with Memory",
            "authors": ["C. Example"],
            "summary": (
                "This paper introduces a workflow planner that retrieves external tools and "
                "stores intermediate reasoning traces in memory to coordinate repeated actions. "
                "The approach is evaluated on benchmark tasks that require tool use and state "
                "tracking."
            ),
            "published": "2025-03-03T00:00:00+00:00",
            "updated": "2025-03-04T00:00:00+00:00",
            "pdf_url": "http://arxiv.org/pdf/2601.00002v1",
            "primary_category": "cs.AI",
            "categories": ["cs.AI"],
            "doi": None,
            "journal_ref": None,
            "comment": "Synthetic test record",
            "arxiv_url": "http://arxiv.org/abs/2601.00002v1",
        },
        {
            "entry_id": "http://arxiv.org/abs/2601.00003v1",
            "title": "Retrieval-Grounded Agentic Scheduling",
            "authors": ["D. Example", "E. Example"],
            "summary": (
                "We present a retrieval-grounded scheduler that decomposes task queues into "
                "subgoals and uses retrieved context to choose the next action. The system is "
                "tested in dynamic scheduling scenarios and shows improved success under noisy "
                "input conditions."
            ),
            "published": "2025-04-10T00:00:00+00:00",
            "updated": "2025-04-12T00:00:00+00:00",
            "pdf_url": "http://arxiv.org/pdf/2601.00003v1",
            "primary_category": "cs.CL",
            "categories": ["cs.CL", "cs.AI"],
            "doi": None,
            "journal_ref": None,
            "comment": "Synthetic test record",
            "arxiv_url": "http://arxiv.org/abs/2601.00003v1",
        },
        {
            "entry_id": "http://arxiv.org/abs/2601.00004v1",
            "title": "Self-Correcting Multi-Agent Execution Graphs",
            "authors": ["F. Example"],
            "summary": (
                "The work proposes an execution graph where multiple agents inspect one another's "
                "outputs and trigger correction loops when inconsistency is detected. This design "
                "improves robustness on synthetic coordination tasks but remains sensitive to "
                "prompt design."
            ),
            "published": "2025-05-07T00:00:00+00:00",
            "updated": "2025-05-08T00:00:00+00:00",
            "pdf_url": "http://arxiv.org/pdf/2601.00004v1",
            "primary_category": "cs.AI",
            "categories": ["cs.AI", "cs.LG"],
            "doi": None,
            "journal_ref": None,
            "comment": "Synthetic test record",
            "arxiv_url": "http://arxiv.org/abs/2601.00004v1",
        },
    ]


def write_mock_raw_data() -> None:
    """Write the mock raw arXiv payload to the dedicated test file."""

    payload = {
        "query": "mock pipeline test",
        "fetched_at": "2026-05-23T00:00:00+00:00",
        "years_back": 2,
        "max_results": 4,
        "total_papers": 4,
        "papers": make_mock_raw_papers(),
    }
    TEST_RAW_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_mock_card_from_raw(paper: generate_cards.RawPaper) -> PaperCard:
    """Create a deterministic structured card for a raw paper record."""

    category_hint = "multi-agent coordination"
    if "Tool" in paper.title:
        category_hint = "tool-augmented workflow"
    elif "Retrieval" in paper.title:
        category_hint = "retrieval-grounded planning"
    elif "Self-Correcting" in paper.title:
        category_hint = "self-correction and verification"

    return PaperCard(
        title=paper.title,
        problem=f"{paper.title} 关注的核心问题是如何提升复杂任务中的协同可靠性。",
        key_idea=f"通过原型化的 {category_hint} 思路，将推理、规划与修正机制结合。",
        method=f"The paper uses a structured {category_hint} pipeline with iterative refinement.",
        dataset_or_scenario="Synthetic coordination and reasoning benchmarks",
        metrics="Task success rate, robustness, and consistency",
        results_summary="The method improves execution stability and robustness over baseline workflows.",
        innovation_type="系统方法 / 协同机制",
        limitations="依赖提示与任务设定，外部泛化能力仍有限。",
        best_fit_category=category_hint,
        confidence_level=5,
    )


class FakeCompletionResponse:
    """Minimal response object compatible with beta.chat.completions.parse."""

    def __init__(self, parsed: Any) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(parsed=parsed))]


class MockCompletions:
    """Mock the OpenAI structured parsing endpoint."""

    def __init__(self, cards_by_title: dict[str, PaperCard]) -> None:
        self.cards_by_title = cards_by_title

    @staticmethod
    def _extract_value(content: str, prefix: str) -> str:
        for line in content.splitlines():
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip()
        return ""

    @staticmethod
    def _extract_titles(content: str) -> list[str]:
        titles: list[str] = []
        for line in content.splitlines():
            if line.startswith("[") and "title:" in line:
                titles.append(line.split("title:", 1)[1].split("|", 1)[0].strip())
        return titles

    def parse(self, *, messages: list[dict[str, str]], response_format: Any, **_: Any) -> Any:
        user_content = messages[-1]["content"]
        response_name = getattr(response_format, "__name__", "")

        if response_name == "PaperCard":
            title = self._extract_value(user_content, "title:")
            card = self.cards_by_title.get(title)
            if card is None:
                raise KeyError(f"No mock card configured for title: {title}")
            return FakeCompletionResponse(card)

        if response_name == "TaxonomyResponse":
            categories = sorted({card.best_fit_category for card in self.cards_by_title.values()})
            taxonomy_md = ["# Taxonomy", ""]
            taxonomy_md.append("## 1. Multi-Agent Coordination")
            taxonomy_md.append("- Debate-based planning")
            taxonomy_md.append("- Self-correction and verification")
            taxonomy_md.append("")
            taxonomy_md.append("## 2. Workflow and Retrieval")
            taxonomy_md.append("- Tool-augmented workflow")
            taxonomy_md.append("- Retrieval-grounded planning")
            taxonomy_md.append("")
            taxonomy_md.append("## Category Signals")
            for category in categories:
                taxonomy_md.append(f"- {category}")
            return FakeCompletionResponse(response_format(taxonomy_markdown="\n".join(taxonomy_md).strip()))

        if response_name == "ComparisonBatchResponse":
            titles = self._extract_titles(user_content)
            rows: list[Any] = []
            for title in titles:
                card = self.cards_by_title[title]
                rows.append(
                    cluster_analysis.ComparisonRow(
                        paper_title=card.title,
                        method_name=card.method,
                        time_space_complexity="O(n) time / O(1) extra space (estimated)",
                        application_scenario=card.dataset_or_scenario,
                        pros_cons=f"优点：{card.results_summary}；缺点：{card.limitations}",
                        data_driven="Yes",
                    )
                )
            return FakeCompletionResponse(response_format(rows=rows))

        if response_name == "WeeklyDigestResponse":
            lines = [line.strip() for line in user_content.splitlines() if line.strip().startswith("title=")]
            digest_title = "Weekly Digest: Agentic Workflow Review"
            overview = "本周研究继续围绕多智能体协作、工具增强流程与自我纠错机制展开。"
            technical_evolution = [
                "方法从单体链式推理转向多智能体协作与显式分工，强调任务分解与协调开销的平衡。",
                "工具增强路线更关注工作流编排与记忆管理，适合外部知识密集场景，但复杂度与稳定性并存。",
            ]
            taxonomy_impact = [
                "新增样本强化了 taxonomy 中‘多智能体协同’与‘工具增强工作流’两条主线。",
                "自我纠错与检验机制提示 taxonomy 需要增加‘执行后验证’这一二级补充方向。",
            ]
            research_gaps = [
                "现有工作仍过度依赖合成或局部基准，缺少对长程任务中误差累积与反馈延迟的系统分析。",
                "多数方法在复杂度上尚未建立统一比较标准，未来需要把协调开销、记忆开销与可靠性一起纳入评估。",
            ]
            closing_sentence = "总体来看，领域正从单点性能优化转向可组合、可验证、可扩展的协作系统设计。"
            return FakeCompletionResponse(
                response_format(
                    digest_title=digest_title,
                    overview=overview,
                    technical_evolution=technical_evolution,
                    taxonomy_impact=taxonomy_impact,
                    research_gaps=research_gaps,
                    closing_sentence=closing_sentence,
                )
            )

        raise NotImplementedError(f"Unsupported response format: {response_name}")


class MockClient:
    """A minimal OpenAI-compatible client for offline testing."""

    def __init__(self, cards_by_title: dict[str, PaperCard]) -> None:
        self.beta = SimpleNamespace(chat=SimpleNamespace(completions=MockCompletions(cards_by_title)))


def build_mock_client(raw_papers: list[generate_cards.RawPaper]) -> MockClient:
    """Create a fake client seeded with deterministic PaperCard outputs."""

    cards_by_title = {
        paper.title: build_mock_card_from_raw(paper)
        for paper in raw_papers
    }
    return MockClient(cards_by_title)


def step_generate_cards(raw_papers: list[generate_cards.RawPaper], client: MockClient) -> list[PaperCard]:
    """Run the card-generation logic against the mock client."""

    generated_cards: list[PaperCard] = []
    for index, paper in enumerate(raw_papers, start=1):
        card = generate_cards.parse_card(client=client, model="mock-model", temperature=0.0, paper=paper)
        generate_cards.append_jsonl(TEST_CARDS_PATH, card)
        generated_cards.append(card)
        log_step(f"Step 2.{index}: PaperCard generated and appended for '{paper.title}'.")
    return generated_cards


def assert_jsonl_valid(cards_path: Path) -> None:
    """Validate each JSONL line with PaperCard.model_validate_json."""

    with cards_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            PaperCard.model_validate_json(line)
            log_step(f"Validation: JSONL line {line_number} passed Pydantic validation.")


def step_cluster_analysis(cards: list[PaperCard], client: MockClient) -> None:
    """Run taxonomy and comparison-table generation with the mock client."""

    card_records = cluster_analysis.load_cards(TEST_CARDS_PATH)
    taxonomy_md = cluster_analysis.generate_taxonomy(client=client, model="mock-model", temperature=0.0, cards=card_records)
    cluster_analysis.save_taxonomy(taxonomy_md, TEST_TAXONOMY_PATH)

    comparison_rows: list[dict[str, object]] = []
    for batch in cluster_analysis.chunk_cards(card_records, batch_size=2):
        batch_rows = cluster_analysis.generate_comparison_batch(
            client=client,
            model="mock-model",
            temperature=0.0,
            batch=batch,
        )
        comparison_rows.extend(batch_rows)
    cluster_analysis.save_comparison_table(comparison_rows, TEST_COMPARISON_PATH)
    log_step("Step 3: Taxonomy markdown and comparison CSV generated successfully.")


def assert_comparison_columns(comparison_path: Path) -> None:
    """Check the comparison table contains the required 5 comparison columns."""

    with comparison_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)

    expected_columns = {
        "method_name",
        "time_space_complexity",
        "application_scenario",
        "pros_cons",
        "data_driven",
    }
    actual_columns = set(header)
    if not expected_columns.issubset(actual_columns):
        raise AssertionError(
            f"Comparison table columns invalid. Expected at least {sorted(expected_columns)}, got {header}"
        )

    extra_columns = actual_columns - expected_columns - {"paper_title"}
    if extra_columns:
        raise AssertionError(f"Comparison table contains unexpected extra columns: {sorted(extra_columns)}")

    log_step(f"Validation: comparison table columns verified: {header}")


def step_weekly_digest(client: MockClient) -> None:
    """Run the weekly digest generation logic with the mock client."""

    taxonomy_md = weekly_survey_generator.load_taxonomy(TEST_TAXONOMY_PATH)
    comparison_df = weekly_survey_generator.load_comparison_table(TEST_COMPARISON_PATH)
    cards = weekly_survey_generator.load_cards(TEST_CARDS_PATH)
    state = weekly_survey_generator.load_state(TEST_STATE_PATH)
    new_cards = weekly_survey_generator.select_new_cards(cards, state, lookback=10)

    digest = weekly_survey_generator.generate_weekly_digest(
        client=client,
        model="mock-model",
        temperature=0.0,
        taxonomy_md=taxonomy_md,
        comparison_df=comparison_df,
        new_cards=new_cards,
    )
    markdown = weekly_survey_generator.render_markdown(digest, week_index=1, new_cards=new_cards)
    TEST_WEEKLY_DIGEST_PATH.write_text(markdown, encoding="utf-8")
    TEST_STATE_PATH.write_text(json.dumps({"digest_index": 1, "last_processed_count": len(cards)}, ensure_ascii=False, indent=2), encoding="utf-8")
    log_step("Step 4: Weekly digest markdown generated successfully.")


def assert_files_exist(paths: list[Path]) -> None:
    """Verify the requested artifacts were created."""

    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Missing expected artifact: {path}")
    log_step("Validation: all expected test artifacts exist.")


def main() -> int:
    """Execute the offline integration pipeline test."""

    logging.basicConfig(level=logging.INFO)
    ensure_parent_dirs()
    cleanup_test_artifacts()

    log_step("Step 0: Cleared stale test artifacts.")
    write_mock_raw_data()
    log_step(f"Step 1: Mock data created successfully at {TEST_RAW_PATH}.")

    success = False
    try:
        raw_payload = json.loads(TEST_RAW_PATH.read_text(encoding="utf-8"))
        raw_papers = [
            generate_cards.RawPaper(
                entry_id=paper["entry_id"],
                title=paper["title"],
                summary=paper["summary"],
                arxiv_url=paper["arxiv_url"],
            )
            for paper in raw_payload["papers"]
        ]
        mock_client = build_mock_client(raw_papers)

        generated_cards = step_generate_cards(raw_papers, mock_client)
        assert_jsonl_valid(TEST_CARDS_PATH)

        step_cluster_analysis(generated_cards, mock_client)
        assert_files_exist([TEST_CARDS_PATH, TEST_TAXONOMY_PATH, TEST_COMPARISON_PATH])
        assert_comparison_columns(TEST_COMPARISON_PATH)

        step_weekly_digest(mock_client)
        assert_files_exist(
            [TEST_CARDS_PATH, TEST_TAXONOMY_PATH, TEST_COMPARISON_PATH, TEST_WEEKLY_DIGEST_PATH]
        )

        digest_text = TEST_WEEKLY_DIGEST_PATH.read_text(encoding="utf-8")
        required_sections = [
            "## 1. 本周研究动态总览",
            "## 2. 核心技术路线演进",
            "## 3. 分类体系冲击与补充",
            "## 4. 研究空白与未来方向",
        ]
        for section in required_sections:
            if section not in digest_text:
                raise AssertionError(f"Weekly digest missing section: {section}")

        log_step("Validation: weekly digest contains all required sections.")
        success = True
        log_step("All integration checks passed.")
        return 0

    finally:
        if success:
            cleanup_test_artifacts()
            log_step("Cleanup: removed all temporary test artifacts.")


if __name__ == "__main__":
    raise SystemExit(main())
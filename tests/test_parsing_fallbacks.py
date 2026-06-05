from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SRC_DIR = PROJECT_ROOT / "src"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import cluster_analysis
import generate_cards
import weekly_survey_generator


class _AlwaysFailParse:
    def parse(self, **_):
        raise RuntimeError("structured parse not supported")


class _MockCreate:
    def __init__(self, content: str) -> None:
        self._content = content

    def create(self, **_):
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _MockClient:
    def __init__(self, content: str) -> None:
        self.beta = SimpleNamespace(chat=SimpleNamespace(completions=_AlwaysFailParse()))
        self.chat = SimpleNamespace(completions=_MockCreate(content))


class ParsingFallbackTests(unittest.TestCase):
    def test_generate_cards_fallback_parses_and_injects_title(self) -> None:
        payload = {
            "problem": "核心问题",
            "key_idea": "核心思想",
            "method": "方法描述",
            "dataset_or_scenario": "场景",
            "metrics": "准确率",
            "results_summary": "结果概述",
            "innovation_type": "方法创新",
            "limitations": "局限",
            "best_fit_category": "agent workflow",
            "confidence_level": 4,
        }
        client = _MockClient(json.dumps(payload, ensure_ascii=False))
        paper = generate_cards.RawPaper(
            entry_id="id-1",
            title="A Missing-Title Paper",
            summary="summary",
            arxiv_url="http://arxiv.org/abs/0000.00001",
        )

        card = generate_cards.parse_card(client=client, model="mock", temperature=0.0, paper=paper)

        self.assertEqual(card.title, "A Missing-Title Paper")
        self.assertEqual(card.best_fit_category, "agent workflow")

    def test_cluster_comparison_fallback_parses_code_fence_json(self) -> None:
        rows_payload = [
            {
                "paper_title": "Paper A",
                "method_name": "Method A",
                "time_space_complexity": "O(n)",
                "application_scenario": "planning",
                "pros_cons": "pros/cons",
                "data_driven": "Yes",
            }
        ]
        wrapped = "模型输出如下:\n```json\n" + json.dumps(rows_payload, ensure_ascii=False) + "\n```"
        client = _MockClient(wrapped)

        batch = [
            cluster_analysis.CardRecord(
                title="Paper A",
                problem="p",
                key_idea="k",
                method="m",
                dataset_or_scenario="d",
                metrics="metric",
                results_summary="r",
                innovation_type="i",
                limitations="l",
                best_fit_category="c",
                confidence_level=5,
            )
        ]

        rows = cluster_analysis.generate_comparison_batch(
            client=client,
            model="mock",
            temperature=0.0,
            batch=batch,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["paper_title"], "Paper A")

    def test_cluster_rejects_low_comparison_coverage(self) -> None:
        cards = [
            cluster_analysis.CardRecord(
                title=f"Paper {index}",
                problem="p",
                key_idea="k",
                method="m",
                dataset_or_scenario="d",
                metrics="metric",
                results_summary="r",
                innovation_type="i",
                limitations="l",
                best_fit_category="c",
                confidence_level=5,
            )
            for index in range(2)
        ]
        with self.assertRaisesRegex(ValueError, "coverage"):
            cluster_analysis.validate_comparison_coverage(
                rows=[{"paper_title": "Paper 0"}],
                cards=cards,
                minimum_coverage=0.9,
            )

    def test_weekly_digest_shortcut_field_returns_markdown(self) -> None:
        original_base_url = os.environ.get("OPENAI_BASE_URL")
        os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com/v1"
        try:
            payload = {"weekly_digest": "# Weekly\n\n- item 1\n- item 2"}
            client = _MockClient(json.dumps(payload, ensure_ascii=False))

            comparison_df = pd.DataFrame(
                [
                    {
                        "paper_title": "Paper A",
                        "method_name": "Method A",
                        "time_space_complexity": "O(n)",
                        "application_scenario": "planning",
                        "pros_cons": "pros/cons",
                        "data_driven": "Yes",
                    }
                ]
            )
            new_cards = [
                weekly_survey_generator.CardRecord(
                    title="Paper A",
                    problem="p",
                    key_idea="k",
                    method="m",
                    dataset_or_scenario="d",
                    metrics="metric",
                    results_summary="r",
                    innovation_type="i",
                    limitations="l",
                    best_fit_category="c",
                    confidence_level=5,
                )
            ]

            digest = weekly_survey_generator.generate_weekly_digest(
                client=client,
                model="mock",
                temperature=0.0,
                taxonomy_md="# Taxonomy\n\n## C",
                comparison_df=comparison_df,
                new_cards=new_cards,
            )

            self.assertIsInstance(digest, str)
            self.assertIn("# Weekly", digest)
        finally:
            if original_base_url is None:
                os.environ.pop("OPENAI_BASE_URL", None)
            else:
                os.environ["OPENAI_BASE_URL"] = original_base_url


if __name__ == "__main__":
    unittest.main()

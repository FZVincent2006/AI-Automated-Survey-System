from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.analyze import parse_model_json
from scripts.export_dashboard_data import card_to_dashboard_paper


class DashboardIntegrationTests(unittest.TestCase):
    def test_dashboard_demo_data_has_required_sections(self) -> None:
        payload = json.loads(
            (PROJECT_ROOT / "web" / "data" / "dashboard-data.json").read_text(
                encoding="utf-8"
            )
        )

        required = {
            "meta",
            "metrics",
            "pipeline",
            "categories",
            "papers",
            "taxonomy",
            "insights",
            "weeklyDigests",
            "finalSurvey",
        }
        self.assertTrue(required.issubset(payload))
        self.assertGreaterEqual(len(payload["weeklyDigests"]), 3)
        self.assertGreaterEqual(len(payload["papers"]), 10)

    def test_live_parser_accepts_json_code_fence(self) -> None:
        payload = {
            "title": "Paper",
            "problem": "Problem",
            "key_idea": "Idea",
            "method": "Method",
            "dataset_or_scenario": "Scenario",
            "metrics": "Metrics",
            "results_summary": "Results",
            "innovation_type": "Innovation",
            "limitations": "Limitations",
            "best_fit_category": "Category",
            "confidence_level": 4,
        }

        parsed = parse_model_json(f"```json\n{json.dumps(payload)}\n```")

        self.assertEqual(parsed["title"], "Paper")
        self.assertEqual(parsed["confidence_level"], 4)

    def test_card_export_preserves_source_metadata(self) -> None:
        card = {
            "title": "Paper",
            "problem": "Problem",
            "key_idea": "Idea",
            "method": "Method",
            "dataset_or_scenario": "Scenario",
            "metrics": "Metrics",
            "results_summary": "Results",
            "innovation_type": "Innovation",
            "limitations": "Limitations",
            "best_fit_category": "Category",
            "confidence_level": 5,
        }
        raw = {
            "authors": ["A. Author"],
            "published": "2026-01-02T00:00:00+00:00",
            "arxiv_url": "https://arxiv.org/abs/1234.5678",
        }

        paper = card_to_dashboard_paper(card, raw, {}, 0)

        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["authors"], ["A. Author"])
        self.assertEqual(paper["url"], raw["arxiv_url"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_arxiv
import run_pipeline


class FetchConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = {
            "ARXIV_SEARCH_QUERY": os.environ.get("ARXIV_SEARCH_QUERY"),
            "ARXIV_MAX_RESULTS": os.environ.get("ARXIV_MAX_RESULTS"),
            "ARXIV_YEARS_BACK": os.environ.get("ARXIV_YEARS_BACK"),
        }

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_resolve_fetch_settings_prefers_cli_over_env(self) -> None:
        os.environ["ARXIV_SEARCH_QUERY"] = "env query"
        os.environ["ARXIV_MAX_RESULTS"] = "30"
        os.environ["ARXIV_YEARS_BACK"] = "3"

        args = argparse.Namespace(query="cli query", max_results=12, years_back=1)
        query, max_results, years_back = fetch_arxiv.resolve_fetch_settings(args)

        self.assertEqual(query, "cli query")
        self.assertEqual(max_results, 12)
        self.assertEqual(years_back, 1)

    def test_resolve_fetch_settings_uses_env_then_default(self) -> None:
        os.environ["ARXIV_SEARCH_QUERY"] = "env query"
        os.environ["ARXIV_MAX_RESULTS"] = "25"
        os.environ["ARXIV_YEARS_BACK"] = "2"

        args = argparse.Namespace(query=None, max_results=None, years_back=None)
        query, max_results, years_back = fetch_arxiv.resolve_fetch_settings(args)

        self.assertEqual(query, "env query")
        self.assertEqual(max_results, 25)
        self.assertEqual(years_back, 2)


class RunPipelineFetchArgTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = {
            "ARXIV_SEARCH_QUERY": os.environ.get("ARXIV_SEARCH_QUERY"),
            "ARXIV_MAX_RESULTS": os.environ.get("ARXIV_MAX_RESULTS"),
            "ARXIV_YEARS_BACK": os.environ.get("ARXIV_YEARS_BACK"),
        }

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_build_fetch_args_uses_env_when_cli_missing(self) -> None:
        os.environ["ARXIV_SEARCH_QUERY"] = "env query"
        os.environ["ARXIV_MAX_RESULTS"] = "22"
        os.environ["ARXIV_YEARS_BACK"] = "4"

        args = argparse.Namespace(query=None, max_results=None, years_back=None)
        result = run_pipeline.build_fetch_args(args)

        self.assertEqual(
            result,
            ["--query", "env query", "--max-results", "22", "--years-back", "4"],
        )

    def test_build_fetch_args_prefers_cli_values(self) -> None:
        os.environ["ARXIV_SEARCH_QUERY"] = "env query"
        os.environ["ARXIV_MAX_RESULTS"] = "22"
        os.environ["ARXIV_YEARS_BACK"] = "4"

        args = argparse.Namespace(query="cli query", max_results=10, years_back=2)
        result = run_pipeline.build_fetch_args(args)

        self.assertEqual(
            result,
            ["--query", "cli query", "--max-results", "10", "--years-back", "2"],
        )

    def test_build_fetch_args_adds_append_flag(self) -> None:
        os.environ.pop("ARXIV_SEARCH_QUERY", None)
        os.environ.pop("ARXIV_MAX_RESULTS", None)
        os.environ.pop("ARXIV_YEARS_BACK", None)
        args = argparse.Namespace(
            query=None,
            max_results=None,
            years_back=None,
            append_fetch=True,
        )

        self.assertEqual(run_pipeline.build_fetch_args(args), ["--append"])

    def test_final_submission_ready_counts_cards_and_digests(self) -> None:
        original_cards_path = run_pipeline.CARDS_PATH
        original_output_dir = run_pipeline.OUTPUT_DIR
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                cards_path = root / "paper_cards.jsonl"
                output_dir = root / "output"
                output_dir.mkdir()
                cards_path.write_text("\n".join("{}" for _ in range(50)), encoding="utf-8")
                for index in range(1, 4):
                    (output_dir / f"weekly_digest_第{index}周.md").write_text(
                        "# digest",
                        encoding="utf-8",
                    )
                run_pipeline.CARDS_PATH = cards_path
                run_pipeline.OUTPUT_DIR = output_dir

                self.assertEqual(run_pipeline.final_submission_ready(), (True, 50, 3))
        finally:
            run_pipeline.CARDS_PATH = original_cards_path
            run_pipeline.OUTPUT_DIR = original_output_dir


if __name__ == "__main__":
    unittest.main()

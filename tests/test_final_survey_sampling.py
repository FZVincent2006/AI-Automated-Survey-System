from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import final_survey_generator


class FinalSurveySamplingTests(unittest.TestCase):
    def test_evenly_spaced_indices_cover_full_range(self) -> None:
        indices = final_survey_generator.sample_evenly_spaced_indices(100, 5)

        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 99)
        self.assertIn(50, indices)
        self.assertEqual(len(indices), 5)

    def test_adaptive_sample_count_caps_and_scales(self) -> None:
        self.assertEqual(final_survey_generator.adaptive_sample_count(10, 3, 8, 0.5), 5)
        self.assertEqual(final_survey_generator.adaptive_sample_count(500, 20, 60, 0.2), 60)

    def test_validation_rejects_incomplete_submission(self) -> None:
        cards = [
            final_survey_generator.CardRecord(
                title="Paper",
                key_idea="Idea",
                method="Method",
                best_fit_category="Category",
            )
        ]
        with self.assertRaisesRegex(ValueError, "at least 50"):
            final_survey_generator.validate_final_artifacts(
                markdown=(
                    "# Survey\n## Abstract\nA\n## Introduction\nB\n"
                    "## Taxonomy Analysis\nC\n## Comparative Analysis\nD\n"
                    "## Trend Insights\nE\n## Future Directions\nF\n## Conclusion\nG"
                ),
                cards=cards,
                weekly_digests=[],
                min_papers=50,
                min_weekly_digests=3,
                min_chars=1,
                max_chars=0,
                allow_incomplete=False,
            )

    def test_main_report_length_excludes_appendix(self) -> None:
        markdown = "# Survey\n正文\n## Appendix: Included Paper Titles\n" + ("Paper\n" * 100)
        self.assertLess(
            final_survey_generator.count_content_characters(
                final_survey_generator.main_report_markdown(markdown)
            ),
            20,
        )


if __name__ == "__main__":
    unittest.main()

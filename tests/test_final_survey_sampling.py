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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import weekly_survey_generator


class WeeklyReportValidationTests(unittest.TestCase):
    def test_weekly_validation_rejects_short_report(self) -> None:
        markdown = """
# Weekly
## 1. 本周研究动态总览
短。
## 2. 核心技术路线演进
短。
## 3. 分类体系冲击与补充
短。
## 4. 研究空白与未来方向
短。
"""
        with self.assertRaisesRegex(ValueError, "too short"):
            weekly_survey_generator.validate_weekly_markdown(
                markdown,
                min_chars=100,
                max_chars=1000,
            )

    def test_weekly_validation_accepts_required_sections(self) -> None:
        body = "分析内容" * 40
        markdown = f"""
# Weekly
## 1. 本周研究动态总览
{body}
## 2. 核心技术路线演进
{body}
## 3. 分类体系冲击与补充
{body}
## 4. 研究空白与未来方向
{body}
"""
        weekly_survey_generator.validate_weekly_markdown(
            markdown,
            min_chars=100,
            max_chars=2000,
        )


if __name__ == "__main__":
    unittest.main()

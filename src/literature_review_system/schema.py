"""Strict schemas for structured literature review cards.

The goal of this module is to constrain downstream LLM output to the exact
fields required by the course project, with no extra or invented keys.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PaperCard(BaseModel):
    """A strictly structured card for one paper."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str = Field(description="论文标题")
    problem: str = Field(description="论文解决的核心问题")
    key_idea: str = Field(description="核心思想")
    method: str = Field(description="提出的方法")
    dataset_or_scenario: str = Field(description="实验数据集或应用场景")
    metrics: str = Field(description="评价指标")
    results_summary: str = Field(description="实验结果摘要")
    innovation_type: str = Field(description="创新类型")
    limitations: str = Field(description="局限性")
    best_fit_category: str = Field(description="最符合的分类标签")
    confidence_level: int | str = Field(description="置信度评分")
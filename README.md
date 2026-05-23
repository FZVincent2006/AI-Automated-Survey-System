# AI 辅助自动化文献综述系统

[![Python](https://img.shields.io/badge/Python-3.14%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Status](https://img.shields.io/badge/Status-Open%20Source-brightgreen.svg)

一个面向课程大作业的 Python 项目，用来自动抓取 arXiv 前沿论文、抽取结构化论文卡片、生成分类体系、对比表、周报和最终综述报告。

项目重点不是单次摘要，而是把“检索 - 结构化抽取 - 聚类分析 - 周报生成 - 最终报告”串成一条可复用、可回归、可持续运行的流水线。

仓库已按开源提交整理：真实密钥不入库，环境变量通过 `.env` 本地加载，默认示例配置放在 [.env.example](.env.example)。

## 项目状态

- 已完成核心流水线实现：抓取、卡片生成、聚类分析、周报、最终报告。
- 已完成 DeepSeek 兼容与文本回退解析。
- 已完成离线集成测试与解析边界单测。
- 当前适合提交课程作业，也适合开源展示与继续迭代。

## 开源说明

- 本仓库默认不包含真实 API Key 或私密配置。
- `.env` 已加入 `.gitignore`，请在本地单独维护。
- 示例配置文件 [.env.example](.env.example) 仅用于说明环境变量格式。

## 主要功能

- 自动抓取 arXiv 上的前沿论文，支持查询词、时间窗口和结果数量配置。
- 使用严格的 Pydantic Schema 生成论文卡片，方便后续聚类和统计。
- 自动产出 taxonomy（分类树）与 comparison table（对比表）。
- 基于新增论文生成周报 Markdown，支持增量运行。
- 基于全部产物生成最终综述报告。
- 支持 DeepSeek 兼容 OpenAI API、结构化输出与文本降级解析。
- 内置离线集成测试，便于在没有真实 API Key 的环境下验证主流程。

## 技术栈

- Python 3.14+
- `arxiv`
- `openai`
- `pydantic`
- `pandas`
- `python-dotenv`
- `tenacity`

## 项目结构

```text
scripts/
  fetch_arxiv.py              # 抓取 arXiv 原始论文数据
  generate_cards.py           # 生成结构化论文卡片 JSONL
  cluster_analysis.py         # 生成 taxonomy 和 comparison table
  weekly_survey_generator.py  # 生成周报
  final_survey_generator.py   # 生成最终综述报告
  run_pipeline.py             # 一键运行全流程

src/literature_review_system/
  schema.py                   # 论文卡片 Pydantic Schema

data/
  papers_raw.json             # 原始抓取结果
  paper_cards.jsonl           # 论文卡片
  taxonomy.md                 # 分类树
  comparison_table.csv        # 对比表

output/
  weekly_digest_第N周.md      # 周报
  final_survey.md             # 最终综述报告

tests/
  test_parsing_fallbacks.py    # 解析回退测试
  test_fetch_pipeline_config.py# 抓取与管道配置测试
test_pipeline.py              # 全链路离线集成测试
```

## 快速开始

### 1. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

复制一份 `.env.example` 为 `.env`，然后填写你的密钥和参数。

必须配置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

可选配置：

- `ARXIV_SEARCH_QUERY`
- `ARXIV_MAX_RESULTS`
- `ARXIV_YEARS_BACK`

示例：

```env
OPENAI_API_KEY=your_deepseek_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-v4-pro

ARXIV_SEARCH_QUERY="(agentic OR \"multi-agent\" OR \"llm agent\" OR \"agent workflow\" OR \"tool use\" OR \"reasoning-action\") AND (cat:cs.AI OR cat:cs.CL OR cat:cs.LG OR cat:cs.RO)"
ARXIV_MAX_RESULTS=20
ARXIV_YEARS_BACK=2
```

## 运行方式

### 一键运行全流程

```powershell
.\.venv\Scripts\python.exe scripts/run_pipeline.py
```

### 分步运行

```powershell
.\.venv\Scripts\python.exe scripts/fetch_arxiv.py
.\.venv\Scripts\python.exe scripts/generate_cards.py
.\.venv\Scripts\python.exe scripts/cluster_analysis.py
.\.venv\Scripts\python.exe scripts/weekly_survey_generator.py
.\.venv\Scripts\python.exe scripts/final_survey_generator.py
```

### 只运行抓取阶段并自定义参数

```powershell
.\.venv\Scripts\python.exe scripts/fetch_arxiv.py --query "Agentic Workflow" --max-results 30 --years-back 3
```

### 跳过抓取，直接从已有数据继续

```powershell
.\.venv\Scripts\python.exe scripts/run_pipeline.py --skip-fetch
```

## 输出结果

- `data/papers_raw.json`：抓取到的原始 arXiv 记录
- `data/paper_cards.jsonl`：结构化论文卡片
- `data/taxonomy.md`：分类体系
- `data/comparison_table.csv`：论文方法对比表
- `output/weekly_digest_第N周.md`：每周综述
- `output/final_survey.md`：最终综述报告

## 测试

推荐先跑离线测试，确认主流程没有问题：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe test_pipeline.py
```

## 设计特点

- **结构化优先**：论文卡片、周报和最终报告都尽量使用严格结构化输出。
- **兼容性优先**：针对 DeepSeek 等 OpenAI-compatible provider 做了文本回退解析。
- **可恢复运行**：JSONL 流式写入与状态文件支持增量处理。
- **可验证**：提供解析边界单测和全链路离线集成测试。

## 注意事项

- 不要把真实 API Key 提交到仓库里；请把 `.env` 加入本地环境，不要提交。
- arXiv 抓取结果会随时间变化，重复运行时产物可能略有不同。
- 如果模型输出不符合结构要求，脚本会尽量降级解析，并把失败样本写入 `data/debug/`。

## 开源许可

本项目采用 [MIT License](LICENSE)。如果你在此基础上继续开发或二次分发，请保留原始许可声明。

## 适合的使用场景

- 课程大作业
- 文献综述自动化实验
- 学术趋势跟踪
- LLM 结构化抽取与流水线编排演示

## 后续可扩展方向

- 增加更细粒度的主题聚类与图谱可视化。
- 引入自动评估指标，比如覆盖率、重复率和多样性得分。
- 增加更多数据源，例如 Semantic Scholar、OpenAlex 或 Crossref。

"""Vercel serverless endpoint for one-paper live analysis."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler


MAX_TITLE_LENGTH = 500
MAX_ABSTRACT_LENGTH = 12_000
REQUIRED_FIELDS = {
    "title",
    "problem",
    "key_idea",
    "method",
    "dataset_or_scenario",
    "metrics",
    "results_summary",
    "innovation_type",
    "limitations",
    "best_fit_category",
    "confidence_level",
}


SYSTEM_PROMPT = """你是严谨的学术论文信息抽取助手。
仅根据用户提供的英文论文标题和摘要生成中文结构化论文卡片，不得使用外部知识补全。
摘要没有提供的信息必须写“摘要未明确说明”，不得虚构数据集、指标或实验结论。
只返回一个 JSON 对象，不要返回 Markdown 或解释文字。
字段必须严格为：
title, problem, key_idea, method, dataset_or_scenario, metrics,
results_summary, innovation_type, limitations, best_fit_category, confidence_level。
confidence_level 使用 1-5 的整数。
"""


def parse_model_json(content: str) -> dict[str, object]:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("Model response is not a JSON object.")
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        raise ValueError(f"Model response is missing fields: {sorted(missing)}")
    return {field: payload[field] for field in REQUIRED_FIELDS}


def call_model(title: str, abstract: str) -> dict[str, object]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    base_url = (os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL") or "deepseek-chat"
    request_body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"title: {title}\n\nabstract: {abstract}",
            },
        ],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    content = response_payload["choices"][0]["message"]["content"]
    result = parse_model_json(content)
    result["title"] = title
    return result


class handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 20_000:
                self.send_json(400, {"error": "Invalid request size."})
                return

            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            title = str(payload.get("title") or "").strip()
            abstract = str(payload.get("abstract") or "").strip()
            if not title or not abstract:
                self.send_json(400, {"error": "Title and abstract are required."})
                return
            if len(title) > MAX_TITLE_LENGTH or len(abstract) > MAX_ABSTRACT_LENGTH:
                self.send_json(400, {"error": "Input is too long."})
                return

            self.send_json(200, call_model(title, abstract))
        except urllib.error.HTTPError as exc:
            self.send_json(502, {"error": f"Model provider returned HTTP {exc.code}."})
        except Exception as exc:  # Keep secrets and provider payloads out of responses.
            print(f"Live analysis failed: {type(exc).__name__}: {exc}")
            self.send_json(503, {"error": "Live analysis is temporarily unavailable."})

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        self.send_json(405, {"error": "Use POST."})

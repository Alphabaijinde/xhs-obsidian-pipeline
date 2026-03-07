#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
AI enrich helpers for chat->note ingestion.

Uses OpenCode CLI with a free model by default:
  opencode/minimax-m2.5-free
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

DEFAULT_OPENCODE_MODEL = os.environ.get("OPENCODE_MODEL", "opencode/minimax-m2.5-free")
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "opencode")


def _safe_path_env() -> str:
    """Ensure /usr/sbin exists in PATH for opencode runtime checks."""
    current = os.environ.get("PATH", "")
    parts = current.split(":") if current else []
    if "/usr/sbin" not in parts:
        parts.append("/usr/sbin")
    return ":".join([p for p in parts if p])


def run_opencode_json_prompt(prompt: str, model: str = DEFAULT_OPENCODE_MODEL, timeout: int = 120) -> str:
    """Run opencode and return assistant text payload extracted from JSON event stream."""
    env = os.environ.copy()
    env["PATH"] = _safe_path_env()

    cmd = [
        OPENCODE_BIN,
        "run",
        prompt,
        "--model",
        model,
        "--format",
        "json",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )

    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "opencode failed").strip())

    text_parts: list[str] = []
    for raw in proc.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            evt = json.loads(raw)
        except Exception:
            continue
        if evt.get("type") != "text":
            continue
        part = evt.get("part") or {}
        t = str(part.get("text") or "").strip()
        if t:
            text_parts.append(t)

    return "\n".join(text_parts).strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract first JSON object from text."""
    s = str(text or "").strip()
    if not s:
        return {}

    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", s)
    if not match:
        return {}

    candidate = match.group(0)
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def ai_ingest_plan(message: str, urls: list[str], model: str = DEFAULT_OPENCODE_MODEL) -> dict[str, Any]:
    """
    Ask AI for ingestion intent and tags.
    Returns stable dict even on failure.
    """
    base = {
        "intent": "save" if urls else "ignore",
        "summary": "检测到链接，默认执行入库" if urls else "未检测到链接，跳过入库",
        "tags": [],
        "priority": "medium" if urls else "low",
    }

    prompt = f"""
你是一个“链接入库策略助手”。
请根据用户消息和链接列表，输出严格 JSON（不要 markdown，不要解释）：

{{
  "intent": "save|ignore|ask",
  "summary": "一句中文总结",
  "tags": ["标签1", "标签2"],
  "priority": "low|medium|high"
}}

规则：
1) 有明确 URL 且看起来是内容分享时，intent 优先 save。
2) tags 最多 5 个，中文短词。
3) 如果信息不足，intent 可为 ask。

用户消息：{message}
URL 列表：{urls}
""".strip()

    try:
        raw = run_opencode_json_prompt(prompt, model=model)
        obj = _extract_json_object(raw)
        if not obj:
            return base

        intent = str(obj.get("intent") or "").strip().lower()
        if intent not in {"save", "ignore", "ask"}:
            intent = base["intent"]

        priority = str(obj.get("priority") or "").strip().lower()
        if priority not in {"low", "medium", "high"}:
            priority = base["priority"]

        tags = obj.get("tags") or []
        cleaned_tags = []
        for tag in tags if isinstance(tags, list) else []:
            t = re.sub(r"\s+", "", str(tag or ""))
            t = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5_\-]", "", t)
            if not t:
                continue
            if t not in cleaned_tags:
                cleaned_tags.append(t)
            if len(cleaned_tags) >= 5:
                break

        return {
            "intent": intent,
            "summary": str(obj.get("summary") or base["summary"]).strip()[:120],
            "tags": cleaned_tags,
            "priority": priority,
        }
    except Exception as e:
        fallback = dict(base)
        fallback["summary"] = f"AI策略降级：{e}"
        return fallback

#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Chat bridge for URL ingestion.

Purpose:
- Receive chat text (Feishu/WeChat/other bridge)
- Extract URLs
- Use OpenCode free model for lightweight routing/tags
- Save notes through existing url_reader pipeline

Run server:
  python scripts/chat_bridge.py serve --host 127.0.0.1 --port 8765

POST /ingest payload:
{
  "text": "消息正文，包含链接",
  "source": "feishu|wechat|other",
  "sender": "alice",
  "chat_id": "optional",
  "token": "optional if BRIDGE_TOKEN not set"
}
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ai_enricher import DEFAULT_OPENCODE_MODEL, ai_ingest_plan
from url_reader import (
    DEFAULT_OUTPUT_DIR,
    extract_urls_from_text,
    read_url,
    save_content,
)

BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")


def _merge_tags(base_tags: list[str] | None, ai_tags: list[str] | None) -> list[str]:
    out: list[str] = []
    for seq in (base_tags or [], ai_tags or []):
        for tag in seq:
            t = str(tag or "").strip()
            if not t:
                continue
            if t not in out:
                out.append(t)
    return out[:8]


def ingest_text_message(
    text: str,
    source: str = "unknown",
    sender: str = "",
    chat_id: str = "",
    output_dir: str | None = None,
    use_ai: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    message = str(text or "").strip()
    urls = extract_urls_from_text(message)

    plan = {
        "intent": "save" if urls else "ignore",
        "summary": "默认规则：有链接则入库",
        "tags": [],
        "priority": "medium" if urls else "low",
    }
    if use_ai:
        plan = ai_ingest_plan(message, urls)

    if not urls:
        return {
            "success": True,
            "processed": 0,
            "saved": [],
            "plan": plan,
            "message": "未检测到 URL，未执行入库",
            "source": source,
            "sender": sender,
            "chat_id": chat_id,
        }

    if plan.get("intent") == "ignore" and not force:
        return {
            "success": True,
            "processed": 0,
            "saved": [],
            "plan": plan,
            "message": "AI判定忽略，本次未入库（可 force=true 强制）",
            "source": source,
            "sender": sender,
            "chat_id": chat_id,
        }

    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    saved = []
    failed = []

    for url in urls:
        result = read_url(url, verbose=False, prefer_playwright_for_xiaohongshu=True)
        if not result.get("success"):
            failed.append({"url": url, "errors": result.get("errors", [])})
            continue

        metadata = result.get("metadata", {})
        platform = result.get("platform", {})

        base_tags = metadata.get("tags", [])
        merged_tags = _merge_tags(base_tags, plan.get("tags", []))

        note_id_value = str(metadata.get("noteId") or "").strip()

        save_result = save_content(
            content=metadata.get("contentText") or metadata.get("content") or result.get("content", ""),
            url=url,
            platform_name=platform.get("name", "未知"),
            output_dir=target_dir,
            title=metadata.get("title"),
            author=metadata.get("author"),
            images=metadata.get("images", []),
            likes=str(metadata.get("likes", "")),
            collects=str(metadata.get("collects", "")),
            comments=str(metadata.get("comments", "")),
            tags=merged_tags,
            hashtags=metadata.get("hashtags", []),
            edit_info=str(metadata.get("editInfo", "")),
            hot_comments=metadata.get("hotComments", []),
            note_id=note_id_value,
            author_id=str(metadata.get("authorId", "")),
            xiaohongshu_id=str(metadata.get("xiaohongshuId", "")),
            verbose=False,
        )

        if save_result.get("success"):
            saved.append(
                {
                    "url": url,
                    "title": save_result.get("title", ""),
                    "dir": save_result.get("dir", ""),
                    "md_file": save_result.get("md_file", ""),
                    "images": save_result.get("images", 0),
                }
            )
        else:
            failed.append({"url": url, "errors": ["save failed"]})

    return {
        "success": len(saved) > 0,
        "processed": len(urls),
        "saved": saved,
        "failed": failed,
        "plan": plan,
        "source": source,
        "sender": sender,
        "chat_id": chat_id,
        "output_dir": target_dir,
        "model": DEFAULT_OPENCODE_MODEL,
    }


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "URLReaderBridge/0.1"

    def _write_json(self, payload: dict[str, Any], status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._write_json({"ok": True, "service": "chat_bridge"})
            return
        self._write_json({"error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        if self.path != "/ingest":
            self._write_json({"error": "not found"}, status=404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw = self.rfile.read(content_length) if content_length > 0 else b""

        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._write_json({"error": "invalid json"}, status=400)
            return

        body_token = str(payload.get("token") or "")
        header_token = str(self.headers.get("x-bridge-token") or "")
        if BRIDGE_TOKEN and BRIDGE_TOKEN not in {body_token, header_token}:
            self._write_json({"error": "unauthorized"}, status=401)
            return

        text = str(payload.get("text") or "").strip()
        if not text:
            self._write_json({"error": "text is required"}, status=400)
            return

        result = ingest_text_message(
            text=text,
            source=str(payload.get("source") or "unknown"),
            sender=str(payload.get("sender") or ""),
            chat_id=str(payload.get("chat_id") or ""),
            output_dir=str(payload.get("output_dir") or "").strip() or None,
            use_ai=bool(payload.get("use_ai", True)),
            force=bool(payload.get("force", False)),
        )
        self._write_json(result, status=200)


def run_server(host: str, port: int):
    server = ThreadingHTTPServer((host, port), BridgeHandler)
    print(f"[chat-bridge] listening on http://{host}:{port}")
    print(f"[chat-bridge] endpoint: POST /ingest, GET /health")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Chat bridge for URL Reader")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run HTTP bridge server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)

    p_ingest = sub.add_parser("ingest", help="ingest one message from CLI")
    p_ingest.add_argument("text", help="chat message text")
    p_ingest.add_argument("--source", default="cli")
    p_ingest.add_argument("--sender", default="")
    p_ingest.add_argument("--chat-id", default="")
    p_ingest.add_argument("--output-dir", default="")
    p_ingest.add_argument("--no-ai", action="store_true")
    p_ingest.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if args.cmd == "serve":
        run_server(args.host, args.port)
        return

    if args.cmd == "ingest":
        result = ingest_text_message(
            text=args.text,
            source=args.source,
            sender=args.sender,
            chat_id=args.chat_id,
            output_dir=args.output_dir or None,
            use_ai=not args.no_ai,
            force=args.force,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()

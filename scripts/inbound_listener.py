#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Inbound listener MVP for chat platforms.

目标：先跑通“微信监听 -> 入库”最小闭环；随后复用同一监听器支持飞书。

Run:
  python scripts/inbound_listener.py --source wechat --host 127.0.0.1 --port 8877
  python scripts/inbound_listener.py --source feishu --host 127.0.0.1 --port 8878

POST /event payload（MVP 宽松字段）:
{
  "text": "帮我存这个 https://...",
  "sender": "alice",
  "chat_id": "group-1"
}

常见别名字段也支持：
- text/content/msg/message
- sender/from/user/user_name
- chat_id/conversation_id/chat
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from chat_bridge import ingest_text_message


LISTENER_TOKEN = os.environ.get("LISTENER_TOKEN", "")


def _pick(payload: dict[str, Any], keys: list[str], default: str = "") -> str:
    for k in keys:
        val = payload.get(k)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return default


class InboundHandler(BaseHTTPRequestHandler):
    server_version = "InboundListener/0.1"

    def _write_json(self, payload: dict[str, Any], status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @property
    def source(self) -> str:
        return str(getattr(self.server, "source", "unknown"))

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._write_json({"ok": True, "service": "inbound_listener", "source": self.source})
            return
        self._write_json({"error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        if self.path != "/event":
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
        header_token = str(self.headers.get("x-listener-token") or "")
        if LISTENER_TOKEN and LISTENER_TOKEN not in {body_token, header_token}:
            self._write_json({"error": "unauthorized"}, status=401)
            return

        text = _pick(payload, ["text", "content", "msg", "message"])
        if not text:
            self._write_json({"error": "text is required"}, status=400)
            return

        sender = _pick(payload, ["sender", "from", "user", "user_name"])
        chat_id = _pick(payload, ["chat_id", "conversation_id", "chat"]) 

        result = ingest_text_message(
            text=text,
            source=self.source,
            sender=sender,
            chat_id=chat_id,
            output_dir=_pick(payload, ["output_dir"]) or None,
            use_ai=bool(payload.get("use_ai", True)),
            force=bool(payload.get("force", False)),
        )
        self._write_json(result, status=200)


def run_server(source: str, host: str, port: int):
    server = ThreadingHTTPServer((host, port), InboundHandler)
    setattr(server, "source", source)
    print(f"[inbound-listener] source={source} listening on http://{host}:{port}")
    print("[inbound-listener] endpoint: POST /event, GET /health")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Inbound listener MVP for WeChat/Feishu")
    parser.add_argument("--source", choices=["wechat", "feishu"], required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    run_server(args.source, args.host, args.port)


if __name__ == "__main__":
    main()

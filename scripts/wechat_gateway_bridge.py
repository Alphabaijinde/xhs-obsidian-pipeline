#!/usr/bin/env python3

from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests


def _pick(payload: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _deep_get(payload: dict[str, Any], paths: list[list[str]]) -> str:
    for path in paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current.get(key)
        if current is None:
            continue
        text = str(current).strip()
        if text:
            return text
    return ""


def _normalize_text(text: str) -> str:
    return html.unescape(str(text or "").replace("<br/>", "\n")).strip()


def normalize_message(payload: dict[str, Any]) -> dict[str, str] | None:
    type_name = _pick(payload, ["TypeName", "type_name"])
    data = (
        payload.get("Data")
        if isinstance(payload.get("Data"), dict)
        else payload.get("data")
    )

    if type_name == "AddMsg" and isinstance(data, dict):
        from_id = _deep_get(data, [["FromUserName", "string"], ["FromUserName"]])
        to_id = _deep_get(data, [["ToUserName", "string"], ["ToUserName"]])
        content = _normalize_text(_deep_get(data, [["Content", "string"], ["Content"]]))
        message_id = _pick(data, ["MsgId", "NewMsgId", "msgId", "newMsgId"])
        if not content:
            return None

        sender = from_id
        chat_id = from_id or to_id
        text = content

        if from_id.endswith("@chatroom"):
            chat_id = from_id
            if ":\n" in content:
                sender, text = content.split(":\n", 1)
                sender = sender.strip() or from_id
                text = text.strip()
        elif to_id.endswith("@chatroom"):
            chat_id = to_id
        elif from_id == "filehelper" or to_id == "filehelper":
            chat_id = "filehelper"
            sender = "filehelper"

        text = _normalize_text(text)
        if not text:
            return None
        return {
            "text": text,
            "sender": sender,
            "chat_id": chat_id,
            "message_id": message_id,
        }

    text = _normalize_text(
        _pick(payload, ["text", "content", "msg", "message", "raw_message"])
    )
    if not text:
        return None
    sender = _pick(
        payload,
        ["sender", "from", "user", "user_name", "from_user", "fromWxid", "user_id"],
    )
    chat_id = _pick(
        payload, ["chat_id", "conversation_id", "chat", "toWxid", "room_id", "group_id"]
    )
    message_id = _pick(payload, ["message_id", "msg_id", "MsgId", "id"])
    return {
        "text": text,
        "sender": sender,
        "chat_id": chat_id,
        "message_id": message_id,
    }


def should_forward(message: dict[str, str], listen_mode: str) -> bool:
    if listen_mode == "all":
        return True
    return str(message.get("chat_id") or "").strip() == "filehelper"


class GatewayBridge:
    def __init__(
        self,
        target_url: str,
        token: str,
        timeout: int,
        use_ai: bool,
        force: bool,
        dedupe_size: int,
    ):
        self.target_url = target_url
        self.token = token
        self.timeout = timeout
        self.use_ai = use_ai
        self.force = force
        self.dedupe_size = max(100, dedupe_size)
        self._seen: set[str] = set()
        self._seen_order: collections.deque[str] = collections.deque()

    def _dedupe_key(self, message: dict[str, str]) -> str:
        message_id = str(message.get("message_id") or "").strip()
        if message_id:
            return f"id:{message_id}"
        raw = f"{message.get('chat_id', '')}:{message.get('sender', '')}:{message.get('text', '')}"
        return "hash:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _remember(self, key: str) -> None:
        if key in self._seen:
            return
        self._seen.add(key)
        self._seen_order.append(key)
        while len(self._seen_order) > self.dedupe_size:
            stale = self._seen_order.popleft()
            self._seen.discard(stale)

    def forward(self, message: dict[str, str]) -> tuple[int, str]:
        dedupe_key = self._dedupe_key(message)
        if dedupe_key in self._seen:
            return 200, '{"ok": true, "ignored": "duplicate"}'

        payload = {
            "text": message.get("text", ""),
            "sender": message.get("sender", ""),
            "chat_id": message.get("chat_id", ""),
            "message_id": message.get("message_id", ""),
            "use_ai": self.use_ai,
            "force": self.force,
        }
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["x-listener-token"] = self.token

        response = requests.post(
            self.target_url, json=payload, headers=headers, timeout=self.timeout
        )
        if response.ok:
            self._remember(dedupe_key)
        return response.status_code, response.text[:400]


class GatewayHandler(BaseHTTPRequestHandler):
    bridge: GatewayBridge
    route: str
    listen_mode: str
    gateway_token: str

    def _write_json(self, payload: dict[str, Any], status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._write_json(
                {"ok": True, "service": "wechat_gateway_bridge", "route": self.route}
            )
            return
        self._write_json({"error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        if self.path != self.route:
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

        if not isinstance(payload, dict):
            self._write_json({"error": "invalid payload"}, status=400)
            return

        if self.gateway_token:
            body_token = str(payload.get("token") or "")
            header_token = str(self.headers.get("x-gateway-token") or "")
            if self.gateway_token not in {body_token, header_token}:
                self._write_json({"error": "unauthorized"}, status=401)
                return

        message = normalize_message(payload)
        if not message:
            self._write_json({"ok": True, "ignored": "no-text"})
            return

        if not should_forward(message, self.listen_mode):
            self._write_json(
                {
                    "ok": True,
                    "ignored": "listen-mode",
                    "chat_id": message.get("chat_id", ""),
                }
            )
            return

        try:
            status, body = self.bridge.forward(message)
            self._write_json(
                {"ok": status < 400, "upstream_status": status, "upstream": body}
            )
        except Exception as exc:
            self._write_json({"ok": False, "error": str(exc)}, status=502)


def run_server(
    host: str,
    port: int,
    route: str,
    target_url: str,
    token: str,
    timeout: int,
    listen_mode: str,
    use_ai: bool,
    force: bool,
    gateway_token: str,
    dedupe_size: int,
):
    handler = type("GatewayBridgeHandler", (GatewayHandler,), {})
    handler.bridge = GatewayBridge(
        target_url=target_url,
        token=token,
        timeout=timeout,
        use_ai=use_ai,
        force=force,
        dedupe_size=dedupe_size,
    )
    handler.route = route
    handler.listen_mode = listen_mode
    handler.gateway_token = gateway_token
    server = ThreadingHTTPServer((host, port), handler)
    print(f"[gateway-bridge] listening http://{host}:{port}{route}")
    print(f"[gateway-bridge] target {target_url}")
    print(f"[gateway-bridge] mode {listen_mode}")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(
        description="Forward WeChat gateway callbacks to /event"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--route", default="/wechat/callback")
    parser.add_argument("--target-url", default="http://127.0.0.1:8877/event")
    parser.add_argument(
        "--listener-token", default=os.environ.get("LISTENER_TOKEN", "")
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--listen-mode", choices=["filehelper", "all"], default="filehelper"
    )
    parser.add_argument("--use-ai", dest="use_ai", action="store_true")
    parser.add_argument("--no-use-ai", dest="use_ai", action="store_false")
    parser.set_defaults(use_ai=False)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--gateway-token", default=os.environ.get("GATEWAY_TOKEN", ""))
    parser.add_argument("--dedupe-size", type=int, default=5000)
    args = parser.parse_args()
    run_server(
        host=args.host,
        port=args.port,
        route=args.route,
        target_url=args.target_url,
        token=args.listener_token,
        timeout=args.timeout,
        listen_mode=args.listen_mode,
        use_ai=args.use_ai,
        force=args.force,
        gateway_token=args.gateway_token,
        dedupe_size=args.dedupe_size,
    )


if __name__ == "__main__":
    main()

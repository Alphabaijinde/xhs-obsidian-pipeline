#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import argparse
import collections
import html
import json
import os
from pathlib import Path
import time
from typing import Any

import requests

try:
    import itchat
    from itchat.content import TEXT
except Exception:
    itchat = None
    TEXT = None


def extract_text(message: dict[str, Any]) -> str:
    text_field = message.get("Text")
    if callable(text_field):
        try:
            text_field = text_field()
        except TypeError:
            text_field = ""

    if isinstance(text_field, str) and text_field.strip():
        return html.unescape(text_field.replace("<br/>", "\n")).strip()

    for key in ("Content", "text", "content", "msg", "message"):
        value = message.get(key)
        if value is None:
            continue
        text = html.unescape(str(value).replace("<br/>", "\n")).strip()
        if text:
            return text

    return ""


def _nickname(message: dict[str, Any]) -> str:
    user = message.get("User")
    if isinstance(user, dict):
        for key in ("RemarkName", "NickName", "UserName"):
            value = str(user.get(key) or "").strip()
            if value:
                return value

    for key in ("ActualNickName", "FromUserName", "ToUserName"):
        value = str(message.get(key) or "").strip()
        if value:
            return value

    return "unknown"


def _chat_id(message: dict[str, Any]) -> str:
    from_user = str(message.get("FromUserName") or "").strip()
    to_user = str(message.get("ToUserName") or "").strip()
    nickname = _nickname(message)

    if (
        from_user == "filehelper"
        or to_user == "filehelper"
        or nickname == "文件传输助手"
    ):
        return "filehelper"

    if from_user:
        return from_user
    if to_user:
        return to_user
    return "unknown"


def should_forward_message(message: dict[str, Any], listen_mode: str) -> bool:
    if not extract_text(message):
        return False
    if listen_mode == "all":
        return True
    return _chat_id(message) == "filehelper"


def build_event_payload(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": extract_text(message),
        "sender": _nickname(message),
        "chat_id": _chat_id(message),
        "message_id": str(message.get("MsgId") or message.get("NewMsgId") or ""),
    }


class Forwarder:
    def __init__(
        self,
        event_url: str,
        token: str,
        timeout: int,
        dry_run: bool,
        max_retries: int,
        seen_cache_size: int,
    ):
        self.event_url = event_url
        self.token = token
        self.timeout = timeout
        self.dry_run = dry_run
        self.max_retries = max(0, max_retries)
        self.seen_cache_size = max(100, seen_cache_size)
        self._seen_ids: set[str] = set()
        self._seen_order: collections.deque[str] = collections.deque()

    def _remember_id(self, message_id: str) -> None:
        if not message_id or message_id in self._seen_ids:
            return
        self._seen_ids.add(message_id)
        self._seen_order.append(message_id)
        while len(self._seen_order) > self.seen_cache_size:
            stale_id = self._seen_order.popleft()
            self._seen_ids.discard(stale_id)

    def forward(self, message: dict[str, Any]) -> None:
        payload = build_event_payload(message)
        message_id = payload.get("message_id", "")
        if message_id and message_id in self._seen_ids:
            return

        if self.dry_run:
            print(
                f"[wechat-uos] dry-run payload: {json.dumps(payload, ensure_ascii=False)}"
            )
            self._remember_id(message_id)
            return

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["x-listener-token"] = self.token

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self.event_url, json=payload, headers=headers, timeout=self.timeout
                )
                print(f"[wechat-uos] -> {response.status_code} {response.text[:240]}")
                if response.ok:
                    self._remember_id(message_id)
                    return
            except requests.RequestException as exc:
                print(f"[wechat-uos] request error: {exc}")

            if attempt >= self.max_retries:
                print("[wechat-uos] give up forwarding after retries")
                return

            backoff_seconds = 0.5 * (2**attempt)
            time.sleep(backoff_seconds)


def run_bridge(args: argparse.Namespace) -> int:
    if itchat is None or TEXT is None:
        print("[wechat-uos] missing dependency: itchat-uos")
        print("install: source .venv/bin/activate && pip install itchat-uos")
        return 2

    forwarder = Forwarder(
        event_url=args.event_url,
        token=args.listener_token,
        timeout=args.timeout,
        dry_run=args.dry_run,
        max_retries=args.max_retries,
        seen_cache_size=args.seen_cache_size,
    )

    @itchat.msg_register(TEXT, isFriendChat=True, isGroupChat=True, isMpChat=True)
    def _on_text_message(message: dict[str, Any]):
        if not should_forward_message(message, listen_mode=args.listen_mode):
            return
        try:
            forwarder.forward(message)
        except Exception as exc:
            print(f"[wechat-uos] forward failed: {exc}")

    status_file = Path(args.status_file)
    status_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"[wechat-uos] listen_mode={args.listen_mode} -> {args.event_url}")
    print(f"[wechat-uos] status_file={status_file}")

    attempt = 0
    while True:
        attempt += 1
        try:
            itchat.auto_login(
                enableCmdQR=args.cmd_qr,
                hotReload=not args.no_hot_reload,
                statusStorageDir=str(status_file),
            )
            itchat.run(blockThread=True)
            return 0
        except KeyboardInterrupt:
            print("[wechat-uos] stopped by user")
            return 130
        except Exception as exc:
            print(f"[wechat-uos] login loop failed: {exc}")
            if args.max_login_retries >= 0 and attempt > args.max_login_retries:
                print("[wechat-uos] reached max login retries, exiting")
                return 1
            backoff_seconds = min(30.0, float(2 ** min(attempt, 5)))
            time.sleep(backoff_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Forward WeChat UOS text messages to /event"
    )
    parser.add_argument("--event-url", default="http://127.0.0.1:8877/event")
    parser.add_argument(
        "--listen-mode", choices=["filehelper", "all"], default="filehelper"
    )
    parser.add_argument(
        "--listener-token", default=os.environ.get("LISTENER_TOKEN", "")
    )
    parser.add_argument("--status-file", default="data/itchat_uos.pkl")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--seen-cache-size", type=int, default=5000)
    parser.add_argument("--max-login-retries", type=int, default=-1)
    parser.add_argument("--cmd-qr", action="store_true")
    parser.add_argument("--no-hot-reload", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return run_bridge(args)


if __name__ == "__main__":
    raise SystemExit(main())

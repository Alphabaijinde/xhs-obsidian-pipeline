#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import argparse
import collections
import functools
import hashlib
import os
import re
import subprocess
import sys
import time
from typing import Iterable

import requests

print = functools.partial(print, flush=True)

HEADER_PATTERN = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s+\[(.+?)\]\s*$")
MESSAGE_PATTERN = re.compile(r"^\s*\[(.+?)\]\s*(.*)$")


def parse_chat_header(line: str) -> str | None:
    m = HEADER_PATTERN.match(line.strip())
    if not m:
        return None
    return m.group(2).strip()


def parse_message_content(line: str) -> str | None:
    stripped = line.rstrip("\n")
    m = MESSAGE_PATTERN.match(stripped)
    if m:
        content = m.group(2).strip()
        return content or None
    return None


def is_filehelper_chat(chat_name: str) -> bool:
    lowered = chat_name.lower()
    return "文件传输助手" in chat_name or "filehelper" in lowered


class EventForwarder:
    def __init__(
        self,
        event_url: str,
        token: str,
        timeout: int,
        max_retries: int,
        dedupe_size: int,
    ):
        self.event_url = event_url
        self.token = token
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.dedupe_size = max(100, dedupe_size)
        self._seen: set[str] = set()
        self._seen_order: collections.deque[str] = collections.deque()

    def _remember(self, key: str) -> None:
        if key in self._seen:
            return
        self._seen.add(key)
        self._seen_order.append(key)
        while len(self._seen_order) > self.dedupe_size:
            stale = self._seen_order.popleft()
            self._seen.discard(stale)

    def _dedupe_key(self, chat_id: str, text: str) -> str:
        digest = hashlib.sha1(f"{chat_id}:{text}".encode("utf-8")).hexdigest()
        return digest

    def forward(self, *, text: str, sender: str, chat_id: str, source: str) -> None:
        clean = str(text or "").strip()
        if not clean:
            return

        dedupe_key = self._dedupe_key(chat_id, clean)
        if dedupe_key in self._seen:
            return

        payload = {
            "text": clean,
            "sender": sender,
            "chat_id": chat_id,
            "source": source,
            "force": True,
        }
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["x-listener-token"] = self.token

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self.event_url, json=payload, headers=headers, timeout=self.timeout
                )
                print(f"[wechat-db] -> {response.status_code} {response.text[:240]}")
                if response.ok:
                    self._remember(dedupe_key)
                    return
            except requests.RequestException as exc:
                print(f"[wechat-db] request error: {exc}")

            if attempt >= self.max_retries:
                print("[wechat-db] give up forwarding after retries")
                return

            time.sleep(0.5 * (2**attempt))


def iter_lines(process: subprocess.Popen[str]) -> Iterable[str]:
    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if line:
            yield line
            continue
        if process.poll() is not None:
            break
        time.sleep(0.1)


def run_bridge(args: argparse.Namespace) -> int:
    monitor_script = os.path.abspath(args.monitor_script)
    if not os.path.exists(monitor_script):
        print(f"[wechat-db] monitor script not found: {monitor_script}")
        return 2

    cwd = os.path.abspath(args.tool_cwd or os.path.dirname(monitor_script))
    cmd = [args.python_bin, monitor_script]
    print(f"[wechat-db] launch monitor: {' '.join(cmd)}")
    print(f"[wechat-db] monitor cwd: {cwd}")

    forwarder = EventForwarder(
        event_url=args.event_url,
        token=args.listener_token,
        timeout=args.timeout,
        max_retries=args.max_retries,
        dedupe_size=args.dedupe_size,
    )

    restarts = 0
    while True:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        current_chat = ""
        try:
            for raw_line in iter_lines(process):
                line = raw_line.rstrip("\n")
                print(f"[wechat-db-monitor] {line}")

                chat_name = parse_chat_header(line)
                if chat_name:
                    current_chat = chat_name
                    continue

                if not current_chat or not is_filehelper_chat(current_chat):
                    continue

                message = parse_message_content(line)
                if not message:
                    continue

                forwarder.forward(
                    text=message,
                    sender=current_chat,
                    chat_id="filehelper",
                    source="wechat_db",
                )
        except KeyboardInterrupt:
            print("[wechat-db] stopped by user")
            if process.poll() is None:
                process.terminate()
            return 130
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()

        code = process.returncode if process.returncode is not None else 1
        if code == 0:
            return 0

        restarts += 1
        if args.max_restarts >= 0 and restarts > args.max_restarts:
            print("[wechat-db] reached max restarts, exiting")
            return code

        print(
            f"[wechat-db] monitor exited with code {code}, retry in {args.restart_delay}s"
        )
        time.sleep(max(1, args.restart_delay))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bridge wechat-decrypt-mac monitor output to /event"
    )
    parser.add_argument(
        "--monitor-script", default="/tmp/wechat-decrypt-mac/monitor.py"
    )
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--tool-cwd", default="")
    parser.add_argument("--event-url", default="http://127.0.0.1:8877/event")
    parser.add_argument(
        "--listener-token", default=os.environ.get("LISTENER_TOKEN", "")
    )
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--dedupe-size", type=int, default=5000)
    parser.add_argument("--restart-delay", type=int, default=5)
    parser.add_argument("--max-restarts", type=int, default=-1)
    args = parser.parse_args()
    return run_bridge(args)


if __name__ == "__main__":
    raise SystemExit(main())

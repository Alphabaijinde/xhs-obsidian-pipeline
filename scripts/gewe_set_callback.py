#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urljoin

import requests


def normalize_base_api(base_api: str) -> str:
    value = str(base_api or "").strip().rstrip("/")
    if not value:
        return "http://api.geweapi.com/gewe/v2/api"
    if value.endswith("/gewe/v2/api"):
        return value
    if value.endswith("/gewe"):
        return f"{value}/v2/api"
    return f"{value}/gewe/v2/api"


def build_request_parts(base_api: str, token: str, callback_url: str):
    api = normalize_base_api(base_api)
    endpoint = urljoin(f"{api}/", "login/setCallback")
    headers = {
        "Content-Type": "application/json",
        "X-GEWE-TOKEN": token,
    }
    payload = {
        "token": token,
        "callbackUrl": callback_url,
    }
    return endpoint, headers, payload


def set_callback(base_api: str, token: str, callback_url: str, timeout: int):
    endpoint, headers, payload = build_request_parts(base_api, token, callback_url)
    response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
    body = response.text
    try:
        parsed = response.json()
    except Exception:
        parsed = {"raw": body}
    return response.status_code, parsed


def main():
    parser = argparse.ArgumentParser(description="Set GeWe callback URL")
    parser.add_argument(
        "--base-api",
        default=os.environ.get("GEWE_BASE_API", "http://api.geweapi.com/gewe/v2/api"),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GEWE_TOKEN", ""),
    )
    parser.add_argument(
        "--callback-url",
        default=os.environ.get(
            "GEWE_CALLBACK_URL", "http://127.0.0.1:8899/wechat/callback"
        ),
    )
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    if not args.token.strip():
        print("[gewe-set-callback] missing token; use --token or GEWE_TOKEN")
        raise SystemExit(2)

    status, payload = set_callback(
        base_api=args.base_api,
        token=args.token.strip(),
        callback_url=args.callback_url.strip(),
        timeout=args.timeout,
    )
    print(json.dumps({"status": status, "response": payload}, ensure_ascii=False))
    if status >= 400:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

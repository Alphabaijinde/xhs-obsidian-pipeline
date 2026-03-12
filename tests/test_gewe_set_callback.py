#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from gewe_set_callback import build_request_parts, normalize_base_api  # noqa: E402


class GeweSetCallbackTest(unittest.TestCase):
    def test_normalize_base_api_appends_path(self):
        self.assertEqual(
            normalize_base_api("http://api.geweapi.com"),
            "http://api.geweapi.com/gewe/v2/api",
        )

    def test_normalize_base_api_keeps_existing_api_path(self):
        self.assertEqual(
            normalize_base_api("http://api.geweapi.com/gewe/v2/api"),
            "http://api.geweapi.com/gewe/v2/api",
        )

    def test_build_request_parts(self):
        url, headers, payload = build_request_parts(
            base_api="http://api.geweapi.com/gewe/v2/api",
            token="abc123",
            callback_url="http://127.0.0.1:8899/wechat/callback",
        )
        self.assertEqual(url, "http://api.geweapi.com/gewe/v2/api/login/setCallback")
        self.assertEqual(headers["X-GEWE-TOKEN"], "abc123")
        self.assertEqual(payload["token"], "abc123")
        self.assertEqual(
            payload["callbackUrl"], "http://127.0.0.1:8899/wechat/callback"
        )


if __name__ == "__main__":
    unittest.main()

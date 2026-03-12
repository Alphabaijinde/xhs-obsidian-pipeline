#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_uos_bridge import build_event_payload, extract_text, should_forward_message  # noqa: E402


class WechatUosBridgeTest(unittest.TestCase):
    def test_extract_text_from_plain_string(self):
        self.assertEqual(extract_text({"Text": " hi "}), "hi")

    def test_extract_text_from_callable(self):
        message = {"Text": lambda: "link https://example.com"}
        self.assertEqual(extract_text(message), "link https://example.com")

    def test_extract_text_falls_back_to_content(self):
        self.assertEqual(extract_text({"Content": "hello"}), "hello")

    def test_should_forward_only_filehelper_when_mode_filehelper(self):
        filehelper_message = {"FromUserName": "filehelper", "Text": "hello"}
        normal_message = {"FromUserName": "@friend", "Text": "hello"}

        self.assertTrue(
            should_forward_message(filehelper_message, listen_mode="filehelper")
        )
        self.assertFalse(
            should_forward_message(normal_message, listen_mode="filehelper")
        )

    def test_should_forward_every_text_message_when_mode_all(self):
        normal_message = {"FromUserName": "@friend", "Text": "hello"}
        self.assertTrue(should_forward_message(normal_message, listen_mode="all"))

    def test_build_event_payload_uses_expected_fields(self):
        message = {
            "FromUserName": "filehelper",
            "ToUserName": "wxid_me",
            "User": {"NickName": "文件传输助手"},
            "Text": "save https://example.com",
            "CreateTime": 123,
            "MsgId": "abc-1",
        }

        payload = build_event_payload(message)

        self.assertEqual(payload["text"], "save https://example.com")
        self.assertEqual(payload["sender"], "文件传输助手")
        self.assertEqual(payload["chat_id"], "filehelper")
        self.assertEqual(payload["message_id"], "abc-1")


if __name__ == "__main__":
    unittest.main()

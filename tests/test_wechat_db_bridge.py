#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_db_bridge import (
    is_filehelper_chat,
    parse_chat_header,
    parse_message_content,
)  # noqa: E402


class WechatDbBridgeTest(unittest.TestCase):
    def test_parse_chat_header(self):
        self.assertEqual(parse_chat_header("[12:34:56] [文件传输助手]"), "文件传输助手")

    def test_parse_chat_header_non_header(self):
        self.assertIsNone(parse_chat_header("开始监听..."))

    def test_parse_message_content(self):
        self.assertEqual(
            parse_message_content("  [文本] save this https://example.com"),
            "save this https://example.com",
        )

    def test_parse_message_content_empty(self):
        self.assertIsNone(parse_message_content("  [文本]   "))

    def test_is_filehelper_chat(self):
        self.assertTrue(is_filehelper_chat("文件传输助手"))
        self.assertTrue(is_filehelper_chat("filehelper"))
        self.assertFalse(is_filehelper_chat("技术群"))


if __name__ == "__main__":
    unittest.main()

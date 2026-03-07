#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from chat_bridge import ingest_text_message  # noqa: E402


class ChatBridgeTest(unittest.TestCase):
    def test_ingest_without_url(self):
        result = ingest_text_message("今天先不存", use_ai=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 0)
        self.assertIn("未检测到 URL", result["message"])

    @patch("chat_bridge.save_content")
    @patch("chat_bridge.read_url")
    def test_ingest_with_url(self, mock_read_url, mock_save_content):
        mock_read_url.return_value = {
            "success": True,
            "platform": {"name": "通用网站"},
            "metadata": {
                "title": "测试标题",
                "author": "作者",
                "images": [],
                "likes": "",
                "collects": "",
                "comments": "",
                "tags": ["原标签"],
                "hashtags": [],
                "hotComments": [],
                "contentText": "正文",
            },
            "content": "正文",
        }
        mock_save_content.return_value = {
            "success": True,
            "title": "测试标题",
            "dir": "/tmp/x",
            "md_file": "/tmp/x/x.md",
            "images": 0,
        }

        result = ingest_text_message("帮我存这个 https://example.com", use_ai=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)
        self.assertEqual(len(result["saved"]), 1)
        mock_read_url.assert_called_once()
        mock_save_content.assert_called_once()


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_gateway_bridge import GatewayBridge, normalize_message, should_forward  # noqa: E402


class WechatGatewayBridgeTest(unittest.TestCase):
    def test_normalize_wechat_raw_filehelper(self):
        payload = {
            "TypeName": "AddMsg",
            "Data": {
                "FromUserName": {"string": "filehelper"},
                "ToUserName": {"string": "wxid_me"},
                "Content": {"string": "save https://example.com"},
                "MsgId": "m1",
            },
        }
        message = normalize_message(payload)
        self.assertIsNotNone(message)
        self.assertEqual(message["chat_id"], "filehelper")
        self.assertEqual(message["sender"], "filehelper")
        self.assertEqual(message["text"], "save https://example.com")

    def test_normalize_wechat_group_payload(self):
        payload = {
            "TypeName": "AddMsg",
            "Data": {
                "FromUserName": {"string": "123@chatroom"},
                "ToUserName": {"string": "wxid_me"},
                "Content": {"string": "wxid_user:\nhello group"},
            },
        }
        message = normalize_message(payload)
        self.assertIsNotNone(message)
        self.assertEqual(message["chat_id"], "123@chatroom")
        self.assertEqual(message["sender"], "wxid_user")
        self.assertEqual(message["text"], "hello group")

    def test_normalize_generic_payload(self):
        payload = {"text": "hello", "sender": "alice", "chat_id": "room-1"}
        message = normalize_message(payload)
        self.assertEqual(
            message,
            {"text": "hello", "sender": "alice", "chat_id": "room-1", "message_id": ""},
        )

    def test_should_forward_filehelper_mode(self):
        self.assertTrue(should_forward({"chat_id": "filehelper"}, "filehelper"))
        self.assertFalse(should_forward({"chat_id": "room-1"}, "filehelper"))
        self.assertTrue(should_forward({"chat_id": "room-1"}, "all"))

    @patch("wechat_gateway_bridge.requests.post")
    def test_forward_deduplicates_same_message(self, mock_post: Mock):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.text = '{"ok": true}'
        mock_post.return_value = response

        bridge = GatewayBridge(
            target_url="http://127.0.0.1:8877/event",
            token="",
            timeout=10,
            use_ai=False,
            force=False,
            dedupe_size=100,
        )
        msg = {
            "text": "hello",
            "sender": "filehelper",
            "chat_id": "filehelper",
            "message_id": "dup-1",
        }

        first = bridge.forward(msg)
        second = bridge.forward(msg)

        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()

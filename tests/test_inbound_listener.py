#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from inbound_listener import _pick  # noqa: E402


class InboundListenerTest(unittest.TestCase):
    def test_pick_prefers_first_non_empty(self):
        payload = {"text": "", "content": " hi ", "msg": "later"}
        self.assertEqual(_pick(payload, ["text", "content", "msg"]), "hi")

    def test_pick_returns_default(self):
        payload = {"x": 1}
        self.assertEqual(_pick(payload, ["text", "content"], default="none"), "none")


if __name__ == "__main__":
    unittest.main()

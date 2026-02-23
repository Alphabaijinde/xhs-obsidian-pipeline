#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
import sys
import unittest
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from url_reader import (  # noqa: E402
    build_provenance_fingerprint,
    get_license_mode,
    infer_note_domain,
    normalize_content_text,
)


class FormatRulesTest(unittest.TestCase):
    def test_normalize_content_text_removes_pure_hashtag_line(self):
        raw = "第一行正文\n#银行人的日常# #银行工作# #投资#\n第二行正文"
        cleaned = normalize_content_text(raw)
        self.assertIn("第一行正文", cleaned)
        self.assertIn("第二行正文", cleaned)
        self.assertNotIn("#银行人的日常#", cleaned)

    def test_normalize_content_text_removes_separator_noise(self):
        raw = "正文A\n---\n正文B\n***\n正文C"
        cleaned = normalize_content_text(raw)
        self.assertNotIn("---", cleaned)
        self.assertNotIn("***", cleaned)
        self.assertIn("正文A", cleaned)
        self.assertIn("正文B", cleaned)
        self.assertIn("正文C", cleaned)

    def test_domain_osint_not_misclassified_as_social(self):
        title = "World Monitor：开源情报实时大屏"
        content = "支持社交媒体导出，包含OSINT多源聚合和地图图层。"
        tags = ["人工智能", "OSINT"]
        self.assertEqual(infer_note_domain(title, content, tags), "osint_product")

    def test_domain_ai_ops_not_misclassified_as_social(self):
        title = "OpenClaw 7技能管理250万粉丝"
        content = "管理多个社交媒体账号，依赖skills编排与自动化运营。"
        tags = ["AI工具", "产品经理"]
        self.assertEqual(infer_note_domain(title, content, tags), "ai_ops")

    def test_provenance_fingerprint_is_stable(self):
        fp1 = build_provenance_fingerprint(
            url="https://www.xiaohongshu.com/explore/abc123",
            title="标题A",
            note_id="abc123",
            author_id="u001",
            date_saved="2026-02-21",
        )
        fp2 = build_provenance_fingerprint(
            url="https://www.xiaohongshu.com/explore/abc123",
            title="标题A",
            note_id="abc123",
            author_id="u001",
            date_saved="2026-02-21",
        )
        self.assertEqual(fp1, fp2)
        self.assertTrue(fp1.startswith("xop-"))

    def test_license_mode_env_switch(self):
        old = os.environ.get("URL_READER_LICENSE_MODE")
        try:
            os.environ["URL_READER_LICENSE_MODE"] = "commercial"
            self.assertEqual(get_license_mode(), "commercial")
            os.environ["URL_READER_LICENSE_MODE"] = "foo"
            self.assertEqual(get_license_mode(), "AGPL-3.0-or-later")
        finally:
            if old is None:
                os.environ.pop("URL_READER_LICENSE_MODE", None)
            else:
                os.environ["URL_READER_LICENSE_MODE"] = old


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""测试小红书抓取"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from url_reader import read_url, format_output

# 测试小红书URL（使用一个公开的小红书笔记）
test_url = "https://www.xiaohongshu.com/explore/673e0eb3000000001e0315ab"

print("=" * 60)
print("测试小红书抓取")
print("=" * 60)
print(f"\n测试URL: {test_url}\n")

# 执行抓取
result = read_url(test_url, verbose=True)

print("\n" + "=" * 60)
print("结果")
print("=" * 60)

if result.get("success"):
    print("✅ 抓取成功！\n")
    print("策略:", result.get("strategy"))
    print("平台:", result.get("platform", {}).get("name"))
    
    metadata = result.get("metadata", {})
    print("\n元数据:")
    print(f"  标题: {metadata.get('title', 'N/A')}")
    print(f"  作者: {metadata.get('author', 'N/A')}")
    print(f"  图片数: {len(metadata.get('images', []))}")
    
    content = result.get("content", "")
    print(f"\n内容长度: {len(content)} 字符")
    print(f"\n前300字符:\n{content[:300]}")
else:
    print("❌ 抓取失败\n")
    print("错误:", result.get("errors", []))

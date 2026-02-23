#!/usr/bin/env python3
"""调试小红书内容提取选择器"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parents[2]

test_url = "https://www.xiaohongshu.com/explore/673e0eb3000000001e0315ab"
auth_file = ROOT_DIR / "data" / "xiaohongshu_auth.json"

async def debug_selectors():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        
        context_config = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        
        if auth_file.exists():
            context_config["storage_state"] = str(auth_file)
        
        context = await browser.new_context(**context_config)
        page = await context.new_page()
        
        print("正在加载页面...")
        await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        
        # 测试各种选择器
        selectors = [
            '#detail-desc',
            '.note-content',
            '.desc-content',
            '.content span',
            '.note-text',
            '[class*="note"][class*="content"]',
            '[class*="desc"]',
            'h1',
            '[class*="title"]'
        ]
        
        print("\n选择器测试:")
        print("=" * 60)
        
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = await el.inner_text()
                    print(f"✅ {sel:40s} -> {len(text):4d} 字符")
                    if len(text) < 200:
                        print(f"   内容: {text[:100]}")
                else:
                    print(f"❌ {sel:40s} -> 未找到")
            except Exception as e:
                print(f"⚠️  {sel:40s} -> 错误: {e}")
        
        # 获取页面HTML查看结构
        print("\n\n保存HTML到本地...")
        html = await page.content()
        with open("/tmp/xhs_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("已保存到: /tmp/xhs_debug.html")
        
        await browser.close()

asyncio.run(debug_selectors())

#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
URL Reader - 智能网页内容读取器
策略：Firecrawl（首选）→ Jina（备选）→ Playwright（兜底）
自动保存内容和图片到指定目录
"""

import os
import sys
import json
import asyncio
import csv
import requests
import re
import hashlib
import time
from urllib.parse import parse_qs, quote, urlparse, urlsplit, urlunsplit
from pathlib import Path
from datetime import datetime

# 配置
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
JINA_BASE_URL = "https://r.jina.ai/"
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
WECHAT_AUTH_FILE = DATA_DIR / "wechat_auth.json"
XIAOHONGSHU_AUTH_FILE = DATA_DIR / "xiaohongshu_auth.json"

# 默认保存目录 - 修改为 Obsidian 知识库路径
DEFAULT_OUTPUT_DIR = os.environ.get(
    "URL_READER_OUTPUT_DIR",
    "/Users/baijinde/Documents/obsidian_docs/mac_docs/🌐 网络收藏",
)

GENERATOR_NAME = "xhs-obsidian-pipeline"
GENERATOR_VERSION = "0.4.0"
GENERATOR_REPO = "https://github.com/Alphabaijinde/xhs-obsidian-pipeline"
PROVENANCE_SENTINEL = "XOP-Trace"


def get_license_mode() -> str:
    """
    生成笔记时附带许可模式标记，便于后续取证。
    可通过 URL_READER_LICENSE_MODE=commercial 切换。
    """
    raw = clean_inline_text(os.environ.get("URL_READER_LICENSE_MODE", ""))
    if raw.lower() in {"commercial", "commercial-license", "enterprise"}:
        return "commercial"
    return "AGPL-3.0-or-later"


def build_provenance_fingerprint(
    url: str,
    title: str,
    note_id: str = "",
    author_id: str = "",
    date_saved: str = "",
) -> str:
    """构建稳定可复算的内容指纹（用于归属取证）"""
    payload = "|".join(
        [
            clean_inline_text(url),
            clean_inline_text(title),
            clean_inline_text(note_id),
            clean_inline_text(author_id),
            clean_inline_text(date_saved),
            GENERATOR_NAME,
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"xop-{digest}"


def identify_platform(url: str) -> dict:
    """识别URL所属平台"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    platforms = {
        "wechat": {
            "name": "微信公众号",
            "domains": ["mp.weixin.qq.com"],
            "need_login": True,
        },
        "xiaohongshu": {
            "name": "小红书",
            "domains": ["xiaohongshu.com", "xhslink.com"],
            "need_login": False,
        },
        "toutiao": {
            "name": "今日头条",
            "domains": ["toutiao.com"],
            "need_login": False,
        },
        "douyin": {
            "name": "抖音",
            "domains": ["douyin.com", "v.douyin.com"],
            "need_login": False,
        },
        "taobao": {
            "name": "淘宝",
            "domains": ["taobao.com", "item.taobao.com"],
            "need_login": True,
        },
        "tmall": {
            "name": "天猫",
            "domains": ["tmall.com", "detail.tmall.com"],
            "need_login": True,
        },
        "jd": {
            "name": "京东",
            "domains": ["jd.com", "item.jd.com"],
            "need_login": False,
        },
        "zhihu": {
            "name": "知乎",
            "domains": ["zhihu.com", "zhuanlan.zhihu.com"],
            "need_login": False,
        },
        "weibo": {
            "name": "微博",
            "domains": ["weibo.com", "m.weibo.cn"],
            "need_login": True,
        },
        "bilibili": {
            "name": "B站",
            "domains": ["bilibili.com", "b23.tv"],
            "need_login": False,
        },
        "baidu": {
            "name": "百度",
            "domains": ["baidu.com", "baijiahao.baidu.com"],
            "need_login": False,
        },
    }

    for platform_id, info in platforms.items():
        for d in info["domains"]:
            if d in domain:
                return {"id": platform_id, **info}

    return {"id": "generic", "name": "通用网站", "domains": [], "need_login": False}


def read_with_firecrawl(url: str) -> dict:
    """策略A：使用 Firecrawl API 读取"""
    if not FIRECRAWL_API_KEY:
        return {"success": False, "error": "FIRECRAWL_API_KEY 未设置"}

    try:
        from firecrawl import Firecrawl

        app = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = app.scrape(url)

        if result:
            # Firecrawl v2 返回 Document 对象
            markdown = getattr(result, "markdown", "") or ""
            metadata = getattr(result, "metadata", None)
            if metadata:
                metadata = (
                    metadata.model_dump() if hasattr(metadata, "model_dump") else {}
                )
            else:
                metadata = {}

            if markdown and len(markdown) > 100:
                # 检查是否是验证页面
                if "环境异常" in markdown or "验证" in markdown[:200]:
                    return {"success": False, "error": "页面需要验证"}

                return {
                    "success": True,
                    "strategy": "Firecrawl",
                    "content": markdown,
                    "metadata": metadata,
                }

        return {"success": False, "error": "Firecrawl 返回内容为空"}

    except Exception as e:
        return {"success": False, "error": f"Firecrawl 错误: {str(e)}"}


def read_with_jina(url: str) -> dict:
    """策略B-1：使用 Jina Reader API 读取（免费）"""
    try:
        jina_url = f"{JINA_BASE_URL}{url}"
        headers = {
            "Accept": "text/markdown",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }

        response = requests.get(jina_url, headers=headers, timeout=30)

        if response.status_code == 200:
            content = response.text

            # 检查是否是有效内容
            if "环境异常" in content or "完成验证" in content:
                return {"success": False, "error": "页面需要验证"}
            if "你访问的页面不见了" in content or "web_error_page" in content:
                return {"success": False, "error": "页面不存在或被限制访问"}

            if len(content) < 100:
                return {"success": False, "error": "内容太短，可能读取失败"}

            return {
                "success": True,
                "strategy": "Jina Reader",
                "content": content,
                "metadata": {},
            }

        return {"success": False, "error": f"HTTP {response.status_code}"}

    except Exception as e:
        return {"success": False, "error": f"Jina 错误: {str(e)}"}


async def get_xiaohongshu_login_signals(page) -> dict:
    """读取页面登录态信号，避免仅凭 cookie 误判"""
    try:
        return await page.evaluate(
            """() => {
                const text = document.body?.innerText || '';
                const nodes = Array.from(document.querySelectorAll('button, a, span, div'));
                const isVisible = (el) => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const hasLoginBtn = nodes.some((el) => {
                    if (!isVisible(el)) return false;
                    const t = (el.innerText || '').trim();
                    return t === '登录' || t === '登录/注册' || t === '手机号登录';
                });
                const hasLoginPrompt = ['马上登录即可', '手机号登录', '获取验证码', '扫码登录', '登录后推荐更懂你的笔记']
                    .some((kw) => text.includes(kw));
                const hasUserProfileLink = document.querySelectorAll('a[href*="/user/profile/"]').length > 0;
                const hasAvatar = !!document.querySelector('img[src*="avatar"], [class*="avatar"]');
                const hasUserMenuText = ['退出登录', '我的收藏', '我的笔记', '个人主页']
                    .some((kw) => text.includes(kw));
                return {
                    hasLoginBtn,
                    hasLoginPrompt,
                    hasUserProfileLink,
                    hasAvatar,
                    hasUserMenuText
                };
            }"""
        )
    except Exception:
        return {
            "hasLoginBtn": False,
            "hasLoginPrompt": False,
            "hasUserProfileLink": False,
            "hasAvatar": False,
            "hasUserMenuText": False,
        }


def sanitize_xiaohongshu_handle(value: str) -> str:
    """规范化小红书号文本"""
    text = clean_inline_text(value)
    if not text:
        return ""
    text = re.sub(r"^小红书号[：:\s]*", "", text)
    text = re.sub(r"[^0-9A-Za-z_\-]", "", text)
    return text.strip()


def extract_xhs_uid_from_profile_url(url: str) -> str:
    """从 /user/profile/<uid> 链接提取 uid"""
    raw = str(url or "").strip()
    match = re.search(r"/user/profile/([0-9a-zA-Z]+)", raw)
    return match.group(1) if match else ""


async def fetch_xiaohongshu_profile_info(context, author_id: str) -> dict:
    """通过作者主页抓取小红书号（和兜底 author_id）"""
    author_id = clean_inline_text(author_id)
    if not author_id:
        return {}

    profile_page = await context.new_page()
    try:
        profile_url = f"https://www.xiaohongshu.com/user/profile/{author_id}"
        await profile_page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        await profile_page.wait_for_timeout(3500)
        result = await profile_page.evaluate(
            r"""() => {
                const body = document.body?.innerText || '';
                const title = document.title || '';
                const handleMatch = body.match(/小红书号[：:\s]*([A-Za-z0-9_\-]+)/);
                const handle = handleMatch ? handleMatch[1] : '';
                const currentUrl = location.href || '';
                return { title, handle, currentUrl };
            }"""
        )
        handle = sanitize_xiaohongshu_handle(result.get("handle", ""))
        uid_from_link = extract_xhs_uid_from_profile_url(result.get("currentUrl", ""))
        return {
            "xiaohongshuId": handle,
            "authorId": uid_from_link or author_id,
            "title": clean_inline_text(result.get("title", "")),
        }
    except Exception:
        return {}
    finally:
        await profile_page.close()


async def search_xiaohongshu_profile_info(context, author_name: str) -> dict:
    """通过站内搜索按昵称回填 author_id / 小红书号"""
    keyword = clean_inline_text(author_name)
    if not keyword:
        return {}

    search_page = await context.new_page()
    try:
        search_url = (
            "https://www.xiaohongshu.com/search_result?keyword="
            + quote(keyword)
            + "&type=51"
        )
        await search_page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        await search_page.wait_for_timeout(4500)
        data = await search_page.evaluate(
            r"""(keyword) => {
                const compact = (v) => String(v || '').replace(/\s+/g, ' ').trim();
                const cards = Array.from(document.querySelectorAll('a[href*="/user/profile/"]'))
                    .map((a) => ({
                        href: a.href || '',
                        text: compact(a.innerText || '')
                    }))
                    .filter((item) => item.href && item.text);

                const extractHandle = (text) => {
                    const m = text.match(/小红书号[：:\s]*([A-Za-z0-9_\-]+)/);
                    return m ? m[1] : '';
                };
                const extractName = (text) => compact(text.split('\n')[0] || '');
                const extractUid = (href) => {
                    const m = href.match(/\/user\/profile\/([0-9a-zA-Z]+)/);
                    return m ? m[1] : '';
                };

                const normalizedKeyword = compact(keyword).toLowerCase();
                let best = null;
                for (const card of cards) {
                    const name = extractName(card.text);
                    const normName = name.toLowerCase();
                    const score =
                        normName === normalizedKeyword
                            ? 100
                            : normName.includes(normalizedKeyword)
                            ? 60
                            : card.text.toLowerCase().includes(normalizedKeyword)
                            ? 40
                            : 0;
                    if (score <= 0) continue;
                    const candidate = {
                        score,
                        name,
                        uid: extractUid(card.href),
                        xhsId: extractHandle(card.text),
                        href: card.href
                    };
                    if (!best || candidate.score > best.score) {
                        best = candidate;
                    }
                }
                return best || {};
            }""",
            keyword,
        )
        return {
            "authorId": clean_inline_text(data.get("uid", "")),
            "xiaohongshuId": sanitize_xiaohongshu_handle(data.get("xhsId", "")),
            "authorName": clean_inline_text(data.get("name", "")),
        }
    except Exception:
        return {}
    finally:
        await search_page.close()


async def check_xiaohongshu_login(p, auth_file: str) -> bool:
    """检测小红书登录态是否有效（真实页面校验，避免 cookie 误判）"""
    try:
        with open(auth_file, "r", encoding="utf-8") as f:
            storage_state = json.load(f)

        cookies = storage_state.get("cookies", [])
        xhs_cookies = [c for c in cookies if "xiaohongshu" in c.get("domain", "")]
        if not xhs_cookies:
            return False

        now_ts = int(time.time())
        # 小红书常见会话/身份 cookie 名
        auth_cookie_names = {"a1", "web_session", "webId", "xsecappid", "gid", "acw_tc"}

        has_auth_cookie = any(
            cookie.get("name", "") in auth_cookie_names
            or any(
                token in cookie.get("name", "").lower()
                for token in ["session", "token", "auth", "login"]
            )
            for cookie in xhs_cookies
        )
        if not has_auth_cookie:
            return False

        # 至少有一个未过期或会话型 cookie
        has_valid_cookie = any(
            cookie.get("expires", -1) in (-1, 0)
            or int(cookie.get("expires", -1)) > now_ts + 60
            for cookie in xhs_cookies
        )
        if not has_valid_cookie:
            return False

        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=auth_file,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        try:
            await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)
            signals = await get_xiaohongshu_login_signals(page)
            if signals.get("hasLoginBtn") or signals.get("hasLoginPrompt"):
                return False

            return bool(
                signals.get("hasUserProfileLink")
                or signals.get("hasAvatar")
                or signals.get("hasUserMenuText")
            )
        finally:
            await browser.close()
    except Exception:
        return False


async def interactive_xiaohongshu_login(p, url: str) -> tuple:
    """交互式小红书登录：点击登录按钮 → 等待扫码 → 抓取内容"""

    print("\n" + "=" * 60)
    print("小红书登录")
    print("=" * 60)

    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context(viewport={"width": 1920, "height": 1080})
    page = await context.new_page()

    print("⏳ 正在打开小红书...")
    await page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded")
    await asyncio.sleep(2)
    print("✅ 页面已加载\n")

    signals = await get_xiaohongshu_login_signals(page)
    has_login_btn = bool(signals.get("hasLoginBtn") or signals.get("hasLoginPrompt"))

    if has_login_btn:
        print("📱 检测到未登录状态，准备登录...")
        print("\n📋 操作步骤：")
        print("   1. 浏览器会自动点击登录按钮")
        print("   2. 使用手机小红书 App 扫描二维码")
        print("   3. 扫码成功后，系统自动继续\n")

        # 点击登录按钮
        login_clicked = await page.evaluate("""() => {
            const loginTexts = ['登录', '登录/注册', 'Login'];
            for (const text of loginTexts) {
                const btn = Array.from(document.querySelectorAll('button, a, span, div'))
                    .find(el => el.innerText?.trim() === text);
                if (btn) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""")

        if login_clicked:
            print("✅ 已点击登录按钮，请扫码...")
            await asyncio.sleep(2)  # 等待二维码显示
        else:
            print("⚠️  未找到登录按钮，请手动点击登录")

    # 等待登录成功
    print("\n🔍 等待扫码登录...")
    logged_in = False
    for i in range(1800):  # 30分钟超时，避免来不及扫码
        await asyncio.sleep(1)

        try:
            # 登录成功标准：登录提示消失 + 用户态信号出现
            signals = await get_xiaohongshu_login_signals(page)
            logged_in = (
                not signals.get("hasLoginBtn")
                and not signals.get("hasLoginPrompt")
                and (
                    signals.get("hasAvatar")
                    or signals.get("hasUserProfileLink")
                    or signals.get("hasUserMenuText")
                )
            )

            if logged_in:
                print("✅ 登录成功！")
                break

            if i % 20 == 0 and i > 0:
                print(f"   等待扫码中... {i}秒")

        except:
            pass

    if not logged_in:
        print("\n⚠️  登录超时")
        await browser.close()
        return None, None

    # 保存登录态
    print("\n💾 保存登录态...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage = await context.storage_state()

    with open(XIAOHONGSHU_AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(storage, f)

    cookies = storage.get("cookies", [])
    print(f"✅ 已保存 {len(cookies)} 个 cookies")

    # 抓取笔记内容 - 直接在新标签页打开
    print(f"\n📄 正在抓取笔记...")

    # 使用新页面来避免重定向问题
    note_page = await context.new_page()
    try:
        await note_page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            await note_page.wait_for_load_state("networkidle", timeout=15000)
        except:
            pass
        await asyncio.sleep(3)
    except Exception as e:
        print(f"⚠️ 页面加载警告: {e}")

    return note_page, browser


async def extract_xiaohongshu_content(page, browser, url: str) -> dict:
    """从小红书页面提取内容 - 优先使用 API 数据"""
    try:
        captured_comment_items = []

        async def capture_comment_response(response):
            """抓取页面自身发出的已签名评论接口响应"""
            try:
                resp_url = response.url or ""
                if "/api/sns/web/v2/comment/page" not in resp_url:
                    return
                payload = await response.json()
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                for key in ("top_comments", "comments", "comment_list"):
                    items = data.get(key) or []
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        content_text = (
                            item.get("content")
                            or item.get("comment_content")
                            or item.get("text")
                            or ""
                        )
                        if not str(content_text).strip():
                            continue
                        user_info = item.get("user_info") or item.get("user") or {}
                        captured_comment_items.append(
                            {
                                "user": (
                                    user_info.get("nickname")
                                    or user_info.get("name")
                                    or user_info.get("userName")
                                    or "用户"
                                ),
                                "content": str(content_text).strip(),
                                "likes": str(
                                    item.get("like_count")
                                    or item.get("liked_count")
                                    or item.get("likes")
                                    or "0"
                                ),
                            }
                        )
                        for sub_key in ("sub_comments", "sub_comment_list", "subComments"):
                            sub_items = item.get(sub_key) or []
                            if not isinstance(sub_items, list):
                                continue
                            for sub in sub_items:
                                sub_text = (
                                    sub.get("content")
                                    or sub.get("comment_content")
                                    or sub.get("text")
                                    or ""
                                )
                                if not str(sub_text).strip():
                                    continue
                                sub_user_info = sub.get("user_info") or sub.get("user") or {}
                                captured_comment_items.append(
                                    {
                                        "user": (
                                            sub_user_info.get("nickname")
                                            or sub_user_info.get("name")
                                            or sub_user_info.get("userName")
                                            or "用户"
                                        ),
                                        "content": str(sub_text).strip(),
                                        "likes": str(
                                            sub.get("like_count")
                                            or sub.get("liked_count")
                                            or sub.get("likes")
                                            or "0"
                                        ),
                                    }
                                )
            except Exception:
                return

        page.on("response", capture_comment_response)

        # 监听器挂载后刷新一次，避免错过页面初始评论接口请求
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(500)
        except Exception:
            pass

        # 等待页面完全稳定
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        await asyncio.sleep(2)

        # 预加载评论区和延迟内容（下拉后回顶），并尽量触发评论接口请求
        try:
            await page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('button, div, span, a'));
                    const commentEntry = nodes.find(n => {
                        const t = (n.innerText || '').trim();
                        return t === '评论' || t.endsWith('评论') || t.includes('评论');
                    });
                    if (commentEntry) commentEntry.click();
                }"""
            )
            await page.wait_for_timeout(300)
            await page.evaluate(
                """() => {
                    const isVisible = (el) => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                    const nodes = Array.from(document.querySelectorAll('button, div, span, a'));
                    const hotTab = nodes.find((n) => {
                        if (!isVisible(n)) return false;
                        const t = (n.innerText || '').trim();
                        return t === '最热' || t.includes('最热');
                    });
                    if (hotTab) hotTab.click();
                }"""
            )
            await page.wait_for_timeout(350)
            for _ in range(4):
                await page.mouse.wheel(0, 1400)
                await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(400)
            await page.wait_for_timeout(1200)
        except Exception:
            pass

        # 优先从页面状态提取结构化数据，DOM 兜底
        result = await page.evaluate(
            r"""
            async () => {
                const compact = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                const uniq = (arr) => Array.from(new Set(arr.filter(Boolean)));
                const loginMarkers = ['马上登录即可', '手机号登录', '登录后查看', '请先登录', '打开小红书查看'];
                const expectedNoteId =
                    (window.location.pathname.match(/\/explore\/([0-9a-zA-Z]+)/) || [])[1] || '';
                const parseCount = (value) => {
                    const text = compact(value).toLowerCase().replace(/,/g, '');
                    if (!text) return 0;
                    const numMatch = text.match(/\\d+(\\.\\d+)?/);
                    if (!numMatch) return 0;
                    let num = parseFloat(numMatch[0]);
                    if (text.includes('万') || text.endsWith('w')) num *= 10000;
                    if (text.endsWith('k')) num *= 1000;
                    return Number.isFinite(num) ? Math.round(num) : 0;
                };
                const formatTime = (value) => {
                    if (value === null || value === undefined) return '';
                    if (typeof value === 'number') {
                        const ts = value > 1e12 ? value : value * 1000;
                        const d = new Date(ts);
                        if (!Number.isNaN(d.getTime())) {
                            return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
                        }
                    }
                    const text = compact(value);
                    if (/^\\d{10,13}$/.test(text)) {
                        const raw = Number(text);
                        const ts = text.length === 13 ? raw : raw * 1000;
                        const d = new Date(ts);
                        if (!Number.isNaN(d.getTime())) {
                            return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
                        }
                    }
                    return text;
                };

                let title = compact(document.querySelector('h1')?.innerText) ||
                            compact(document.querySelector('[class*="title"]')?.innerText) ||
                            compact(document.title);
                let author = cleanAuthorName(document.querySelector('[class*="author"]')?.innerText) ||
                             cleanAuthorName(document.querySelector('[class*="nickname"]')?.innerText) ||
                             cleanAuthorName(document.querySelector('a[href*="/user/profile/"]')?.innerText);
                let content = '';
                let likes = '';
                let collects = '';
                let comments = '';
                let noteId = '';
                let authorId = '';
                let xiaohongshuId = '';
                let editInfo = '';
                const images = [];
                const hashtags = [];
                const imageKeySet = new Set();
                const imageObjectKeySet = new Set();
                const hotCommentMap = new Map();
                let hasStructuredImages = false;

                const toPathKey = (url) => {
                    const value = compact(url);
                    if (!value) return '';
                    try {
                        const u = new URL(value, window.location.origin);
                        return `${u.host}${u.pathname}`;
                    } catch (e) {
                        return value.split('?')[0];
                    }
                };
                function cleanAuthorName(name) {
                    let text = compact(name);
                    if (!text) return '';
                    text = text.replace(/^[\\s@]+/, '');
                    text = text.replace(/\\s+(?:\\d+(?:\\.\\d+)?[wW万kK]?|\\d+\\+)\\s*$/, '');
                    return compact(text);
                }

                const addImage = (url) => {
                    const value = compact(url);
                    if (!value) return;
                    if (value.includes('avatar')) return;
                    if (!(value.includes('xhscdn') || value.includes('sns-webpic'))) return;
                    const key = value.split('?')[0];
                    if (imageKeySet.has(key)) return;
                    imageKeySet.add(key);
                    images.push(value);
                };
                const pickBestImageUrl = (img) => {
                    if (!img) return '';
                    if (typeof img === 'string') return compact(img);
                    const candidates = [];
                    const pushCandidate = (value, score = 0) => {
                        const url = compact(value);
                        if (!url) return;
                        if (!(url.includes('xhscdn') || url.includes('sns-webpic'))) return;
                        candidates.push({ url, score });
                    };
                    pushCandidate(img.urlOrigin, 120);
                    pushCandidate(img.originUrl, 120);
                    pushCandidate(img.original, 110);
                    pushCandidate(img.urlDefault, 100);
                    pushCandidate(img.url, 90);
                    pushCandidate(img.urlPre, 80);
                    if (Array.isArray(img.infoList)) {
                        for (const info of img.infoList) {
                            const width = Number(info?.width || info?.w || 0) || 0;
                            const height = Number(info?.height || info?.h || 0) || 0;
                            pushCandidate(
                                info?.url || info?.urlOrigin || info?.originUrl || info?.original,
                                70 + Math.round((width * height) / 100000)
                            );
                        }
                    }
                    if (candidates.length === 0) return '';
                    candidates.sort((a, b) => b.score - a.score);
                    return candidates[0].url;
                };
                const addTag = (tag) => {
                    let value = compact(tag).replace(/^#/, '');
                    value = value.replace('[话题]', '').replace('［话题］', '');
                    value = value.replace(/^[\[\]【】]+|[\[\]【】]+$/g, '');
                    if (!value) return;
                    const hasChinese = /[\\u4e00-\\u9fa5]/.test(value);
                    if (!hasChinese && value.length < 2) return;
                    hashtags.push(value);
                };
                const normalizeCommentKey = (text) =>
                    compact(text)
                        .replace(/\[[^\]]+\]/g, '')
                        .replace(/[^\\u4e00-\\u9fa5A-Za-z0-9]/g, '')
                        .toLowerCase()
                        .slice(0, 120);
                const addHotComment = (item) => {
                    if (!item) return;
                    const contentText = compact(item.content || item.text || item.comment || item.desc);
                    if (contentText.length < 2 || contentText.length > 300) return;
                    const userInfo = item.userInfo || item.user || item.author || item.commentUserInfo || {};
                    const user = compact(userInfo.nickname || userInfo.name || userInfo.userName || userInfo.nickName || userInfo.displayName || '');
                    const likesText = compact(
                        item.likeCount ?? item.likedCount ?? item.likes ?? item.interactInfo?.likedCount ?? item.interactInfo?.likeCount ?? ''
                    );
                    const key = normalizeCommentKey(contentText);
                    if (!key) return;
                    const nextItem = {
                        user: user || '用户',
                        content: contentText,
                        likes: likesText || '0',
                        likesValue: parseCount(likesText)
                    };
                    const prev = hotCommentMap.get(key);
                    if (!prev || nextItem.likesValue > prev.likesValue) {
                        hotCommentMap.set(key, nextItem);
                    }
                };

                const state = window.__INITIAL_STATE__ || window.__INITIAL_DATA__ || {};
                const noteCandidates = [];
                const walk = (obj, depth, path) => {
                    if (!obj || depth > 6) return;
                    if (Array.isArray(obj)) {
                        for (const item of obj) walk(item, depth + 1, path);
                        return;
                    }
                    if (typeof obj !== 'object') return;

                    const noteText = compact(obj.desc || obj.content || obj.noteDesc || '');
                    const hasNoteSignal =
                        noteText.length > 10 &&
                        (obj.imageList || obj.images || obj.imageListV2 || obj.imageListV3 || obj.user || obj.author);
                    if (hasNoteSignal) noteCandidates.push(obj);

                    if (/comment/i.test(path)) addHotComment(obj);

                    for (const key of Object.keys(obj)) {
                        walk(obj[key], depth + 1, `${path}.${key}`);
                    }
                };
                walk(state, 0, 'state');

                const matchedById = expectedNoteId
                    ? noteCandidates.filter((item) => {
                        const candidateId = compact(item.noteId || item.id || item.note_id || '');
                        return candidateId === expectedNoteId;
                    })
                    : [];

                const pickPool = matchedById.length > 0 ? matchedById : noteCandidates;

                const pick = pickPool
                    .sort((a, b) => {
                        const score = (obj) => {
                            const textLen = compact(obj.desc || obj.content || obj.noteDesc || '').length;
                            const titleLen = compact(obj.title || obj.displayTitle || obj.name || '').length;
                            const imgList = obj.imageList || obj.images || obj.imageListV2 || obj.imageListV3 || [];
                            const candidateId = compact(obj.noteId || obj.id || obj.note_id || '');
                            const idBonus = expectedNoteId
                                ? (candidateId === expectedNoteId ? 100000 : -1000)
                                : 0;
                            return textLen + titleLen + (Array.isArray(imgList) ? imgList.length * 12 : 0) + idBonus;
                        };
                        return score(b) - score(a);
                    })[0];

                if (pick) {
                    const pickTitle = compact(pick.title || pick.displayTitle || pick.name);
                    const titleLooksNoisy =
                        !title ||
                        title.length > 60 ||
                        /(?:-\s*小红书|_小红书)\s*$/i.test(title) ||
                        loginMarkers.some((marker) => title.includes(marker));
                    const shouldOverrideTitle = titleLooksNoisy;
                    if (pickTitle && shouldOverrideTitle) title = pickTitle;
                    content = content || compact(pick.desc || pick.content || pick.noteDesc);
                    const user = pick.user || pick.author || {};
                    const authorFromNote = cleanAuthorName(
                        user.nickname || user.name || user.userName || user.nickName || ''
                    );
                    const handleFromNote = compact(
                        user.redId ||
                        user.red_id ||
                        user.xiaohongshuId ||
                        user.xiaohongshu_id ||
                        user.xhsId ||
                        user.displayId ||
                        ''
                    ).replace(/^小红书号[：:\s]*/,'');
                    const authorCompactNoSpace = (author || '').replace(/\\s+/g, '');
                    const authorLooksNoisy =
                        !author || /(?:\\d+(?:\\.\\d+)?[wW万kK]?|\\d+\\+)$/.test(authorCompactNoSpace);
                    if (authorFromNote && authorLooksNoisy) author = authorFromNote;
                    if (handleFromNote) xiaohongshuId = handleFromNote;

                    noteId = compact(pick.noteId || pick.id || pick.note_id || '');
                    authorId = compact(user.userId || user.id || user.user_id || '');

                    const interact = pick.interactInfo || pick.interact || pick.interaction || {};
                    likes = compact(likes || interact.likedCount || interact.likeCount || interact.likes || pick.likedCount || '');
                    collects = compact(collects || interact.collectedCount || interact.collectCount || interact.collects || pick.collectedCount || '');
                    comments = compact(comments || interact.commentCount || interact.comments || pick.commentCount || '');

                    const imgList = pick.imageList || pick.images || pick.imageListV2 || pick.imageListV3 || [];
                    const collectImage = (img) => {
                        if (!img) return;
                        if (typeof img === 'string') {
                            addImage(img);
                            return;
                        }
                        const objectKey =
                            compact(img.imageId || img.fileId || img.id || img.traceId || '') ||
                            toPathKey(
                                img.url || img.original || img.originUrl || img.urlDefault || img.urlPre || img.urlOrigin
                            );
                        if (objectKey && imageObjectKeySet.has(objectKey)) return;
                        if (objectKey) imageObjectKeySet.add(objectKey);
                        const bestUrl = pickBestImageUrl(img);
                        addImage(bestUrl);
                    };
                    if (Array.isArray(imgList)) {
                        for (const img of imgList) collectImage(img);
                        if (images.length > 0) hasStructuredImages = true;
                    }

                    const tagList = pick.tagList || pick.tags || pick.hashTags || pick.hashtags || [];
                    if (Array.isArray(tagList)) {
                        for (const tag of tagList) {
                            if (typeof tag === 'string') {
                                addTag(tag);
                            } else if (tag && typeof tag === 'object') {
                                addTag(tag.name || tag.tagName || tag.title || tag.text);
                            }
                        }
                    }

                    const timeRaw = pick.time || pick.publishTime || pick.lastUpdateTime || pick.updateTime || pick.createTime || '';
                    const locationRaw = compact(pick.ipLocation || pick.ip_location || pick.location || '');
                    const timeText = formatTime(timeRaw);
                    editInfo = compact(`${timeText} ${locationRaw}`);
                }

                if (!content) {
                    const contentSelectors = [
                        '#detail-desc',
                        '.note-content',
                        '.desc-content',
                        '.content span',
                        '.note-text',
                        '[class*="note"][class*="content"]',
                        '[class*="desc"]'
                    ];
                    for (const selector of contentSelectors) {
                        const el = document.querySelector(selector);
                        const text = compact(el?.innerText);
                        if (text.length > 10) {
                            content = text;
                            break;
                        }
                    }
                }

                if (!hasStructuredImages && images.length === 0) {
                    const noteImageSelectors = [
                        '[class*="note-scroller"] img',
                        '[class*="note-slider"] img',
                        '[class*="swiper"] img',
                        '.swiper-slide img',
                        '[class*="note"] img',
                        '[class*="carousel"] img'
                    ];
                    for (const selector of noteImageSelectors) {
                        document.querySelectorAll(selector).forEach((img) => addImage(img.src));
                    }
                }
                document.querySelectorAll('span, div').forEach((el) => {
                    const text = compact(el.innerText);
                    if (!text || !/\\d/.test(text)) return;
                    if (!likes && text.includes('赞')) likes = text.replace(/[^0-9万wWkK.]/g, '');
                    if (!collects && text.includes('收藏')) collects = text.replace(/[^0-9万wWkK.]/g, '');
                    if (!comments && text.includes('评论')) comments = text.replace(/[^0-9万wWkK.]/g, '');
                });

                const tagSource = compact(`${title} ${content}`);
                const tagMatches = tagSource.match(/#([\\u4e00-\\u9fa5A-Za-z0-9_\\-]+)/g) || [];
                tagMatches.forEach((tag) => addTag(tag));

                document.querySelectorAll('[class*="comment"]').forEach((node) => {
                    const contentNode = node.querySelector('[class*="content"], p, span');
                    const userNode = node.querySelector('[class*="name"], [class*="user"]');
                    const likeNode = node.querySelector('[class*="like"]');
                    addHotComment({
                        content: contentNode?.innerText || node.innerText,
                        user: { nickname: userNode?.innerText || '' },
                        likeCount: likeNode?.innerText || ''
                    });
                });

                // 评论 API：总是尝试拉取，优先用结构化点赞数覆盖 DOM 的“10+”文本
                const fetchCommentPage = async (noteIdForApi, cursor = '') => {
                    const searchParams = new URLSearchParams(window.location.search || '');
                    const xsecToken = compact(searchParams.get('xsec_token'));
                    const commentUrl =
                        `/api/sns/web/v2/comment/page?note_id=${encodeURIComponent(noteIdForApi)}` +
                        `&cursor=${encodeURIComponent(cursor)}&top_comment_id=&image_formats=jpg,webp,avif` +
                        (xsecToken ? `&xsec_token=${encodeURIComponent(xsecToken)}` : '');
                    const commentResp = await fetch(commentUrl, {
                        credentials: 'include',
                        headers: {
                            'accept': 'application/json, text/plain, */*'
                        }
                    });
                    if (!commentResp.ok) return null;
                    const commentJson = await commentResp.json();
                    const data = commentJson?.data || {};
                    const lists = [data.top_comments, data.comments, data.comment_list];
                    for (const list of lists) {
                        if (!Array.isArray(list)) continue;
                        for (const item of list) {
                            addHotComment({
                                content: item?.content || item?.comment_content || item?.text || '',
                                user: item?.user_info || item?.user || {},
                                likeCount: item?.like_count ?? item?.liked_count ?? item?.likes ?? ''
                            });
                            const subLists = [item?.sub_comments, item?.sub_comment_list, item?.subComments];
                            for (const subList of subLists) {
                                if (!Array.isArray(subList)) continue;
                                for (const sub of subList) {
                                    addHotComment({
                                        content: sub?.content || sub?.comment_content || sub?.text || '',
                                        user: sub?.user_info || sub?.user || {},
                                        likeCount: sub?.like_count ?? sub?.liked_count ?? sub?.likes ?? ''
                                    });
                                }
                            }
                        }
                    }
                    return data;
                };

                const noteIdForApi = noteId || expectedNoteId;
                if (noteIdForApi) {
                    try {
                        const first = await fetchCommentPage(noteIdForApi, '');
                        const nextCursor = first?.cursor || first?.next_cursor || '';
                        if (nextCursor) {
                            await fetchCommentPage(noteIdForApi, nextCursor);
                        }
                    } catch (e) {}
                }

                const hotComments = Array.from(hotCommentMap.values())
                    .sort((a, b) => (b.likesValue || 0) - (a.likesValue || 0));

                return {
                    title: title || '',
                    author: cleanAuthorName(author || ''),
                    content: content || '',
                    likes: likes || '',
                    collects: collects || '',
                    comments: comments || '',
                    images: uniq(images),
                    hashtags: uniq(hashtags),
                    hotComments: hotComments.slice(0, 10).map(({ user, content, likes }) => ({ user, content, likes })),
                    editInfo: editInfo || '',
                    noteId: noteId || '',
                    authorId: authorId || '',
                    xiaohongshuId: xiaohongshuId || '',
                    source: pick ? 'initial_state+dom' : 'dom'
                };
            }
        """
        )

        # 给 response 回调留一点处理窗口，避免评论响应还未写入 captured_comment_items
        await page.wait_for_timeout(350)

        # 合并页面接口抓到的评论数据（优先接口，避免 DOM 里的“10+”或遗漏）
        if captured_comment_items:
            merged_comments = dedupe_hot_comments(
                (result.get("hotComments") or []) + captured_comment_items
            )
            result["hotComments"] = [
                {
                    "user": c.get("user", "用户"),
                    "content": c.get("content", ""),
                    "likes": c.get("likes", "0"),
                }
                for c in merged_comments
            ]

        # 可选增强：通过 xhshow 请求签名接口，补齐评论点赞/图片等结构化信息
        xhshow_note_id = str(result.get("noteId") or "").strip() or extract_xhs_note_id_from_url(url)
        if xhshow_note_id:
            try:
                storage_state = await page.context.storage_state()
            except Exception:
                storage_state = {}

            cookie_dict = build_xhs_cookie_dict(storage_state)
            xhshow_enriched = enrich_xhs_via_xhshow(
                note_id=xhshow_note_id,
                source_url=url,
                cookie_dict=cookie_dict,
            )

            if xhshow_enriched:
                # 图片：若签名接口拿到图片列表，优先使用，避免抓到首页推荐流
                enriched_images = xhshow_enriched.get("images") or []
                if enriched_images:
                    result["images"] = enriched_images

                # 互动数据：优先数值更大的版本，避免页面局部渲染导致丢值
                for metric in ("likes", "collects", "comments"):
                    enriched_value = str(xhshow_enriched.get(metric) or "").strip()
                    current_value = str(result.get(metric) or "").strip()
                    if parse_interaction_count(enriched_value) > parse_interaction_count(current_value):
                        result[metric] = enriched_value

                # 评论：去重合并，保留点赞更高条目
                enriched_comments = xhshow_enriched.get("hotComments") or []
                if enriched_comments:
                    merged_comments = dedupe_hot_comments(
                        (result.get("hotComments") or []) + enriched_comments
                    )
                    result["hotComments"] = [
                        {
                            "user": c.get("user", "用户"),
                            "content": c.get("content", ""),
                            "likes": c.get("likes", "0"),
                        }
                        for c in merged_comments
                    ]

                enriched_author_id = clean_inline_text(xhshow_enriched.get("authorId", ""))
                if enriched_author_id and not clean_inline_text(result.get("authorId", "")):
                    result["authorId"] = enriched_author_id

                enriched_handle = sanitize_xiaohongshu_handle(
                    xhshow_enriched.get("xiaohongshuId", "")
                )
                if enriched_handle and not sanitize_xiaohongshu_handle(
                    result.get("xiaohongshuId", "")
                ):
                    result["xiaohongshuId"] = enriched_handle

                enriched_source = str(xhshow_enriched.get("source") or "").strip()
                if enriched_source:
                    base_source = str(result.get("source") or "").strip()
                    if base_source:
                        result["source"] = f"{base_source}+{enriched_source}"
                    else:
                        result["source"] = enriched_source

        # 小红书号补全：优先作者主页，再兜底站内搜索
        author_name = clean_inline_text(result.get("author", ""))
        author_id = clean_inline_text(result.get("authorId", ""))
        xhs_handle = sanitize_xiaohongshu_handle(result.get("xiaohongshuId", ""))
        try:
            if author_id and not xhs_handle:
                profile_info = await fetch_xiaohongshu_profile_info(page.context, author_id)
                xhs_handle = sanitize_xiaohongshu_handle(profile_info.get("xiaohongshuId", "")) or xhs_handle
                author_id = clean_inline_text(profile_info.get("authorId", "")) or author_id
            if author_name and (not author_id or not xhs_handle):
                search_info = await search_xiaohongshu_profile_info(page.context, author_name)
                if not author_id:
                    author_id = clean_inline_text(search_info.get("authorId", ""))
                if not xhs_handle:
                    xhs_handle = sanitize_xiaohongshu_handle(search_info.get("xiaohongshuId", ""))
        except Exception:
            pass

        if author_id:
            result["authorId"] = author_id
        if xhs_handle:
            result["xiaohongshuId"] = xhs_handle

        # 小红书专用格式化（用于直接 read 输出）
        markdown = f"# {result.get('title', '无标题')}\n\n"
        markdown += f"> 作者：**{result.get('author', '未知')}**  \n"
        if result.get("xiaohongshuId"):
            markdown += f"> 小红书号：{result.get('xiaohongshuId')}  \n"
        markdown += "> 平台：小红书  \n"

        likes = result.get("likes", "")
        collects = result.get("collects", "")
        comments_count = result.get("comments", "")
        if likes or collects or comments_count:
            markdown += "> 互动："
            if likes:
                markdown += f"👍 {likes}赞 "
            if collects:
                markdown += f"| ⭐ {collects}收藏 "
            if comments_count:
                markdown += f"| 💬 {comments_count}评论"
            markdown += "  \n"

        markdown += f"> 链接：[原文]({url})\n\n"
        markdown += "---\n\n"

        content_text = result.get("content", "")
        if content_text and len(content_text.strip()) > 10:
            markdown += "## 📝 正文内容\n\n"
            markdown += f"{content_text}\n\n"
        else:
            markdown += "## 📝 正文内容\n\n"
            markdown += "⚠️ 文字内容较少，请查看下方图片获取完整信息。\n\n"

        images = result.get("images", [])
        if images:
            markdown += "---\n\n## 📷 笔记图片\n\n"
            for i, img_url in enumerate(images, 1):
                markdown += f"![img_{i:02d}]({img_url})\n"

        hot_comments = result.get("hotComments", [])
        if hot_comments:
            markdown += "\n---\n\n## 💬 热门评论\n\n"
            for i, comment in enumerate(hot_comments, 1):
                comment_text = str(comment.get("content", "")).strip()
                if len(comment_text) > 150:
                    comment_text = comment_text[:150] + "..."
                user = str(comment.get("user", "用户")).strip() or "用户"
                likes_text = str(comment.get("likes", "0")).strip() or "0"
                markdown += f"{i}. ({likes_text}赞) {user}：{comment_text}\n\n"

        title_text = str(result.get("title", "")).strip()
        content_check = f"{title_text}\n{str(result.get('content', '')).strip()}"
        blocked_markers = [
            "当前笔记暂时无法浏览",
            "手机号登录",
            "马上登录即可",
            "安全验证",
            "请完成安全验证",
            "登录后查看",
            "打开小红书查看",
            "请先登录",
        ]
        if any(marker in content_check for marker in blocked_markers):
            return {
                "success": False,
                "error": "小红书链接已失效或无访问权限，请提供最新分享链接后重试",
            }

        return {
            "success": True,
            "strategy": "Playwright",
            "content": markdown,
            "metadata": {
                "title": result.get("title", ""),
                "author": result.get("author", ""),
                "likes": likes,
                "collects": collects,
                "comments": comments_count,
                "images": images,
                "hashtags": result.get("hashtags", []),
                "editInfo": result.get("editInfo", ""),
                "hotComments": hot_comments,
                "noteId": result.get("noteId", ""),
                "authorId": result.get("authorId", ""),
                "xiaohongshuId": result.get("xiaohongshuId", ""),
                "contentText": content_text,
                "platform": "小红书",
                "source": result.get("source", "dom"),
            },
        }

    except Exception as e:
        return {"success": False, "error": f"提取失败: {str(e)}"}
    finally:
        if browser:
            await browser.close()


async def read_with_playwright_async(url: str, platform_id: str) -> dict:
    """策略B-2：使用 Playwright 浏览器读取（需要登录态）"""
    try:
        from playwright.async_api import async_playwright
        import time

        auth_file = None

        # 小红书特殊处理：检测登录态，如无则交互式登录
        if platform_id == "xiaohongshu":
            if XIAOHONGSHU_AUTH_FILE.exists():
                auth_file = str(XIAOHONGSHU_AUTH_FILE)
                print("🔍 检测小红书登录态...")
                async with async_playwright() as p:
                    is_valid = await check_xiaohongshu_login(p, auth_file)
                if is_valid:
                    print("✅ 登录态有效")
                else:
                    print("⚠️  登录态已过期")
                    auth_file = None

            # 如无有效登录态，使用交互式登录并在同一会话抓取
            if not auth_file:
                async with async_playwright() as p:
                    page, browser = await interactive_xiaohongshu_login(p, url)
                    if not page:
                        return {"success": False, "error": "登录失败"}

                    # 直接在同一会话中提取内容
                    return await extract_xiaohongshu_content(page, browser, url)

        # 其他平台登录态
        if platform_id == "wechat" and WECHAT_AUTH_FILE.exists():
            auth_file = str(WECHAT_AUTH_FILE)

        async with async_playwright() as p:
            is_xiaohongshu = platform_id == "xiaohongshu"
            browser = await p.chromium.launch(
                headless=not is_xiaohongshu,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                ],
            )

            if platform_id == "xiaohongshu":
                context_config = {
                    "viewport": {"width": 1920, "height": 1080},
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
            else:
                mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002629) NetType/WIFI Language/zh_CN"
                context_config = {
                    "viewport": {"width": 390, "height": 844},
                    "user_agent": mobile_ua,
                    "locale": "zh-CN",
                    "timezone_id": "Asia/Shanghai",
                }

            if auth_file:
                context_config["storage_state"] = auth_file
                print(f"   [Debug] Loading auth from: {auth_file}")
                print(f"   [Debug] File exists: {Path(auth_file).exists()}")
            else:
                print(f"   [Debug] No auth file for platform: {platform_id}")

            context = await browser.new_context(**context_config)

            # ===== 优化3: 注入反检测脚本（仅非小红书平台）=====
            if platform_id != "xiaohongshu":
                await context.add_init_script("""
                    // 隐藏 navigator.webdriver
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });

                    // 模拟 chrome 对象
                    window.chrome = {
                        runtime: {},
                        loadTimes: () => {},
                        csi: () => {},
                        app: {}
                    };

                    // 修改 permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ||
                    parameters.name === 'clipboard-read' ||
                    parameters.name === 'clipboard-write'
                        ? Promise.resolve({state: 'prompt'})
                        : originalQuery(parameters)
                );

                // 添加插件模拟
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [
                        {
                            0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                            description: "Portable Document Format",
                            filename: "internal-pdf-viewer",
                            length: 1,
                            name: "Chrome PDF Plugin"
                        },
                        {
                            0: {type: "application/pdf", suffixes: "pdf", description: ""},
                            description: "Portable Document Format",
                            filename: "internal-pdf-viewer2",
                            length: 1,
                            name: "Chrome PDF Viewer"
                        }
                    ]
                });

                // 修改 languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en']
                });
            """)

            page = await context.new_page()

            # ===== 优化4: 更智能的页面加载策略 =====
            if platform_id == "xiaohongshu":
                # 小红书：使用 domcontentloaded 更快获取内容
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 等待JS渲染完成（增加等待时间确保内容加载）
                await page.wait_for_timeout(5000)
                # 额外等待确保页面稳定
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
            else:
                await page.goto(url, wait_until="networkidle", timeout=30000)

            # 等待页面完全加载
            await page.wait_for_timeout(2000)

            # 小红书风控/安全页直接拦截，避免误抓到非目标笔记数据
            if platform_id == "xiaohongshu":
                current_url = page.url or ""
                if "website-login/error" in current_url or "httpStatus=461" in current_url:
                    await browser.close()
                    return {
                        "success": False,
                        "error": "小红书触发风控(461)，请切换网络或稍后重试",
                    }

            # 检查是否需要验证
            content = await page.content()
            if "环境异常" in content or "完成验证" in content:
                # 尝试点击验证按钮
                verify_btn = await page.query_selector("text=去验证")
                if verify_btn:
                    await verify_btn.click()
                    await page.wait_for_timeout(3000)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    content = await page.content()

                if "环境异常" in content or "完成验证" in content:
                    await browser.close()
                    return {
                        "success": False,
                        "error": "需要手动验证，请运行 setup 命令登录",
                    }

            # 等待文章内容加载
            if platform_id == "wechat":
                try:
                    await page.wait_for_selector("#js_content", timeout=10000)
                except:
                    pass
            elif platform_id == "xiaohongshu":
                # 小红书：等待特定元素加载
                try:
                    # 等待标题或内容区域出现
                    await page.wait_for_selector(
                        "h1, #detail-desc, .note-content", timeout=10000
                    )
                except:
                    pass

            # 提取内容
            if platform_id == "wechat":
                result = await page.evaluate("""
                    () => {
                        const title = document.querySelector('#activity-name')?.innerText?.trim() || '';
                        const author = document.querySelector('#js_name')?.innerText?.trim() || '';
                        const content = document.querySelector('#js_content')?.innerText?.trim() || '';
                        const publishTime = document.querySelector('#publish_time')?.innerText?.trim() || '';
                        return { title, author, content, publishTime };
                    }
                """)
            elif platform_id == "xiaohongshu":
                try:
                    storage = await context.storage_state()
                    cookies = storage.get("cookies", [])
                    xhs_cookies = [
                        c for c in cookies if "xiaohongshu" in c.get("domain", "")
                    ]
                    has_session_cookie = any(
                        any(
                            keyword in c.get("name", "").lower()
                            for keyword in [
                                "session",
                                "token",
                                "auth",
                                "login",
                                "web_session",
                            ]
                        )
                        for c in xhs_cookies
                    )
                    login_check = await page.evaluate("""() => {
                        const pageText = document.body?.innerText || '';
                        const title = document.title || '';
                        const loginKeywords = ['马上登录', '登录即可', '请先登录', 'Login', '登录/注册', '扫码登录'];
                        const isLoginPage = loginKeywords.some(kw => pageText.includes(kw) || title.includes(kw));
                        return {isLoginPage};
                    }""")
                    page_signals = await page.evaluate("""() => {
                        const bodyText = document.body?.innerText || '';
                        const hasLoginForm = bodyText.includes('手机号登录') || bodyText.includes('获取验证码') || bodyText.includes('扫码') && bodyText.includes('登录');
                        const hasNoteContent = !!document.querySelector('#detail-desc, .note-content, .note-text');
                        const hasImage = Array.from(document.querySelectorAll('img')).some(img => img.src && img.src.includes('xhscdn'));
                        return {hasLoginForm, hasNoteContent, hasImage};
                    }""")

                    if login_check.get("isLoginPage") and page_signals.get(
                        "hasLoginForm"
                    ):
                        print("\n⚠️ 检测到登录页面，请扫码登录小红书")
                        print("   登录完成后会自动保存登录态并继续抓取\n")
                        login_success = False
                        for _ in range(150):
                            await page.wait_for_timeout(2000)
                            storage = await context.storage_state()
                            cookies = storage.get("cookies", [])
                            xhs_cookies = [
                                c
                                for c in cookies
                                if "xiaohongshu" in c.get("domain", "")
                            ]
                            has_session_cookie = any(
                                any(
                                    keyword in c.get("name", "").lower()
                                    for keyword in [
                                        "session",
                                        "token",
                                        "auth",
                                        "login",
                                        "web_session",
                                    ]
                                )
                                for c in xhs_cookies
                            )
                            page_signals = await page.evaluate("""() => {
                                const bodyText = document.body?.innerText || '';
                                const hasLoginForm = bodyText.includes('手机号登录') || bodyText.includes('获取验证码');
                                const hasNoteContent = !!document.querySelector('#detail-desc, .note-content, .note-text');
                                const hasImage = Array.from(document.querySelectorAll('img')).some(img => img.src && img.src.includes('xhscdn'));
                                return {hasLoginForm, hasNoteContent, hasImage};
                            }""")
                            if has_session_cookie and (
                                page_signals.get("hasNoteContent")
                                or page_signals.get("hasImage")
                            ):
                                login_success = True
                                break

                        if login_success:
                            DATA_DIR.mkdir(parents=True, exist_ok=True)
                            storage_state = await context.storage_state()
                            with open(
                                XIAOHONGSHU_AUTH_FILE, "w", encoding="utf-8"
                            ) as f:
                                json.dump(storage_state, f, indent=2)
                            print(f"✅ 登录态已保存: {XIAOHONGSHU_AUTH_FILE}")
                            await page.goto(
                                url, wait_until="domcontentloaded", timeout=30000
                            )
                            await page.wait_for_timeout(5000)
                        else:
                            await browser.close()
                            return {
                                "success": False,
                                "error": "登录态未获取，请运行 'python scripts/url_reader.py setup-xhs' 重新登录",
                                "hint": "扫码登录后再重试抓取",
                            }
                    elif login_check.get("isLoginPage") and not page_signals.get(
                        "hasLoginForm"
                    ):
                        await page.wait_for_timeout(6000)
                except Exception as e:
                    print(
                        f"   [Warning] Login check failed: {str(e)[:50]}, continuing..."
                    )

                # 统一走结构化提取，避免多套逻辑不一致
                return await extract_xiaohongshu_content(page, browser, url)
            else:
                # 通用提取
                result = await page.evaluate("""
                    () => {
                        const title = document.querySelector('h1')?.innerText?.trim() ||
                                     document.querySelector('title')?.innerText?.trim() || '';
                        const content = document.body.innerText || '';
                        return { title, author: '', content, publishTime: '' };
                    }
                """)

            await browser.close()

            if result.get("content") and len(result["content"]) > 100:
                # 通用格式化为 Markdown
                markdown = f"# {result.get('title', '无标题')}\n\n"
                if result.get("author"):
                    markdown += f"**作者**: {result['author']}\n"
                if result.get("publishTime"):
                    markdown += f"**发布时间**: {result['publishTime']}\n"
                markdown += f"\n---\n\n{result.get('content', '')}"

                return {
                    "success": True,
                    "strategy": "Playwright",
                    "content": markdown,
                    "metadata": {
                        "title": result.get("title", ""),
                        "author": result.get("author", ""),
                        "publishTime": result.get("publishTime", ""),
                    },
                }

            return {"success": False, "error": "页面内容提取失败"}

    except Exception as e:
        return {"success": False, "error": f"Playwright 错误: {str(e)}"}


def read_with_playwright(url: str, platform_id: str) -> dict:
    """Playwright 同步包装"""
    return asyncio.run(read_with_playwright_async(url, platform_id))


def read_url(
    url: str, verbose: bool = True, prefer_playwright_for_xiaohongshu: bool = False
) -> dict:
    """
    智能读取URL内容
    策略顺序：Firecrawl → Jina → Playwright
    """
    # 识别平台
    platform = identify_platform(url)
    if verbose:
        print(f"📍 平台识别: {platform['name']}")

    errors = []
    prefer_rich_xhs = (
        platform.get("id") == "xiaohongshu" and prefer_playwright_for_xiaohongshu
    )
    if prefer_rich_xhs and verbose:
        print("ℹ️ 小红书笔记模式：优先 Playwright 结构化提取（含高赞评论）")

    # 策略1: Firecrawl（如果有 API Key）
    if FIRECRAWL_API_KEY and not prefer_rich_xhs:
        if verbose:
            print("🔄 尝试策略 A: Firecrawl...")
        result = read_with_firecrawl(url)
        if result.get("success"):
            if verbose:
                print("✅ Firecrawl 读取成功")
            result["platform"] = platform
            return result
        errors.append(f"Firecrawl: {result.get('error')}")
        if verbose:
            print(f"❌ {result.get('error')}")

    should_try_jina_first = not platform.get("need_login")
    if prefer_rich_xhs:
        should_try_jina_first = False

    # 策略2: Jina Reader（免费，不需要登录的平台优先尝试）
    if should_try_jina_first:
        if verbose:
            print("🔄 尝试策略 B-1: Jina Reader...")
        result = read_with_jina(url)
        if result.get("success"):
            if verbose:
                print("✅ Jina Reader 读取成功")
            result["platform"] = platform
            return result
        errors.append(f"Jina: {result.get('error')}")
        if verbose:
            print(f"❌ {result.get('error')}")

    # 策略3: Playwright（需要登录的平台或前面都失败）
    if verbose:
        print("🔄 尝试策略 B-2: Playwright 浏览器...")
    result = read_with_playwright(url, platform["id"])
    if result.get("success"):
        if verbose:
            print("✅ Playwright 读取成功")
        result["platform"] = platform
        return result
    errors.append(f"Playwright: {result.get('error')}")
    if verbose:
        print(f"❌ {result.get('error')}")

    # 如果是需要登录的平台，或小红书强制富提取模式，Jina 作为最后尝试
    if platform.get("need_login") or prefer_rich_xhs:
        if verbose:
            print("🔄 最后尝试: Jina Reader...")
        result = read_with_jina(url)
        if result.get("success"):
            if verbose:
                print("✅ Jina Reader 读取成功")
            result["platform"] = platform
            return result
        errors.append(f"Jina (fallback): {result.get('error')}")

    return {"success": False, "platform": platform, "errors": errors}


def format_output(result: dict, url: str) -> str:
    """格式化输出为 Markdown"""
    if not result.get("success"):
        output = ["# ❌ 读取失败\n"]
        output.append(f"**URL**: {url}")
        output.append(f"**平台**: {result.get('platform', {}).get('name', '未知')}")
        output.append("\n**尝试的策略及错误**:")
        for err in result.get("errors", []):
            output.append(f"- {err}")
        output.append("\n**建议**:")
        output.append(
            "1. 如果是微信公众号，请运行 `python wechat_reader.py setup` 设置登录态"
        )
        output.append("2. 设置 FIRECRAWL_API_KEY 环境变量以使用 Firecrawl")
        output.append("3. 或手动复制文章内容")
        return "\n".join(output)

    platform = result.get("platform", {})
    metadata = result.get("metadata", {})
    content = result.get("content", "")

    output = []
    output.append(f"**来源**: {platform.get('name', '未知')}")
    output.append(f"**读取策略**: {result.get('strategy', '未知')}")
    output.append(f"**原文链接**: {url}")
    output.append("\n---\n")
    output.append(content)

    return "\n".join(output)


# ============== 保存功能 ==============


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """清理文件名，移除非法字符"""
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > max_length:
        name = name[:max_length]
    return name or "untitled"


def build_compact_note_name(title: str, content: str = "", max_length: int = 24) -> str:
    """生成紧凑命名（用于目录/主文件名）：去空格标点与 emoji，仅保留中英文数字"""
    base = normalize_note_title(title, content=content)
    base = clean_inline_text(base)
    base = re.sub(r"\s+", "", base)
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", base)
    if len(base) > max_length:
        base = base[:max_length]
    return base or "untitled"


def extract_title_from_content(content: str) -> str:
    """从内容中提取标题"""
    # 尝试从 Markdown 一级标题提取
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        title = match.group(1).strip()
        # 排除一些无意义的标题
        if (
            title
            and not title.startswith("来源")
            and not title.startswith("**")
            and len(title) > 2
        ):
            return title

    # 尝试从 **标题**: 格式提取
    match = re.search(r"\*\*标题\*\*[：:]\s*(.+)", content)
    if match:
        return match.group(1).strip()

    # 尝试从第一个有意义的行提取
    lines = content.strip().split("\n")
    for line in lines:
        line = line.strip()
        # 跳过空行、元数据行
        if (
            not line
            or line.startswith("**")
            or line.startswith("---")
            or line.startswith("#")
        ):
            continue
        if len(line) > 5 and len(line) < 100:
            return line[:50]

    return "untitled"


def resolve_note_markdown_path(note_dir: Path) -> Path:
    """解析笔记目录下的主 Markdown 文件路径（兼容历史 content.md）"""
    legacy = note_dir / "content.md"
    if legacy.exists():
        return legacy

    md_files = sorted(
        [p for p in note_dir.glob("*.md") if p.is_file()],
        key=lambda p: p.name,
    )
    if md_files:
        return md_files[0]

    return legacy


def build_note_markdown_filename(note_dir: Path) -> str:
    """生成唯一主笔记文件名：与目录同名，避免 graph 里全是 content"""
    folder_name = sanitize_filename(note_dir.name, max_length=120)
    if not folder_name:
        folder_name = "note"
    return f"{folder_name}.md"


def read_frontmatter_value(md_path: Path, key: str) -> str:
    """读取 markdown frontmatter 里的单个字段值"""
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""

    for line in lines[1:200]:
        if line.strip() == "---":
            break
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", line.strip())
        if m:
            return clean_inline_text(m.group(1))
    return ""


def find_existing_note_dir_by_note_id(platform_dir: Path, note_id: str) -> Path | None:
    """在同平台目录下查找已有 note_id 对应笔记目录（优先最早目录）"""
    target = clean_inline_text(note_id)
    if not target:
        return None

    matches = []
    for sub in platform_dir.iterdir():
        if not sub.is_dir():
            continue
        md_path = resolve_note_markdown_path(sub)
        if not md_path.exists():
            continue
        existed_note_id = read_frontmatter_value(md_path, "note_id")
        if existed_note_id == target:
            matches.append(sub)

    if not matches:
        return None

    # 选择最早日期目录，避免同 note_id 产生多个版本分叉
    matches.sort(key=lambda p: p.name)
    return matches[0]


def extract_images_from_content(content: str) -> list:
    """从内容中提取图片URL"""
    md_images = re.findall(r"!\[.*?\]\((https?://[^\s\)]+)\)", content)
    direct_images = re.findall(
        r"(https?://[^\s\)]+\.(?:jpg|jpeg|png|gif|webp|bmp)[^\s\)]*)",
        content,
        re.IGNORECASE,
    )
    xhs_images = re.findall(r"(https?://sns-webpic[^\s\)]+)", content)
    feishu_images = re.findall(
        r"(https?://[^\s\)]*feishu[^\s\)]+\.(?:jpg|jpeg|png|gif|webp)[^\s\)]*)",
        content,
        re.IGNORECASE,
    )
    qq_images = re.findall(
        r"(https?://docimg[^\s\)]+\.(?:jpg|jpeg|png|gif|webp)[^\s\)]*)",
        content,
        re.IGNORECASE,
    )
    all_images = list(
        dict.fromkeys(
            md_images + direct_images + xhs_images + feishu_images + qq_images
        )
    )
    return all_images


def download_image(url: str, save_dir: Path, index: int) -> str:
    """下载图片并返回本地文件名"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.xiaohongshu.com/",
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "webp" in content_type or "webp" in url:
            ext = ".webp"
        elif "png" in content_type or "png" in url:
            ext = ".png"
        elif "gif" in content_type or "gif" in url:
            ext = ".gif"
        else:
            ext = ".jpg"

        filename = f"img_{index:02d}{ext}"
        filepath = save_dir / filename

        with open(filepath, "wb") as f:
            f.write(response.content)

        return filename
    except Exception as e:
        return None


def parse_interaction_count(value) -> int:
    """把 1.2w / 3k / 120 统一转换为可排序数值"""
    text = str(value or "").strip().lower().replace(",", "")
    if not text:
        return 0

    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0

    number = float(match.group(0))
    if "万" in text or text.endswith("w"):
        number *= 10000
    elif text.endswith("k"):
        number *= 1000

    return int(number)


def rank_emoji(index: int) -> str:
    mapping = {
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
    }
    return mapping.get(index, f"{index}.")


def clean_inline_text(value: str) -> str:
    """清理多行/控制字符，确保可安全写入 YAML 单行字段"""
    text = str(value or "")
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_note_title(title: str, content: str = "") -> str:
    """规范化标题，避免抓取到站点 title 导致超长噪音标题"""
    t = clean_inline_text(title)
    if not t:
        t = ""
    t = re.sub(r"\s*[-_]\s*小红书\s*$", "", t, flags=re.IGNORECASE).strip()

    looks_noisy = (len(t) > 60) or ("；" in t and len(t) > 40) or (";" in t and len(t) > 40)
    if looks_noisy:
        lines = [clean_inline_text(x) for x in str(content or "").splitlines()]
        lines = [x for x in lines if x and len(x) >= 6]
        if lines:
            t = lines[0]

    # 优先取第一句/第一分句，避免“整段正文首行”被当作标题
    if len(t) > 48:
        for sep in ["。", "！", "？", ";", "；", "，", ","]:
            if sep not in t:
                continue
            head = clean_inline_text(t.split(sep, 1)[0])
            if 8 <= len(head) <= 80 and len(head) < len(t):
                t = head
                break

    # 进一步压缩：超长“定义句”标题取核心主语部分
    if len(t) > 42 and "是一个" in t:
        head = clean_inline_text(t.split("是一个", 1)[0])
        if 8 <= len(head) <= 42:
            t = head
    if len(t) > 42 and "提供了" in t:
        head = clean_inline_text(t.split("提供了", 1)[0])
        if 8 <= len(head) <= 42:
            t = head

    t = clean_inline_text(t)
    # 兜底清理：避免截断导致标题末尾仅剩孤立数字
    t = re.sub(r"\s+\d{1,2}$", "", t).strip()
    if len(t) > 42:
        t = t[:42].rstrip(" ，,;；:：")
    return t


def sanitize_author(author: str, likes: str = "") -> str:
    """修复作者字段混入互动数字等噪音问题"""
    text = clean_inline_text(author)
    if not text:
        return ""

    likes_token = clean_inline_text(likes).lower()
    if likes_token:
        compact_text = text.lower().replace(" ", "")
        compact_likes = likes_token.replace(" ", "")
        if compact_likes and compact_text.endswith(compact_likes):
            text = text[: len(text) - len(likes_token)].strip(" -|·")

    # 额外兜底：尾部纯数字/10+/1.2w 这类常见互动值
    text = re.sub(r"\s+(?:\d+(?:\.\d+)?[wW万kK]?|\d+\+)\s*$", "", text).strip()
    # 小红书页面上作者名旁经常拼接“关注”按钮文案
    text = re.sub(r"(关注|已关注)\s*$", "", text).strip()
    return text


def normalize_hashtag_text(tag: str) -> str:
    """清理 hashtag 文本中的 [话题] 等噪音"""
    t = clean_inline_text(tag).replace("#", "")
    t = t.replace("[话题]", "").replace("［话题］", "")
    t = t.strip("[]【】")
    t = re.sub(r"\s+", "", t)
    return t


def normalize_image_url_for_dedupe(url: str) -> str:
    """用于图片去重的标准化 key（忽略 query）"""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:
        return raw.split("?")[0]


def extract_xhs_note_id_from_url(url: str) -> str:
    """从小红书链接里提取 note_id"""
    try:
        parsed = urlparse(str(url or ""))
        match = re.search(r"/explore/([0-9a-zA-Z]+)", parsed.path or "")
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def build_xhs_cookie_dict(storage_state: dict) -> dict:
    """从 storage_state 里提取可用于 API 请求的 cookie 字典"""
    cookies = {}
    for cookie in (storage_state or {}).get("cookies", []):
        domain = str(cookie.get("domain", ""))
        if "xiaohongshu" not in domain:
            continue
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", "")).strip()
        if name and value:
            cookies[name] = value
    return cookies


def pick_best_xhs_image_url(image_obj) -> str:
    """从小红书图片对象中挑选最优原图 URL"""
    if not image_obj:
        return ""
    if isinstance(image_obj, str):
        return image_obj.strip()

    candidates = []

    def push(url_value: str, score: int = 0):
        url = str(url_value or "").strip()
        if not url:
            return
        if "xhscdn" not in url and "sns-webpic" not in url:
            return
        candidates.append((score, url))

    push(image_obj.get("urlOrigin"), 120)
    push(image_obj.get("originUrl"), 120)
    push(image_obj.get("original"), 110)
    push(image_obj.get("urlDefault"), 100)
    push(image_obj.get("url"), 90)
    push(image_obj.get("urlPre"), 80)

    info_list = image_obj.get("infoList") or image_obj.get("info_list") or []
    if isinstance(info_list, list):
        for info in info_list:
            if not isinstance(info, dict):
                continue
            width = int(info.get("width") or info.get("w") or 0)
            height = int(info.get("height") or info.get("h") or 0)
            area_score = int((width * height) / 100000) if width and height else 0
            push(
                info.get("url")
                or info.get("urlOrigin")
                or info.get("originUrl")
                or info.get("original"),
                70 + area_score,
            )

    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def enrich_xhs_via_xhshow(
    note_id: str,
    source_url: str,
    cookie_dict: dict,
    max_comment_pages: int = 2,
) -> dict:
    """可选增强：通过 xhshow 生成签名，请求小红书接口拿更完整结构化数据"""
    if not note_id or not cookie_dict:
        return {}

    if "a1" not in cookie_dict:
        return {}

    try:
        from xhshow import Xhshow
    except Exception:
        return {}

    client = Xhshow()
    result = {
        "hotComments": [],
        "images": [],
        "likes": "",
        "collects": "",
        "comments": "",
        "authorId": "",
        "xiaohongshuId": "",
        "source": "",
    }

    base_headers = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://www.xiaohongshu.com",
        "referer": source_url or f"https://www.xiaohongshu.com/explore/{note_id}",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    def signed_get(uri: str, params: dict) -> requests.Response | None:
        try:
            signed_headers = client.sign_headers_get(
                uri=uri,
                cookies=cookie_dict,
                params=params,
            )
            headers = {**base_headers, **signed_headers}
            return requests.get(
                f"https://edith.xiaohongshu.com{uri}",
                params=params,
                headers=headers,
                cookies=cookie_dict,
                timeout=20,
            )
        except Exception:
            return None

    def signed_post(uri: str, payload: dict) -> requests.Response | None:
        try:
            signed_headers = client.sign_headers_post(
                uri=uri,
                cookies=cookie_dict,
                payload=payload,
            )
            headers = {**base_headers, **signed_headers}
            return requests.post(
                f"https://edith.xiaohongshu.com{uri}",
                json=payload,
                headers=headers,
                cookies=cookie_dict,
                timeout=20,
            )
        except Exception:
            return None

    # 1) 笔记详情：优先拿 note_id 对应图片，减少串图风险
    try:
        query = parse_qs(urlparse(source_url).query)
    except Exception:
        query = {}

    feed_payload = {
        "source_note_id": note_id,
        "image_formats": ["jpg", "webp", "avif"],
        "extra": {"need_body_topic": "1"},
    }
    xsec_source = (query.get("xsec_source") or [""])[0].strip()
    xsec_token = (query.get("xsec_token") or [""])[0].strip()
    if xsec_source:
        feed_payload["xsec_source"] = xsec_source
    if xsec_token:
        feed_payload["xsec_token"] = xsec_token

    feed_resp = signed_post("/api/sns/web/v1/feed", feed_payload)
    if feed_resp is not None and feed_resp.status_code == 200:
        try:
            payload = feed_resp.json()
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            note_candidates = []

            def walk(obj):
                if isinstance(obj, dict):
                    note_id_value = str(
                        obj.get("note_id")
                        or obj.get("noteId")
                        or obj.get("noteid")
                        or obj.get("id")
                        or ""
                    )
                    has_note_signal = any(
                        key in obj
                        for key in [
                            "note_card",
                            "image_list",
                            "imageList",
                            "images_list",
                            "interact_info",
                            "interactInfo",
                        ]
                    )
                    if note_id_value == note_id or has_note_signal:
                        note_candidates.append(obj)

                    for value in obj.values():
                        walk(value)
                elif isinstance(obj, list):
                    for item in obj:
                        walk(item)

            walk(data)

            target = None
            for obj in note_candidates:
                note_card = obj.get("note_card") if isinstance(obj, dict) else None
                if isinstance(note_card, dict):
                    candidate_id = str(
                        note_card.get("note_id")
                        or note_card.get("noteId")
                        or note_card.get("id")
                        or ""
                    )
                    if candidate_id == note_id:
                        target = note_card
                        break

                candidate_id = str(
                    obj.get("note_id")
                    or obj.get("noteId")
                    or obj.get("id")
                    or ""
                )
                if candidate_id == note_id:
                    target = obj
                    break

            if isinstance(target, dict):
                interact = (
                    target.get("interact_info")
                    or target.get("interactInfo")
                    or target.get("interact")
                    or {}
                )
                user_info = target.get("user") or target.get("author") or {}
                result["authorId"] = str(
                    user_info.get("user_id")
                    or user_info.get("userId")
                    or user_info.get("id")
                    or ""
                ).strip()
                result["xiaohongshuId"] = sanitize_xiaohongshu_handle(
                    user_info.get("red_id")
                    or user_info.get("redId")
                    or user_info.get("xiaohongshu_id")
                    or user_info.get("xiaohongshuId")
                    or user_info.get("xhsId")
                    or user_info.get("displayId")
                    or ""
                )
                result["likes"] = str(
                    interact.get("liked_count")
                    or interact.get("like_count")
                    or interact.get("likes")
                    or target.get("liked_count")
                    or ""
                )
                result["collects"] = str(
                    interact.get("collected_count")
                    or interact.get("collect_count")
                    or interact.get("collects")
                    or target.get("collected_count")
                    or ""
                )
                result["comments"] = str(
                    interact.get("comment_count")
                    or interact.get("comments")
                    or target.get("comment_count")
                    or ""
                )

                image_objects = (
                    target.get("image_list")
                    or target.get("imageList")
                    or target.get("images_list")
                    or target.get("images")
                    or []
                )
                image_urls = []
                seen = set()
                if isinstance(image_objects, list):
                    for image_obj in image_objects:
                        image_url = pick_best_xhs_image_url(image_obj)
                        if not image_url:
                            continue
                        key = normalize_image_url_for_dedupe(image_url)
                        if key in seen:
                            continue
                        seen.add(key)
                        image_urls.append(image_url)

                if image_urls:
                    result["images"] = image_urls
                    result["source"] = "xhshow/feed"
        except Exception:
            pass

    # 2) 评论：尝试拿到更准确点赞数
    try:
        comments_out = []
        cursor = ""

        for _ in range(max_comment_pages):
            params = {
                "note_id": note_id,
                "cursor": cursor,
                "top_comment_id": "",
                "image_formats": "jpg,webp,avif",
            }
            resp = signed_get("/api/sns/web/v2/comment/page", params)
            if resp is None or resp.status_code != 200:
                break

            payload = resp.json()
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            merged = []
            for key in ("top_comments", "comments", "comment_list"):
                items = data.get(key)
                if isinstance(items, list):
                    merged.extend(items)

            if not merged:
                break

            for item in merged:
                content = str(
                    item.get("content")
                    or item.get("comment_content")
                    or item.get("text")
                    or ""
                ).strip()
                if not content:
                    continue
                user_info = item.get("user_info") or item.get("user") or {}
                user = str(
                    user_info.get("nickname")
                    or user_info.get("name")
                    or user_info.get("userName")
                    or "用户"
                ).strip()
                likes = str(
                    item.get("like_count")
                    or item.get("liked_count")
                    or item.get("likes")
                    or "0"
                ).strip()
                comments_out.append({"user": user or "用户", "content": content, "likes": likes})

            next_cursor = (
                str(data.get("cursor") or data.get("next_cursor") or "").strip()
            )
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        if comments_out:
            result["hotComments"] = dedupe_hot_comments(comments_out)
            result["source"] = "xhshow/comments"
    except Exception:
        pass

    return result


def dedupe_hot_comments(hot_comments: list) -> list:
    """按评论文本语义去重，保留点赞更高的一条"""
    if not hot_comments:
        return []

    best_by_key = {}
    for item in hot_comments:
        if isinstance(item, dict):
            user = str(item.get("user", "")).strip() or "用户"
            content = str(item.get("content", "")).strip()
            likes = str(item.get("likes", "")).strip() or "0"
        else:
            user = "用户"
            content = str(item).strip()
            likes = "0"

        if not content:
            continue

        key = re.sub(r"\[[^\]]+\]", "", content)
        key = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", key).lower()[:120]
        if not key:
            continue

        if not re.search(r"\d", likes):
            likes = "0"

        current = {
            "user": user.replace("|", "\\|"),
            "content": content.replace("\n", " ").replace("|", "\\|"),
            "likes": likes,
            "likes_num": parse_interaction_count(likes),
        }
        prev = best_by_key.get(key)
        if prev is None or current["likes_num"] > prev["likes_num"]:
            best_by_key[key] = current

    return sorted(best_by_key.values(), key=lambda x: x["likes_num"], reverse=True)[:10]


def is_placeholder_hot_comment(comment: dict) -> bool:
    """识别旧模板中的占位评论，避免覆盖真实高赞数据"""
    if not isinstance(comment, dict):
        return True
    user = clean_inline_text(comment.get("user", ""))
    likes = clean_inline_text(comment.get("likes", "0"))
    likes_num = parse_interaction_count(likes)
    generic_user = (
        not user
        or user in {"用户", "用户评论"}
        or "赞数未知" in user
        or user.startswith("用户评论")
    )
    return generic_user and likes_num <= 0


def extract_note_lines(content: str, limit: int = 4) -> list:
    """从正文里抽取可读的关键句，供个人笔记自动填充"""
    lines = []
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip(" -•\t")
        if not line:
            continue
        if line.startswith("#") and len(line) < 30:
            continue
        if line.count("#") >= 2 and len(line) < 80:
            continue
        if line.count("[话题]") >= 2:
            continue
        if line.count("#") >= 4:
            continue
        line = re.sub(r"#([0-9A-Za-z\u4e00-\u9fa5_\-]+)", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 12:
            continue
        lines.append(line)

    unique_lines = []
    seen = set()
    for line in lines:
        key = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", line).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_lines.append(line)
        if len(unique_lines) >= limit:
            break
    return unique_lines


def normalize_content_text(content: str) -> str:
    """清理正文中的平台噪音（如 [话题]、纯 hashtag 行、误入分隔线）"""
    text = str(content or "")
    text = text.replace("[话题]", "").replace("［话题］", "")
    text = text.replace("\uFFFC", " ").replace("￼", " ")
    text = re.sub(r"\s+\n", "\n", text)

    cleaned_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue

        # 去掉误入正文的分隔线
        if line in {"---", "***", "___"}:
            continue

        # 去掉纯话题行（如 #银行人的日常# #银行工作# ...）
        hashtag_tokens = re.findall(r"#([0-9A-Za-z\u4e00-\u9fa5_\-]+)#?", line)
        if len(hashtag_tokens) >= 2:
            left = re.sub(r"#([0-9A-Za-z\u4e00-\u9fa5_\-]+)#?", "", line)
            left = re.sub(r"[\s,，、|｜/;；:：·•]+", "", left)
            if not left:
                continue

        cleaned_lines.append(line)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
    return cleaned_text


def extract_markdown_section(markdown: str, heading: str) -> str:
    """提取指定二级标题下的 section（不含标题行）"""
    if not markdown or not heading:
        return ""
    lines = markdown.splitlines()
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == heading.strip():
            start = i + 1
            break
    if start < 0:
        return ""

    end = len(lines)
    for j in range(start, len(lines)):
        if j == start:
            continue
        if lines[j].startswith("## "):
            end = j
            break
    section = "\n".join(lines[start:end]).strip("\n")
    return section.strip()


def parse_hot_comments_from_markdown(markdown: str) -> list:
    """从已生成笔记中回读高赞评论（用于更新时保留高质量历史）"""
    section = extract_markdown_section(markdown, "## 💬 高赞评论")
    if not section:
        return []

    comments = []
    current = None
    for raw in section.splitlines():
        line = raw.strip()
        if line.startswith("### "):
            if current and current.get("content"):
                comments.append(current)
            header = line[4:].strip()
            m = re.search(r"\s·\s([0-9]+)赞", header)
            likes = m.group(1) if m else "0"
            user = re.sub(r"\s·\s[0-9]+赞\s*$", "", header).strip()
            user = re.sub(r"^[0-9️⃣🔟\.\s]+", "", user).strip()
            current = {"user": user or "用户", "likes": likes, "content": ""}
            continue

        if line.startswith(">"):
            if current is None:
                continue
            content_line = line[1:].strip()
            if current["content"]:
                current["content"] += "\n" + content_line
            else:
                current["content"] = content_line

    if current and current.get("content"):
        comments.append(current)
    return comments


def sanitize_personal_note_override(section_text: str) -> str:
    """清理回填个人笔记内容，移除误带入的页脚"""
    text = str(section_text or "").strip("\n")
    if not text:
        return ""
    lines = text.splitlines()
    trimmed = []
    for line in lines:
        if line.strip() == "---":
            break
        if line.strip().startswith("*收藏时间："):
            break
        if line.strip().startswith("*来源："):
            break
        trimmed.append(line)
    return "\n".join(trimmed).strip("\n")


def normalize_personal_keyword_links(section_text: str) -> str:
    """将个人笔记里的关键词索引从 #tag 统一为 [[tag]]（若尚未使用双链）"""
    text = str(section_text or "")
    if not text:
        return text

    m = re.search(r"(###\s*关键词索引\s*\n)([\s\S]*)\Z", text)
    if not m:
        return text

    header = m.group(1)
    block = m.group(2).strip()
    if not block or "[[" in block:
        return text

    tags = re.findall(r"#([0-9A-Za-z\u4e00-\u9fa5_\-]+)", block)
    uniq_tags = []
    for tag in tags:
        clean_tag = clean_inline_text(tag)
        if clean_tag and clean_tag not in uniq_tags:
            uniq_tags.append(clean_tag)

    if not uniq_tags:
        return text

    replaced = " ".join([f"[[{t}]]" for t in uniq_tags])
    return text[: m.start()] + header + replaced + "\n"


def is_generic_personal_keywords(section_text: str) -> bool:
    """识别关键词索引是否仅是平台/作者等泛词，避免保留低质量覆盖"""
    text = str(section_text or "")
    m = re.search(r"###\s*关键词索引\s*\n([\s\S]*)\Z", text)
    if not m:
        return False
    block = m.group(1)
    if "\n### " in block:
        block = block.split("\n### ", 1)[0]
    block = block.strip()
    links = re.findall(r"\[\[([^\]]+)\]\]", block)
    links = [clean_inline_text(x) for x in links if clean_inline_text(x)]
    if not links:
        return False
    if len(links) <= 2 and any(x == "小红书" for x in links):
        return True
    return False


def is_autogenerated_personal_note(section_text: str) -> bool:
    """识别自动模板生成的个人笔记，便于后续模板升级时自动刷新"""
    text = str(section_text or "")
    markers = [
        "内容类型 | 经验总结型笔记",
        "落地路径：[[输入]] → [[执行]] → [[反馈]]",
        "先搭一个 7 天可复用内容流水线",
        "每周复盘 1 个从洞察到发布的完整案例",
        "按 业务结构/现金流/估值 三层做复盘",
        "真正有效的地方在于把复杂流程拆成可复用步骤",
        "先做「业务结构-现金流-估值」三层核对",
        "建议以小步试错方式先验证",
        "赛博PM导师方法核心",
        "AI自动化运营的核心",
        "OSINT产品的核心",
        "公司研究落地路径",
    ]
    return any(marker in text for marker in markers)


def infer_relation_keywords(title: str, content: str, hot_comments: list, limit: int = 6) -> list:
    """无 hashtag 场景下，从标题/正文/评论提取可用于图谱的主题词"""
    text_parts = [clean_inline_text(title), clean_inline_text(content)]
    for item in (hot_comments or [])[:3]:
        if isinstance(item, dict):
            text_parts.append(clean_inline_text(item.get("content", "")))
    text = " ".join([p for p in text_parts if p])

    candidates = []
    lower_text = text.lower()

    # 常见小红书技术/内容创作关键词
    rules = [
        (r"赛博\s*pm|pm\s*导师", "赛博PM导师"),
        (r"\bai产品\b|ai\s*产品", "AI产品"),
        (r"产品经理", "产品经理"),
        (r"内容策略", "内容策略"),
        (r"趋势", "趋势把握"),
        (r"用户体验", "用户体验"),
        (r"本土化", "本土化"),
        (r"\byoutube\b", "YouTube"),
        (r"\bvibe\s*coding\b", "vibe coding"),
        (r"\bside\s*project\b", "side project"),
        (r"\bcleanshot\b", "cleanshot"),
        (r"\bexcalidraw\b", "excalidraw"),
    ]

    for pattern, label in rules:
        if re.search(pattern, lower_text, flags=re.IGNORECASE):
            if label not in candidates:
                candidates.append(label)
        if len(candidates) >= limit:
            break

    return [f"[[{item}]]" for item in candidates[:limit]]


def is_low_signal_topic(text: str) -> bool:
    t = clean_inline_text(text).lower()
    if not t:
        return True
    noisy_patterns = [
        r"测试",
        r"打卡",
        r"大赏",
        r"抽奖",
        r"互关",
        r"求助",
    ]
    return any(re.search(p, t) for p in noisy_patterns)


def normalize_topic_label(text: str) -> str:
    t = clean_inline_text(text)
    t = t.strip("#[]（）() ")
    if not t:
        return ""
    low = t.lower()
    if low in {"ai", "ai人工智能"}:
        return "人工智能"
    if low in {"vibe coding", "vibecoding"}:
        return "vibecoding"
    return t


def keyword_values(keyword_links: list) -> list:
    values = []
    for item in keyword_links or []:
        text = normalize_topic_label(str(item or ""))
        text = text.replace("[[", "").replace("]]", "")
        if text and text not in values:
            values.append(text)
    return values


def infer_note_domain(title: str, content: str, tags: list) -> str:
    text = " ".join(
        [clean_inline_text(title), clean_inline_text(content)] + [clean_inline_text(t) for t in (tags or [])]
    ).lower()
    if re.search(r"银行|股票|投资|授信|贷款|审批|估值|财报", text):
        return "finance"
    if re.search(r"world\s*monitor|osint|开源情报|情报|数据图层|全球互动地图|地理情报", text):
        return "osint_product"
    if re.search(r"openclaw|skills|自动运营|自动化运营|粉丝矩阵|工作流编排", text):
        return "ai_ops"
    if re.search(r"赛博\s*pm|pm\s*导师|youtube|transcribe|转译|内容创作|选题", text):
        return "creator_method"
    if re.search(r"拜年|向上社交|人脉|领导|贵人|同事|合作伙伴|新年", text):
        return "social"
    if re.search(r"ai|agent|vibe|产品经理|自动化|llm|模型", text):
        return "ai_product"
    return "generic"


def build_domain_seed_keywords(domain: str) -> list:
    mapping = {
        "finance": ["银行人的日常", "经营质量", "现金流", "估值", "观点验证"],
        "social": ["向上社交", "真诚", "细节", "持续性", "错峰发送"],
        "creator_method": ["赛博PM导师", "趋势把握", "转译表达", "用户反馈", "内容复盘"],
        "ai_ops": ["AI自动化运营", "技能编排", "流程自动化", "交付闭环", "风险控制"],
        "osint_product": ["OSINT", "多源聚合", "实时监测", "数据图层", "决策支持"],
        "ai_product": ["AI工具", "产品化表达", "效率提升", "执行复盘", "用户反馈"],
        "generic": ["核心主题", "证据链", "执行动作", "反馈验证"],
    }
    return mapping.get(domain, mapping["generic"])


def merge_keyword_index(keyword_index: list, seed_keywords: list, limit: int = 12) -> list:
    merged = []
    seen = set()

    def append_keyword(raw: str):
        clean_tag = normalize_topic_label(str(raw or ""))
        clean_tag = clean_tag.replace("[[", "").replace("]]", "").strip()
        if not clean_tag or clean_tag in seen:
            return
        seen.add(clean_tag)
        merged.append(f"[[{clean_tag}]]")

    for item in keyword_index or []:
        append_keyword(item)
    for item in seed_keywords or []:
        append_keyword(item)

    return merged[:limit]


def build_object_rows_by_domain(domain: str, keywords: list, hot_comments: list, image_count: int) -> list:
    k1 = keywords[0] if len(keywords) > 0 else "主题"
    k2 = keywords[1] if len(keywords) > 1 else "方法"
    k3 = keywords[2] if len(keywords) > 2 else "结果"
    hot_top_n = max(1, min(3, len(hot_comments or [])))

    if domain == "finance":
        return [
            ["[[投资者]]", "先看经营质量与现金流是否同向，避免只盯利润增速", "按季度记录营收/毛利率/经营现金净额三条曲线"],
            ["[[行业从业者]]", f"围绕 [[{k1}]] 识别组织效率和竞争优势", "把业务拆成产品线，逐条核对增长来源是否可持续"],
            ["[[观点分歧]]", "评论区争议集中在管理风格与估值弹性", f"优先复盘点赞前 {hot_top_n} 条观点，并补一条反证"],
        ]

    if domain == "creator_method":
        return [
            ["[[内容创作者]]", "爆款点不在口号，而在把复杂过程转成可执行步骤", "固定「结论-证据-动作」三段式，避免泛化表达"],
            ["[[产品经理]]", f"围绕 [[{k1}]] 抽象可迁移方法，而非单次经验", "每周复盘 1 个从洞察到发布的完整案例"],
            ["[[账号运营者]]", f"评论区反馈可校准 [[{k2}]] 的表达清晰度", f"优先处理点赞前 {hot_top_n} 条问题，反向优化下一篇脚本"],
        ]

    if domain == "ai_ops":
        return [
            ["[[运营负责人]]", "重点不是工具数量，而是任务链路是否可持续运行", "先定义日报/周报产物，再反推技能分工"],
            ["[[自动化搭建者]]", f"围绕 [[{k1}]] 建立输入标准和异常处理", "给每个技能补失败回退与人工兜底节点"],
            ["[[风险控制]]", f"自动化效率提升后，核心风险在 [[{k2}]] 与内容一致性", "用抽检清单校验事实、语气、发布时间窗"],
        ]

    if domain == "osint_product":
        return [
            ["[[信息分析者]]", "价值来自多源信息交叉验证，而非单一热点追踪", "固定来源分级：官方源/媒体源/社区源"],
            ["[[产品经理]]", f"围绕 [[{k1}]] 设计筛选与告警机制，减少噪音", "把图层按任务场景分组，默认只保留关键监测项"],
            ["[[决策团队]]", f"讨论焦点在 [[{k2}]] 的时效与可信度平衡", "每次事件复盘补一条「误报原因 + 修正规则」"],
        ]

    if domain == "ai_product":
        return [
            ["[[选题策略]]", f"高互动点集中在 [[{k1}]] 的落地案例，而不是概念科普", "每周固定 3 个「问题-方案-收益」题库"],
            ["[[产品化表达]]", f"用 [[{k2}]] 拆清前置条件与执行边界", "每个结论至少配 1 个可量化验证点"],
            ["[[执行复盘]]", f"围绕 [[{k3}]] 的反馈最能区分有效内容", f"从 {image_count} 张图和点赞前 {hot_top_n} 条评论提炼模板"],
        ]

    if domain == "social":
        return [
            ["[[核心关系]]", f"围绕 [[{k1}]] 做差异化触达，不用群发模板", "按重要性分批触达，先贵人后同事再朋友"],
            ["[[沟通场景]]", f"在 [[{k2}]] 场景里强调真诚与细节", "每条消息补一段具体合作回顾，避免空泛寒暄"],
            ["[[执行节奏]]", f"目标是形成 [[{k3}]] 的长期复利", f"复盘点赞前 {hot_top_n} 条反馈并更新话术库"],
        ]

    return [
        ["[[核心主题]]", f"围绕 [[{k1}]] 提炼可复用方法", "先抽取 3 条可直接执行动作"],
        ["[[表达结构]]", f"用 [[{k2}]] 强化论证链路", "补齐数据或案例，避免只有观点没有证据"],
        ["[[反馈验证]]", f"围绕 [[{k3}]] 存在分歧与补充", f"优先验证点赞前 {hot_top_n} 条观点再扩展执行"],
    ]


def build_personal_note_sections(
    title: str,
    content: str,
    hashtags: list,
    tags: list,
    hot_comments: list,
    likes: str,
    collects: str,
    comments: str,
    image_count: int,
) -> dict:
    """生成偏深度的个人笔记草稿（默认风格）"""
    core_lines = extract_note_lines(content, limit=4)
    top_tags = []
    for tag in (hashtags or []):
        clean_tag = normalize_topic_label(str(tag))
        if not clean_tag or is_low_signal_topic(clean_tag):
            continue
        if clean_tag not in top_tags:
            top_tags.append(clean_tag)
        if len(top_tags) >= 6:
            break
    if not top_tags:
        for tag in (tags or []):
            clean_tag = normalize_topic_label(str(tag))
            if not clean_tag or is_low_signal_topic(clean_tag):
                continue
            if clean_tag not in top_tags:
                top_tags.append(clean_tag)
            if len(top_tags) >= 6:
                break
    comment_lines = [c.get("content", "") for c in (hot_comments or []) if c.get("content")]

    keyword_index = [f"[[{tag}]]" for tag in top_tags]
    if not keyword_index:
        keyword_index = infer_relation_keywords(
            title=title,
            content=content,
            hot_comments=hot_comments,
            limit=6,
        )
    domain = infer_note_domain(title=title, content=content, tags=top_tags)
    seed_keywords = build_domain_seed_keywords(domain)
    keyword_index = merge_keyword_index(keyword_index=keyword_index, seed_keywords=seed_keywords, limit=12)
    if not keyword_index:
        keyword_index = ["[[核心主题]]", "[[可执行动作]]"]

    keywords = keyword_values(keyword_index)

    core_points = []
    k1 = keywords[0] if len(keywords) > 0 else "核心主题"
    k2 = keywords[1] if len(keywords) > 1 else "关键抓手"
    k3 = keywords[2] if len(keywords) > 2 else "验证结果"

    if domain == "finance":
        core_points.extend(
            [
                "[[银行人的日常]]的核心：[[经营质量]] + [[现金流]] + [[估值纪律]]",
                "[[公司研究]]落地路径：[[业务拆解]] -> [[指标验证]] -> [[观点迭代]]",
                f"高赞讨论聚焦 [[{k1}]] 与盈利质量，说明分歧点主要在可验证指标。",
            ]
        )
    elif domain == "creator_method":
        core_points.extend(
            [
                "[[赛博PM导师]]方法核心：[[趋势把握]] + [[转译表达]] + [[用户反馈]]",
                "[[内容创作]]落地路径：[[选题洞察]] -> [[结构化表达]] -> [[评论区校准]]",
                "重点不是堆工具，而是把复杂过程拆成可复制的交付动作。",
            ]
        )
    elif domain == "ai_ops":
        core_points.extend(
            [
                "[[AI自动化运营]]的核心：[[技能编排]] + [[流程自动化]] + [[持续监控]]",
                "[[自动化执行]]路径：[[任务拆解]] -> [[多技能协同]] -> [[结果复盘]]",
                "先定义稳定产物，再扩展技能数量，避免“看起来自动化，实际上不可控”。",
            ]
        )
    elif domain == "osint_product":
        core_points.extend(
            [
                "[[OSINT产品]]的核心：[[多源聚合]] + [[实时监测]] + [[可视化决策]]",
                "[[情报分析]]落地路径：[[源头分级]] -> [[图层筛选]] -> [[事件复盘]]",
                "真正可用的系统不是信息更多，而是能在关键时刻更快做出判断。",
            ]
        )
    elif domain == "ai_product":
        core_points.extend(
            [
                "[[AI工具]]的价值不在功能清单，而在是否缩短“洞察到交付”的路径。",
                "[[产品化表达]]要先讲边界条件，再讲动作步骤，避免不可执行。",
                f"把 [[{k1}]] 的案例按周复盘，持续校准 [[{k2}]] 的真实收益。",
            ]
        )
    elif domain == "social":
        core_points.extend(
            [
                "[[向上社交]]的核心：[[真诚]] + [[细节]] + [[持续性]]",
                "[[拜年时间]]选择：[[错峰发送]]，避免消息被淹没",
                f"有效沟通通常落在 [[{k1}]] 的细节与时机上。",
            ]
        )
    else:
        core_points.extend(
            [
                f"这篇内容的核心在于把 [[{k1}]] 具体化为可执行方法，而非停留在观点。",
                f"讨论焦点主要落在 [[{k2}]] 的可验证性与落地成本。",
                f"建议先做小范围验证，再围绕 [[{k3}]] 放大执行规模。",
            ]
        )

    for line in core_lines[:2]:
        clipped = line if len(line) <= 90 else line[:90] + "..."
        if clipped not in core_points:
            core_points.append(clipped)
        if len(core_points) >= 5:
            break
    core_points = core_points[:5]

    interactions = []
    if likes:
        interactions.append(f"{likes}赞")
    if collects:
        interactions.append(f"{collects}收藏")
    if comments:
        interactions.append(f"{comments}评论")
    interaction_summary = "｜".join(interactions) if interactions else ""

    thoughts = []
    if comment_lines:
        first_comment = str(comment_lines[0]).strip()
        thoughts.append(
            "高赞评论关注点：" + (first_comment[:80] + "..." if len(first_comment) > 80 else first_comment)
        )
    thoughts.append("把这篇内容拆成「结论 / 证据 / 动作」三栏再复盘一次。")
    thoughts.append("挑 1 条分歧评论，做一次反向验证。")

    object_rows = build_object_rows_by_domain(
        domain=domain,
        keywords=keywords,
        hot_comments=hot_comments or [],
        image_count=image_count,
    )
    object_rows.insert(1, ["互动概览", interaction_summary or "待补充", f"{image_count} 张图片"])

    return {
        "core_points": core_points,
        "thoughts": thoughts,
        "keyword_index": keyword_index,
        "object_rows": object_rows,
    }


def create_obsidian_note(
    title: str,
    author: str,
    platform: str,
    url: str,
    content: str,
    images: list,
    likes: str = "",
    collects: str = "",
    comments: str = "",
    tags: list = None,
    hashtags: list = None,
    edit_info: str = "",
    hot_comments: list = None,
    note_id: str = "",
    author_id: str = "",
    xiaohongshu_id: str = "",
    date_saved_override: str = "",
    stats_snapshot_at: str = "",
    personal_note_override: str = "",
) -> str:
    """
    创建标准 Obsidian 格式的 Markdown 笔记

    统一格式包含：
    1. YAML Frontmatter（元数据 + 关系图谱字段）
    2. 标题和作者信息（含编辑于）
    3. 正文内容
    4. 图片引用
    5. 标签（#hashtag格式）
    6. 高赞评论
    7. 个人笔记区域
    """
    if tags is None:
        tags = []
    if hashtags is None:
        hashtags = []
    if hot_comments is None:
        hot_comments = []

    title = normalize_note_title(title, content=content) or "untitled"
    author = sanitize_author(author, likes=likes)
    platform = clean_inline_text(platform)
    url = clean_inline_text(url)
    edit_info = clean_inline_text(edit_info)
    xiaohongshu_id = sanitize_xiaohongshu_handle(xiaohongshu_id)

    clean_hashtags = []
    for tag in hashtags:
        t = normalize_hashtag_text(tag)
        has_chinese = bool(re.search(r"[\u4e00-\u9fa5]", t))
        if t and (has_chinese or len(t) >= 2) and t not in clean_hashtags:
            clean_hashtags.append(t)
    hashtags = clean_hashtags

    clean_tags = [clean_inline_text(tag) for tag in tags if clean_inline_text(tag)]
    if not clean_tags and hashtags:
        clean_tags = hashtags[:4]
    tags = clean_tags

    now_date = datetime.now().strftime("%Y-%m-%d")
    date_saved = clean_inline_text(date_saved_override) or now_date
    stats_snapshot_at = clean_inline_text(stats_snapshot_at)
    license_mode = get_license_mode()
    fingerprint_id = build_provenance_fingerprint(
        url=url,
        title=title,
        note_id=note_id,
        author_id=author_id,
        date_saved=date_saved,
    )

    # YAML Frontmatter
    yaml_lines = [
        "---",
        f"title: {title}",
    ]

    if author:
        yaml_lines.append(f"author: {author}")

    yaml_lines.extend(
        [
            f"platform: {platform}",
            f"url: {url}",
            f"date_saved: {date_saved}",
        ]
    )
    if stats_snapshot_at:
        yaml_lines.append(f"stats_snapshot_at: {stats_snapshot_at}")

    if tags:
        yaml_lines.append("tags:")
        for tag in tags:
            yaml_lines.append(f"  - {tag}")

    if likes:
        yaml_lines.append(f"likes: {likes}")
    if collects:
        yaml_lines.append(f"collects: {collects}")
    if comments:
        yaml_lines.append(f"comments: {comments}")

    yaml_lines.append(f"images: {len(images)}")
    yaml_lines.append(f"generator: {GENERATOR_NAME}")
    yaml_lines.append(f"generator_version: {GENERATOR_VERSION}")
    yaml_lines.append(f"generator_repo: {GENERATOR_REPO}")
    yaml_lines.append(f"license_mode: {license_mode}")
    yaml_lines.append(f"fingerprint_id: {fingerprint_id}")
    yaml_lines.append(f"provenance_sentinel: {PROVENANCE_SENTINEL}")

    # 关系图谱字段
    if note_id:
        yaml_lines.append(f"note_id: {note_id}")
    if author_id:
        yaml_lines.append(f"author_id: {author_id}")
    yaml_lines.append(f"xiaohongshu_id: {xiaohongshu_id or 'unknown'}")

    yaml_lines.append("---")

    # 正文部分
    markdown_lines = [""]

    # 标题
    markdown_lines.append(f"# {title}")
    markdown_lines.append("")

    # 元信息引用块
    markdown_lines.append(f"> 作者：**{author or '未知'}**  ")
    if xiaohongshu_id:
        markdown_lines.append(f"> 小红书号：{xiaohongshu_id}  ")
    markdown_lines.append(f"> 平台：{platform}  ")

    # 互动数据
    interactions = []
    if likes:
        interactions.append(f"👍 {likes}赞")
    if collects:
        interactions.append(f"⭐ {collects}收藏")
    if comments:
        interactions.append(f"💬 {comments}评论")

    if interactions:
        markdown_lines.append(f"> 互动：{' | '.join(interactions)}  ")

    markdown_lines.append(f"> 链接：[原文]({url})")

    # 编辑于字段
    if edit_info:
        markdown_lines.append(f"> 编辑于：{edit_info}  ")

    markdown_lines.append("")
    markdown_lines.append("---")
    markdown_lines.append("")

    # 正文内容
    markdown_lines.append("## 📝 正文内容")
    markdown_lines.append("")
    normalized_content = normalize_content_text(content)
    if normalized_content and len(normalized_content.strip()) > 10:
        markdown_lines.append(normalized_content.strip())
    else:
        markdown_lines.append("⚠️ 文字内容较少，请查看下方图片获取完整信息。")
    markdown_lines.append("")

    # 图片部分
    if images:
        markdown_lines.append("---")
        markdown_lines.append("")
        markdown_lines.append(f"## 📷 笔记图片（共{len(images)}张）")
        markdown_lines.append("")

        for i, img_url in enumerate(images, 1):
            ext = img_url.split(".")[-1].split("?")[0][:4] if "." in img_url else "webp"
            if ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
                ext = "webp"
            markdown_lines.append(f"![img_{i:02d}](images/img_{i:02d}.{ext})")

        markdown_lines.append("")

    # 原始标签区域（笔记自带的hashtag）
    if hashtags:
        markdown_lines.append("---")
        markdown_lines.append("")
        markdown_lines.append("## 🏷️ 标签")
        markdown_lines.append("")
        markdown_lines.append(" ".join([f"#{tag}" for tag in hashtags]))
        markdown_lines.append("")

    normalized_comments = dedupe_hot_comments(hot_comments)

    # 高赞评论区域
    if normalized_comments:
        markdown_lines.append("---")
        markdown_lines.append("")
        markdown_lines.append("## 💬 高赞评论")
        markdown_lines.append("")
        for i, comment in enumerate(normalized_comments, 1):
            likes_count = comment.get("likes", "")
            user = comment.get("user", "")
            content_text = comment.get("content", "")
            rank = rank_emoji(i)
            likes_display = likes_count if str(likes_count).strip() else "0"
            markdown_lines.append(f"### {rank} {user} · {likes_display}赞")
            markdown_lines.append("")
            markdown_lines.append(f"> {content_text}")
            markdown_lines.append("")
        markdown_lines.append("")

    # 个人笔记区域
    personal_sections = build_personal_note_sections(
        title=title,
        content=content,
        hashtags=hashtags,
        tags=tags,
        hot_comments=normalized_comments,
        likes=likes,
        collects=collects,
        comments=comments,
        image_count=len(images),
    )

    markdown_lines.append("---")
    markdown_lines.append("")
    markdown_lines.append("## 📝 个人笔记")
    markdown_lines.append("")

    override_text = str(personal_note_override or "").strip()
    if override_text:
        markdown_lines.append(override_text)
        markdown_lines.append("")
    else:
        markdown_lines.append("### 核心概念")
        markdown_lines.append("")
        for item in personal_sections["core_points"]:
            markdown_lines.append(f"- {item}")
        markdown_lines.append("")

        markdown_lines.append("### 对象分级")
        markdown_lines.append("")
        markdown_lines.append("| 对象类型 | 观察结论 | 可执行动作 |")
        markdown_lines.append("|---------|---------|-----------|")
        for row in personal_sections.get("object_rows", []):
            a, b, c = row
            markdown_lines.append(f"| {a} | {b} | {c} |")
        markdown_lines.append("")

        markdown_lines.append("### 关键词索引")
        markdown_lines.append("")
        if personal_sections["keyword_index"]:
            markdown_lines.append(" ".join(personal_sections["keyword_index"]))
        else:
            for item in personal_sections["thoughts"]:
                markdown_lines.append(f"- {item}")
        markdown_lines.append("")

    # 页脚
    markdown_lines.append("---")
    markdown_lines.append("")
    markdown_lines.append(f"*收藏时间：{date_saved}*  ")
    markdown_lines.append(f"*来源：{platform}*")
    markdown_lines.append(f"*生成器：{GENERATOR_NAME}@{GENERATOR_VERSION}*")
    markdown_lines.append(
        f"<!-- {PROVENANCE_SENTINEL}; fingerprint={fingerprint_id}; license={license_mode}; repo={GENERATOR_REPO} -->"
    )
    markdown_lines.append("")

    return "\n".join(yaml_lines + markdown_lines)


def save_content(
    content: str,
    url: str,
    platform_name: str = "",
    output_dir: str = None,
    title: str = None,
    author: str = None,
    images: list = None,
    likes: str = "",
    collects: str = "",
    comments: str = "",
    tags: list = None,
    hashtags: list = None,
    edit_info: str = "",
    hot_comments: list = None,
    note_id: str = "",
    author_id: str = "",
    xiaohongshu_id: str = "",
    verbose: bool = True,
) -> dict:
    """
    保存内容到本地（统一 Obsidian 格式）

    目录结构：
    🌐 网络收藏/
    └── <平台>/
        └── YYYY-MM-DD_<标题>/
            ├── YYYY-MM-DD_<标题>.md
            └── images/
                ├── img_01.webp
                └── ...
    """
    output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)

    # 如果没有提供标题，从内容中提取
    if not title:
        title = extract_title_from_content(content)
    title = normalize_note_title(title, content=content) or "untitled"

    # 确定平台子目录
    platform_slug = sanitize_filename(platform_name) if platform_name else "其他"
    platform_dir = output_dir / platform_slug
    platform_dir.mkdir(parents=True, exist_ok=True)

    # 同一 note_id 固定更新同一目录（优先小红书）
    existing_dir = None
    if platform_name == "小红书" and note_id:
        existing_dir = find_existing_note_dir_by_note_id(platform_dir, note_id)

    # 创建笔记目录：若有历史目录则复用，否则新建 YYYY-MM-DD_标题
    if existing_dir:
        content_dir = existing_dir
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        compact_name = build_compact_note_name(title, content=content, max_length=24)
        folder_name = f"{date_str}_{compact_name}"
        content_dir = platform_dir / folder_name
        content_dir.mkdir(parents=True, exist_ok=True)

    # 创建 images 子目录
    images_dir = content_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # 清理旧图片，避免重复运行后残留历史文件干扰统计
    for stale_file in images_dir.glob("*"):
        if stale_file.is_file():
            try:
                stale_file.unlink()
            except Exception:
                pass

    # 从内容中提取图片URL
    raw_images = extract_images_from_content(content)
    if images:
        raw_images.extend(images)

    # 合并去重（保留顺序，避免 query 参数导致重复）
    content_images = []
    image_seen = set()
    for img_url in raw_images:
        key = normalize_image_url_for_dedupe(img_url)
        if not key or key in image_seen:
            continue
        image_seen.add(key)
        content_images.append(img_url)

    image_mapping = {}

    if content_images and verbose:
        print(f"📷 发现 {len(content_images)} 张图片，正在下载...")

    # 下载图片到 images 子目录
    for i, img_url in enumerate(content_images, 1):
        ext = img_url.split(".")[-1].split("?")[0][:4] if "." in img_url else "webp"
        if ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
            ext = "webp"
        local_name = f"img_{i:02d}.{ext}"

        try:
            response = requests.get(
                img_url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            )
            if response.status_code == 200:
                img_path = images_dir / local_name
                with open(img_path, "wb") as f:
                    f.write(response.content)
                image_mapping[img_url] = f"images/{local_name}"
                if verbose:
                    print(f"  ✓ {local_name}")
        except Exception as e:
            if verbose:
                print(f"  ✗ img_{i:02d}.{ext} (下载失败)")

    # 创建标准化的 Obsidian 笔记
    existing_md = resolve_note_markdown_path(content_dir)
    existing_date_saved = read_frontmatter_value(existing_md, "date_saved") if existing_md.exists() else ""
    date_saved_override = existing_date_saved or datetime.now().strftime("%Y-%m-%d")
    stats_snapshot_at = datetime.now().strftime("%Y-%m-%d") if platform_name == "小红书" else ""
    personal_note_override = ""

    if existing_md.exists():
        existing_title = normalize_note_title(read_frontmatter_value(existing_md, "title"))
        if existing_title and len(existing_title) <= 36:
            # 固化命名：优先保留已确认的短标题，避免后续抓取回写成长标题
            title = existing_title
        try:
            previous_markdown = existing_md.read_text(encoding="utf-8")
        except Exception:
            previous_markdown = ""

        # 复用更深度的个人笔记（避免被自动模板覆盖）
        existing_personal = extract_markdown_section(previous_markdown, "## 📝 个人笔记")
        existing_personal = sanitize_personal_note_override(existing_personal)
        has_default_object_rows = "内容类型 | 经验总结型笔记" in existing_personal
        keep_personal_override = (
            "### 对象分级" in existing_personal and "[[" in existing_personal
        )
        if keep_personal_override and is_autogenerated_personal_note(existing_personal):
            keep_personal_override = False
        if keep_personal_override and has_default_object_rows:
            keep_personal_override = False
        if keep_personal_override and is_generic_personal_keywords(existing_personal):
            keep_personal_override = False
        if keep_personal_override and len(existing_personal) >= 260:
            personal_note_override = normalize_personal_keyword_links(existing_personal)

        # 合并历史高赞评论，避免新抓取评论质量退化
        existing_hot_comments = parse_hot_comments_from_markdown(previous_markdown)
        if existing_hot_comments:
            if hot_comments:
                existing_hot_comments = [
                    c for c in existing_hot_comments if not is_placeholder_hot_comment(c)
                ]
            hot_comments = dedupe_hot_comments((hot_comments or []) + existing_hot_comments)

    obsidian_content = create_obsidian_note(
        title=title,
        author=author or "",
        platform=platform_name,
        url=url,
        content=content,
        images=list(image_mapping.values()),
        likes=likes,
        collects=collects,
        comments=comments,
        tags=tags,
        hashtags=hashtags,
        edit_info=edit_info,
        hot_comments=hot_comments,
        note_id=note_id,
        author_id=author_id,
        xiaohongshu_id=xiaohongshu_id,
        date_saved_override=date_saved_override,
        stats_snapshot_at=stats_snapshot_at,
        personal_note_override=personal_note_override,
    )

    # 保存主笔记文件（目录同名，避免 graph 中全是 content）
    md_filename = build_note_markdown_filename(content_dir)
    md_path = content_dir / md_filename
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(obsidian_content)

    # 迁移历史命名：如果 legacy content.md 存在且不是当前目标文件，删除旧文件
    legacy_md = content_dir / "content.md"
    if legacy_md.exists() and legacy_md != md_path:
        try:
            legacy_md.unlink()
        except Exception:
            pass

    if verbose:
        print(f"\n💾 已保存到: {content_dir}")
        print(f"   - {md_path.name}")
        print(f"   - images/: {len(image_mapping)} 张图片")

    return {
        "success": True,
        "dir": str(content_dir),
        "md_file": str(md_path),
        "images": len(image_mapping),
        "title": title,
    }


def read_and_save(url: str, output_dir: str = None, verbose: bool = True) -> dict:
    """
    读取URL内容并保存到本地（统一 Obsidian 格式）
    """
    result = read_url(url, verbose=verbose, prefer_playwright_for_xiaohongshu=True)

    if not result.get("success"):
        return result

    platform = result.get("platform", {})
    metadata = result.get("metadata", {})
    platform_id = str(platform.get("id", "")).strip()

    note_id_value = str(metadata.get("noteId", "")).strip()
    if platform_id == "xiaohongshu" and not note_id_value:
        note_id_value = extract_xhs_note_id_from_url(url)

    # 对结构化平台优先使用提取出的纯正文，避免重复嵌套 Markdown
    raw_content = metadata.get("contentText") or metadata.get("content") or result.get(
        "content", ""
    )

    save_result = save_content(
        content=raw_content,
        url=url,
        platform_name=platform.get("name", "未知"),
        output_dir=output_dir,
        title=metadata.get("title"),
        author=metadata.get("author"),
        images=metadata.get("images", []),
        likes=str(metadata.get("likes", "")),
        collects=str(metadata.get("collects", "")),
        comments=str(metadata.get("comments", "")),
        tags=metadata.get("tags", []),
        hashtags=metadata.get("hashtags", []),
        edit_info=str(metadata.get("editInfo", "")),
        hot_comments=metadata.get("hotComments", []),
        note_id=note_id_value,
        author_id=str(metadata.get("authorId", "")),
        xiaohongshu_id=str(metadata.get("xiaohongshuId", "")),
        verbose=verbose,
    )

    result["save"] = save_result
    return result


def extract_urls_from_text(text: str) -> list:
    """从任意文本里提取 URL 列表"""
    if not text:
        return []
    return re.findall(r"https?://[^\s\)\]\>\"']+", str(text))


def load_urls_from_source(source: str) -> list:
    """从单个输入源加载 URL（支持纯链接、文本、文件）"""
    source = str(source or "").strip()
    if not source:
        return []

    path = Path(source)
    if path.exists() and path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = path.read_text(encoding="utf-8", errors="ignore")
        return extract_urls_from_text(text)

    # 非文件，按文本提取 URL；若没有则尝试将其作为 URL 本身
    urls = extract_urls_from_text(source)
    if urls:
        return urls
    if source.startswith("http://") or source.startswith("https://"):
        return [source]
    return []


def run_batch_read_and_save(
    url_sources: list,
    output_dir: str = None,
    verbose: bool = True,
    retry: int = 1,
) -> dict:
    """批量处理链接并保存，返回汇总结果"""
    all_urls = []
    seen = set()
    for source in url_sources:
        for url in load_urls_from_source(source):
            if url in seen:
                continue
            seen.add(url)
            all_urls.append(url)

    if not all_urls:
        return {
            "success": False,
            "error": "未识别到有效链接，请提供 URL 或包含 URL 的文件",
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "items": [],
        }

    items = []
    succeeded = 0
    failed = 0

    for idx, url in enumerate(all_urls, 1):
        if verbose:
            print(f"\n{'=' * 60}")
            print(f"批量进度: {idx}/{len(all_urls)}")
            print(f"URL: {url}")
            print(f"{'=' * 60}")

        attempts = max(1, int(retry) + 1)
        last_result = None
        for attempt in range(1, attempts + 1):
            if verbose and attempts > 1:
                print(f"🔁 尝试 {attempt}/{attempts}")
            last_result = read_and_save(url, output_dir=output_dir, verbose=verbose)
            if last_result.get("success"):
                break
            if attempt < attempts:
                time.sleep(1.5)

        item = {
            "url": url,
            "success": bool(last_result and last_result.get("success")),
            "strategy": (last_result or {}).get("strategy"),
            "save": (last_result or {}).get("save"),
            "errors": (last_result or {}).get("errors", []),
        }
        items.append(item)

        if item["success"]:
            succeeded += 1
        else:
            failed += 1

    return {
        "success": failed == 0,
        "total": len(all_urls),
        "succeeded": succeeded,
        "failed": failed,
        "items": items,
    }


def dedupe_xhs_note_dirs(base_platform_dir: Path, keep_dir_name: str, note_id: str) -> list:
    """删除同 note_id 的重复目录，仅保留 keep_dir_name"""
    removed = []
    target_note_id = clean_inline_text(note_id)
    if not target_note_id:
        return removed

    keep_dir = base_platform_dir / keep_dir_name
    if not keep_dir.exists():
        return removed

    for sub in base_platform_dir.iterdir():
        if not sub.is_dir() or sub == keep_dir:
            continue
        md_path = resolve_note_markdown_path(sub)
        if not md_path.exists():
            continue
        current_note_id = read_frontmatter_value(md_path, "note_id")
        if current_note_id != target_note_id:
            continue

        # 显式删除重复目录
        for child in sorted(sub.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                child.rmdir()
        sub.rmdir()
        removed.append(sub.name)

    return removed


def migrate_note_markdown_filenames(base_dir: Path, platform_name: str = "") -> dict:
    """迁移历史 content.md 到目录同名 markdown 文件"""
    migrated = 0
    removed_legacy = 0
    skipped = 0
    errors = []

    if platform_name:
        targets = [base_dir / platform_name]
    else:
        targets = [p for p in base_dir.iterdir() if p.is_dir()]

    for platform_dir in targets:
        if not platform_dir.exists() or not platform_dir.is_dir():
            continue
        for note_dir in platform_dir.iterdir():
            if not note_dir.is_dir():
                continue
            legacy = note_dir / "content.md"
            target = note_dir / build_note_markdown_filename(note_dir)

            try:
                if legacy.exists():
                    if target.exists() and target != legacy:
                        legacy.unlink()
                        removed_legacy += 1
                    elif target != legacy:
                        legacy.rename(target)
                        migrated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(f"{note_dir}: {e}")

    return {
        "migrated": migrated,
        "removed_legacy": removed_legacy,
        "skipped": skipped,
        "errors": errors,
    }


def extract_hashtags_from_markdown(markdown: str) -> list:
    """从已生成 markdown 的标签区回读 hashtag 列表"""
    section = extract_markdown_section(markdown, "## 🏷️ 标签")
    if not section:
        return []
    tags = re.findall(r"#([0-9A-Za-z\u4e00-\u9fa5_\-]+)", section)
    uniq = []
    for tag in tags:
        clean_tag = normalize_hashtag_text(tag)
        if clean_tag and clean_tag not in uniq:
            uniq.append(clean_tag)
    return uniq


def rewrite_existing_note_markdown(md_path: Path, preserve_personal_note: bool = True) -> bool:
    """离线重建单篇笔记格式（不重新抓取网页）"""
    if not md_path.exists() or not md_path.is_file():
        return False

    old = md_path.read_text(encoding="utf-8")

    title = read_frontmatter_value(md_path, "title")
    author = read_frontmatter_value(md_path, "author")
    platform = read_frontmatter_value(md_path, "platform") or "小红书"
    url = read_frontmatter_value(md_path, "url")
    date_saved = read_frontmatter_value(md_path, "date_saved")
    stats_snapshot_at = read_frontmatter_value(md_path, "stats_snapshot_at")
    likes = read_frontmatter_value(md_path, "likes")
    collects = read_frontmatter_value(md_path, "collects")
    comments = read_frontmatter_value(md_path, "comments")
    note_id = read_frontmatter_value(md_path, "note_id")
    author_id = read_frontmatter_value(md_path, "author_id")
    xiaohongshu_id = read_frontmatter_value(md_path, "xiaohongshu_id")

    body_text = extract_markdown_section(old, "## 📝 正文内容")
    hot_comments = parse_hot_comments_from_markdown(old)
    hashtags = extract_hashtags_from_markdown(old)

    personal_note_override = ""
    if preserve_personal_note:
        personal_section = extract_markdown_section(old, "## 📝 个人笔记")
        personal_note_override = sanitize_personal_note_override(personal_section)

    edit_info = ""
    m = re.search(r"^>\s*编辑于：(.+?)\s*$", old, flags=re.MULTILINE)
    if m:
        edit_info = m.group(1).strip()

    images_dir = md_path.parent / "images"
    image_paths = []
    if images_dir.exists() and images_dir.is_dir():
        for p in sorted(images_dir.glob("*")):
            if p.is_file():
                image_paths.append(f"images/{p.name}")

    rebuilt = create_obsidian_note(
        title=title,
        author=author,
        platform=platform,
        url=url,
        content=body_text,
        images=image_paths,
        likes=likes,
        collects=collects,
        comments=comments,
        tags=hashtags[:6],
        hashtags=hashtags,
        edit_info=edit_info,
        hot_comments=hot_comments,
        note_id=note_id,
        author_id=author_id,
        xiaohongshu_id=xiaohongshu_id,
        date_saved_override=date_saved,
        stats_snapshot_at=stats_snapshot_at,
        personal_note_override=personal_note_override,
    )

    if rebuilt == old:
        return False
    md_path.write_text(rebuilt, encoding="utf-8")
    return True


def audit_markdown_format_issues(md_path: Path) -> list:
    """审计单篇笔记的关键格式问题"""
    issues = []
    if not md_path.exists() or not md_path.is_file():
        return ["文件不存在"]

    text = md_path.read_text(encoding="utf-8")
    required_sections = [
        "## 📝 正文内容",
        "## 📷 笔记图片",
        "## 📝 个人笔记",
    ]
    for section in required_sections:
        if section not in text:
            issues.append(f"缺少分区: {section}")

    body = extract_markdown_section(text, "## 📝 正文内容")
    body_lines = body.splitlines()
    # 允许 section 末尾用于分区的结构分隔线，不视为正文异常
    while body_lines and (
        not body_lines[-1].strip() or body_lines[-1].strip() in {"---", "***", "___"}
    ):
        body_lines.pop()

    for raw_line in body_lines:
        line = raw_line.strip()
        if not line:
            continue
        if line in {"---", "***", "___"}:
            issues.append("正文包含误入分隔线")
            break
        hashtag_tokens = re.findall(r"#([0-9A-Za-z\u4e00-\u9fa5_\-]+)#?", line)
        if len(hashtag_tokens) >= 2:
            residue = re.sub(r"#([0-9A-Za-z\u4e00-\u9fa5_\-]+)#?", "", line)
            residue = re.sub(r"[\s,，、|｜/;；:：·•]+", "", residue)
            if not residue:
                issues.append("正文包含纯话题标签行")
                break

    if (md_path.parent / "content.md").exists():
        issues.append("遗留 content.md 未迁移")

    # 归属取证字段（用于后续维权证据）
    required_frontmatter = [
        "generator",
        "generator_version",
        "license_mode",
        "fingerprint_id",
        "provenance_sentinel",
    ]
    for key in required_frontmatter:
        if not read_frontmatter_value(md_path, key):
            issues.append(f"缺少归属字段: {key}")

    return issues


def audit_and_repair_xhs_notes(
    base_platform_dir: Path,
    fix: bool = False,
    preserve_personal_note: bool = True,
) -> dict:
    """批量巡检/修复小红书笔记格式"""
    total = 0
    fixed = 0
    issue_files = []
    clean_files = 0
    errors = []

    if not base_platform_dir.exists():
        return {
            "total": 0,
            "fixed": 0,
            "clean": 0,
            "issue_files": [],
            "errors": [f"目录不存在: {base_platform_dir}"],
        }

    for note_dir in sorted([p for p in base_platform_dir.iterdir() if p.is_dir()]):
        md_path = resolve_note_markdown_path(note_dir)
        if not md_path.exists():
            continue
        total += 1

        try:
            issues = audit_markdown_format_issues(md_path)
            if issues and fix:
                changed = rewrite_existing_note_markdown(
                    md_path, preserve_personal_note=preserve_personal_note
                )
                # 修复后再次审计
                issues = audit_markdown_format_issues(md_path)
                if changed:
                    fixed += 1

            if issues:
                issue_files.append({"file": str(md_path), "issues": issues})
            else:
                clean_files += 1
        except Exception as e:
            errors.append(f"{md_path}: {e}")

    return {
        "total": total,
        "fixed": fixed,
        "clean": clean_files,
        "issue_files": issue_files,
        "errors": errors,
    }


def file_sha256(path: Path) -> str:
    """计算文件 SHA256（证据导出用）"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def export_xhs_proof_report(base_platform_dir: Path, output_csv: Path) -> dict:
    """导出小红书笔记证据清单（指纹 + 文件哈希）"""
    rows = []
    errors = []

    if not base_platform_dir.exists():
        return {
            "success": False,
            "count": 0,
            "output": str(output_csv),
            "errors": [f"目录不存在: {base_platform_dir}"],
        }

    for note_dir in sorted([p for p in base_platform_dir.iterdir() if p.is_dir()]):
        md_path = resolve_note_markdown_path(note_dir)
        if not md_path.exists():
            continue
        try:
            rows.append(
                {
                    "file": str(md_path),
                    "title": read_frontmatter_value(md_path, "title"),
                    "date_saved": read_frontmatter_value(md_path, "date_saved"),
                    "url": read_frontmatter_value(md_path, "url"),
                    "note_id": read_frontmatter_value(md_path, "note_id"),
                    "author_id": read_frontmatter_value(md_path, "author_id"),
                    "xiaohongshu_id": read_frontmatter_value(md_path, "xiaohongshu_id"),
                    "generator": read_frontmatter_value(md_path, "generator"),
                    "generator_version": read_frontmatter_value(md_path, "generator_version"),
                    "license_mode": read_frontmatter_value(md_path, "license_mode"),
                    "fingerprint_id": read_frontmatter_value(md_path, "fingerprint_id"),
                    "file_sha256": file_sha256(md_path),
                }
            )
        except Exception as e:
            errors.append(f"{md_path}: {e}")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "file",
        "title",
        "date_saved",
        "url",
        "note_id",
        "author_id",
        "xiaohongshu_id",
        "generator",
        "generator_version",
        "license_mode",
        "fingerprint_id",
        "file_sha256",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return {
        "success": True,
        "count": len(rows),
        "output": str(output_csv),
        "errors": errors,
    }


async def setup_xiaohongshu_login():
    """设置小红书登录态 - 智能检测版：自动检测登录成功并保存"""
    try:
        from playwright.async_api import async_playwright

        print("=" * 60)
        print("小红书登录设置")
        print("=" * 60)
        print("\n🌐 将打开浏览器，请在小红书网页完成登录...")
        print("\n📋 操作步骤：")
        print("   1. 浏览器打开后，扫码或手机号登录")
        print("   2. 登录成功后，点击任意笔记进入详情页")
        print("   3. 系统会自动检测登录状态并保存")
        print("   4. 完成后可以关闭浏览器\n")

        async with async_playwright() as p:
            # 启动浏览器
            browser = await p.chromium.launch(
                headless=False, args=["--disable-blink-features=AutomationControlled"]
            )

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            page = await context.new_page()

            # 访问小红书
            print("⏳ 正在打开小红书首页...")
            await page.goto(
                "https://www.xiaohongshu.com", wait_until="domcontentloaded"
            )
            print("✅ 页面已加载\n")

            # 优先触发首页登录按钮，拉起扫码弹窗（更稳定保留登录态）
            login_clicked = await page.evaluate("""() => {
                const isVisible = (el) => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const nodes = Array.from(document.querySelectorAll('button, a, span, div'));
                // 优先点击首页左侧纯“登录”按钮，避免误点到其它入口
                const exact = nodes.find(el => isVisible(el) && (el.innerText || '').trim() === '登录');
                if (exact) { exact.click(); return true; }
                const fallback = nodes.find(el => {
                    if (!isVisible(el)) return false;
                    const t = (el.innerText || '').trim();
                    return t === '登录/注册' || t.includes('扫码登录');
                });
                if (fallback) { fallback.click(); return true; }
                return false;
            }""")
            if login_clicked:
                print("✅ 已触发首页登录入口，请扫码二维码登录")
            else:
                print("⚠️ 未自动找到登录按钮，请手动点击首页“登录”")

            # 持续检测登录状态
            print("🔍 正在监测登录状态...")
            print("   （登录后点击任意笔记即可被检测到）\n")

            login_success = False
            check_count = 0

            while not login_success:
                await asyncio.sleep(2)
                check_count += 1

                try:
                    current_url = page.url
                    signals = await get_xiaohongshu_login_signals(page)

                    if (
                        not signals.get("hasLoginBtn")
                        and not signals.get("hasLoginPrompt")
                        and (
                            signals.get("hasUserProfileLink")
                            or signals.get("hasAvatar")
                            or signals.get("hasUserMenuText")
                            or "/user/profile" in current_url
                        )
                    ):
                        login_success = True
                        print("✅ 检测到登录成功！（已通过页面真实状态校验）")
                        break

                    # 若仍在未登录态，定期重试点击登录入口
                    if check_count % 8 == 0 and (
                        signals.get("hasLoginBtn") or signals.get("hasLoginPrompt")
                    ):
                        await page.evaluate("""() => {
                            const isVisible = (el) => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                            const nodes = Array.from(document.querySelectorAll('button, a, span, div'));
                            const btn = nodes.find(el => isVisible(el) && (el.innerText || '').trim() === '登录');
                            if (btn) { btn.click(); return; }
                            const fallback = nodes.find(el => {
                                if (!isVisible(el)) return false;
                                const t = (el.innerText || '').trim();
                                return t === '登录/注册' || t.includes('扫码登录');
                            });
                            if (fallback) fallback.click();
                        }""")

                    # 每15秒显示一次状态
                    if check_count % 7 == 0:
                        print(f"   等待中... {check_count * 2}秒 | 当前URL: {current_url}")

                    # setup 模式不主动超时，避免用户来不及扫码
                    if check_count % 60 == 0:
                        print("   仍在等待扫码登录（可继续操作，不会自动关闭）")

                except Exception as e:
                    # 页面可能已关闭
                    print(f"\n⚠️  浏览器页面已关闭")
                    break

            if not login_success:
                print("\n❌ 未检测到有效登录状态，未覆盖保存登录态")
                try:
                    input("\n回车后关闭浏览器并结束 setup...")
                except EOFError:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass
                return

            # 保存登录态
            print("\n💾 正在保存登录态...")
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            try:
                storage_state = await context.storage_state()
                cookies = storage_state.get("cookies", [])
                xhs_cookies = [
                    c for c in cookies if "xiaohongshu" in c.get("domain", "")
                ]

                print(f"📊 总计 {len(cookies)} 个 cookies")
                print(f"   其中 {len(xhs_cookies)} 个来自小红书")

                if len(cookies) > 0:
                    with open(XIAOHONGSHU_AUTH_FILE, "w", encoding="utf-8") as f:
                        json.dump(storage_state, f, indent=2)

                    file_size = XIAOHONGSHU_AUTH_FILE.stat().st_size
                    print(f"\n✅ 登录态已保存！")
                    print(f"   文件: {XIAOHONGSHU_AUTH_FILE}")
                    print(f"   大小: {file_size} bytes")

                    print("\n🎉 登录态检测并保存成功！")
                else:
                    print("\n❌ 未检测到任何 cookies，保存失败")
                    print("   请确保已在小红书网页完成登录")

            except Exception as e:
                print(f"\n❌ 保存失败: {e}")

            try:
                input("\n回车后关闭浏览器并结束 setup...")
            except EOFError:
                pass

            # 关闭浏览器
            try:
                await browser.close()
                print("\n👋 浏览器已关闭，设置完成！")
            except:
                print("\n👋 浏览器已关闭")

    except KeyboardInterrupt:
        print("\n\n⚠️  被用户中断")
    except Exception as e:
        print(f"\n❌ 登录设置失败: {e}")
        import traceback

        traceback.print_exc()


def main():
    if len(sys.argv) < 2:
        print("=" * 60)
        print("URL Reader - 智能网页内容读取器")
        print("=" * 60)
        print("\n用法:")
        print("  python url_reader.py <url>              # 读取并显示")
        print("  python url_reader.py <url> --save       # 读取并保存")
        print("  python url_reader.py batch <链接或文件...> [--retry N]")
        print("  python url_reader.py setup-xhs          # 设置小红书登录态")
        print("  python url_reader.py migrate-md-names [平台]  # 迁移旧 content.md 命名")
        print("  python url_reader.py audit-xhs-format   # 巡检小红书笔记格式")
        print("  python url_reader.py repair-xhs-format  # 一键修复小红书笔记格式")
        print("  python url_reader.py export-xhs-proof [csv_path]  # 导出证据清单")
        print("\n示例:")
        print("  python url_reader.py https://mp.weixin.qq.com/s/xxxxx --save")
        print("  python url_reader.py batch links.txt --retry 1")
        print("  python url_reader.py migrate-md-names 小红书")
        print("  python url_reader.py repair-xhs-format")
        print("  python url_reader.py export-xhs-proof")
        print("\n保存目录:")
        print(f"  {DEFAULT_OUTPUT_DIR}")
        print("\n策略优先级:")
        print("  1. Firecrawl (需要 API Key)")
        print("  2. Jina Reader (免费)")
        print("  3. Playwright (需要登录态)")
        print("\n环境变量:")
        print(f"  FIRECRAWL_API_KEY: {'已设置' if FIRECRAWL_API_KEY else '未设置'}")
        print(f"  URL_READER_LICENSE_MODE: {get_license_mode()}")
        print(f"  微信登录态: {'已设置' if WECHAT_AUTH_FILE.exists() else '未设置'}")
        print(
            f"  小红书登录态: {'已设置' if XIAOHONGSHU_AUTH_FILE.exists() else '未设置'}"
        )
        return

    # 处理 setup-xhs 命令
    if sys.argv[1] == "setup-xhs":
        asyncio.run(setup_xiaohongshu_login())
        return

    if sys.argv[1] == "migrate-md-names":
        platform_name = sys.argv[2] if len(sys.argv) >= 3 else ""
        base_dir = Path(DEFAULT_OUTPUT_DIR)
        result = migrate_note_markdown_filenames(base_dir, platform_name=platform_name)
        print("✅ 文件名迁移完成")
        print(f"   重命名: {result['migrated']}")
        print(f"   删除旧 content.md: {result['removed_legacy']}")
        print(f"   跳过: {result['skipped']}")
        if result["errors"]:
            print("⚠️ 错误:")
            for err in result["errors"][:20]:
                print(f"   - {err}")
        return

    if sys.argv[1] == "dedupe-xhs":
        if len(sys.argv) < 4:
            print("用法: python url_reader.py dedupe-xhs <keep_dir_name> <note_id>")
            return
        keep_dir_name = sys.argv[2]
        target_note_id = sys.argv[3]
        base_platform_dir = Path(DEFAULT_OUTPUT_DIR) / "小红书"
        removed = dedupe_xhs_note_dirs(base_platform_dir, keep_dir_name, target_note_id)
        print(f"✅ 已保留: {keep_dir_name}")
        if removed:
            print("🧹 已删除重复目录:")
            for name in removed:
                print(f"  - {name}")
        else:
            print("ℹ️ 未发现重复目录")
        return

    if sys.argv[1] == "audit-xhs-format":
        base_platform_dir = Path(DEFAULT_OUTPUT_DIR) / "小红书"
        result = audit_and_repair_xhs_notes(base_platform_dir, fix=False)
        print("✅ 小红书笔记格式巡检完成")
        print(f"   总计: {result['total']}")
        print(f"   合规: {result['clean']}")
        print(f"   需修复: {len(result['issue_files'])}")
        if result["issue_files"]:
            print("\n问题文件:")
            for item in result["issue_files"][:30]:
                print(f"- {item['file']}")
                for issue in item.get("issues", []):
                    print(f"  - {issue}")
        if result["errors"]:
            print("\n⚠️ 巡检错误:")
            for err in result["errors"][:20]:
                print(f"  - {err}")
        return

    if sys.argv[1] == "repair-xhs-format":
        base_platform_dir = Path(DEFAULT_OUTPUT_DIR) / "小红书"
        result = audit_and_repair_xhs_notes(
            base_platform_dir,
            fix=True,
            preserve_personal_note=True,
        )
        print("✅ 小红书笔记格式修复完成")
        print(f"   总计: {result['total']}")
        print(f"   修复写回: {result['fixed']}")
        print(f"   当前合规: {result['clean']}")
        print(f"   剩余问题: {len(result['issue_files'])}")
        if result["issue_files"]:
            print("\n仍有问题的文件:")
            for item in result["issue_files"][:30]:
                print(f"- {item['file']}")
                for issue in item.get("issues", []):
                    print(f"  - {issue}")
        if result["errors"]:
            print("\n⚠️ 修复错误:")
            for err in result["errors"][:20]:
                print(f"  - {err}")
        return

    if sys.argv[1] == "export-xhs-proof":
        default_path = Path(DEFAULT_OUTPUT_DIR) / "小红书" / "_proof" / "xhs_proof_report.csv"
        output_csv = Path(sys.argv[2]) if len(sys.argv) >= 3 else default_path
        base_platform_dir = Path(DEFAULT_OUTPUT_DIR) / "小红书"
        result = export_xhs_proof_report(base_platform_dir, output_csv)
        if result.get("success"):
            print("✅ 小红书证据清单导出完成")
            print(f"   条目数: {result['count']}")
            print(f"   文件: {result['output']}")
            if result["errors"]:
                print("\n⚠️ 部分文件导出失败:")
                for err in result["errors"][:20]:
                    print(f"  - {err}")
        else:
            print("❌ 导出失败")
            for err in result.get("errors", []):
                print(f"  - {err}")
        return

    # 批量模式：支持链接/文件混合输入
    if sys.argv[1] == "batch":
        raw_args = sys.argv[2:]
        retry = 1
        sources = []

        i = 0
        while i < len(raw_args):
            arg = raw_args[i]
            if arg == "--retry":
                if i + 1 < len(raw_args):
                    try:
                        retry = max(0, int(raw_args[i + 1]))
                    except Exception:
                        retry = 1
                    i += 2
                    continue
            sources.append(arg)
            i += 1

        if not sources:
            print("❌ batch 模式需要提供至少一个链接或文件路径")
            print("   示例: python url_reader.py batch links.txt --retry 1")
            return

        print(f"\n{'=' * 60}")
        print("批量模式启动")
        print(f"{'=' * 60}")
        print(f"输入源数量: {len(sources)}")
        print(f"失败重试次数: {retry}\n")

        result = run_batch_read_and_save(sources, retry=retry, verbose=True)
        print(f"\n{'=' * 60}")
        print("批量处理结果")
        print(f"{'=' * 60}")
        print(f"总数: {result.get('total', 0)}")
        print(f"成功: {result.get('succeeded', 0)}")
        print(f"失败: {result.get('failed', 0)}")

        failed_items = [item for item in result.get("items", []) if not item.get("success")]
        if failed_items:
            print("\n失败链接:")
            for item in failed_items:
                print(f"- {item.get('url')}")
                for err in item.get("errors", []):
                    print(f"  - {err}")
        return

    url = sys.argv[1]
    save_mode = "--save" in sys.argv

    print(f"\n{'=' * 60}")
    print(f"正在读取: {url}")
    print(f"{'=' * 60}\n")

    if save_mode:
        result = read_and_save(url)
        if result.get("success") and result.get("save"):
            print(f"\n{'=' * 60}")
            print("✅ 读取并保存成功")
            print(f"{'=' * 60}")
    else:
        result = read_url(url)
        output = format_output(result, url)
        print(f"\n{'=' * 60}")
        print("读取结果")
        print(f"{'=' * 60}\n")
        print(output)


if __name__ == "__main__":
    main()

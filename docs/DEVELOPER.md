# Developer Guide

面向开发者与进阶使用者的完整文档（安装、架构、命令、流程、质量治理）。

## 项目定位

- 输入 URL，自动识别平台并读取内容
- 小红书场景重点优化：结构化提取 + Obsidian 固化模板
- 支持批量处理、格式巡检修复、归属取证导出

## 技术架构（概览）

```text
用户输入 URL
     ↓
平台识别（domain 识别）
     ↓
策略选择（Firecrawl → Jina → Playwright）
     ↓
结构化提取（标题/正文/图片/互动/评论/ID）
     ↓
规范化（标题/正文清洗/模板生成/图谱双链）
     ↓
保存到 Obsidian（目录命名固化 + 图片下载）
     ↓
巡检/修复/证据导出
```

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 环境变量

参考 `.env.example`：

- `FIRECRAWL_API_KEY`：可选，非小红书站点增强读取
- `URL_READER_OUTPUT_DIR`：可选，覆盖默认 Obsidian 输出目录
- `URL_READER_LICENSE_MODE`：可选，`commercial` 时会在生成笔记中写入商业标记
- `BRIDGE_TOKEN`：可选，`scripts/chat_bridge.py` 的 HTTP 鉴权 token
- `OPENCODE_MODEL`：可选，聊天桥接智能路由模型（默认：`opencode/minimax-m2.5-free`）
- `OPENCODE_BIN`：可选，OpenCode 可执行路径（默认：`opencode`）

## 小红书标准流程（固定）

### 首次设置登录态

```bash
./.venv/bin/python scripts/url_reader.py setup-xhs
```

说明：
- 会打开浏览器并优先触发首页登录按钮（扫码弹窗）
- 检测到真实登录状态后自动保存登录态到 `data/xiaohongshu_auth.json`
- 后续运行可复用登录态（过期后再执行一次 setup）

### 单篇生成

```bash
./.venv/bin/python scripts/url_reader.py "<小红书链接>" --save
```

### 批量生成

```bash
./.venv/bin/python scripts/url_reader.py batch links.txt --retry 1
```

## 聊天桥接（飞书/微信等）

新增：`scripts/chat_bridge.py` + `scripts/ai_enricher.py`

用途：
- 接收聊天消息（含 URL）
- 通过 OpenCode 免费模型做轻量“入库意图 + 标签建议”
- 调用现有读取与保存流程，直接落地 Obsidian

### 启动桥接服务

```bash
export BRIDGE_TOKEN="your-bridge-token"  # 可选
export OPENCODE_MODEL="opencode/minimax-m2.5-free"  # 可选

./.venv/bin/python scripts/chat_bridge.py serve --host 127.0.0.1 --port 8765
```

### HTTP 接口

- `GET /health`：健康检查
- `POST /ingest`：消息入库

请求示例：

```bash
curl -X POST http://127.0.0.1:8765/ingest \
  -H 'Content-Type: application/json' \
  -H 'x-bridge-token: your-bridge-token' \
  -d '{
    "source": "feishu",
    "sender": "boss",
    "text": "帮我存这个链接 https://www.xiaohongshu.com/explore/xxxx"
  }'
```

### CLI 直调

```bash
./.venv/bin/python scripts/chat_bridge.py ingest "帮我存这个链接 https://www.xiaohongshu.com/explore/xxxx" --source cli
```

## 输出规范（已固化）

### 目录与主文件命名

- 目录名：`YYYY-MM-DD_紧凑短标题`
- 主文件名：与目录同名（不再统一为 `content.md`）
- 同 `note_id` 自动复用同一目录，避免重复分叉

### 笔记结构

1. YAML Frontmatter（含平台数据 + 图谱 ID + 生成器指纹）
2. 标题与元信息
3. 正文内容
4. 图片区
5. 标签区
6. 高赞评论区（具体赞数）
7. 个人笔记区（核心概念 / 对象分级 / 关键词索引）

### 正文清洗规则

- 去掉 `[话题]` / `［话题］`
- 去掉正文中的纯 hashtag 行（如 `#xx# #yy# ...`）
- 去掉误入正文的分隔线（`---` / `***` / `___`）
- 去掉残留占位符字符（如 `￼`）

## 个人笔记生成（领域化）

会根据标题 / 正文 / 标签自动识别主题域，生成更具体的“个人笔记 / 对象分级”：

- `finance`：金融投资 / 公司研究
- `creator_method`：赛博PM方法论 / 内容转译表达
- `ai_ops`：AI自动化运营 / 技能编排
- `osint_product`：OSINT / 情报产品
- `social`：社交 / 拜年 / 人脉沟通
- `ai_product`：通用 AI 工具与产品化表达

## 质量治理命令

### 巡检

```bash
./.venv/bin/python scripts/url_reader.py audit-xhs-format
```

检查项包括：
- 是否缺少关键分区
- 正文是否混入纯话题标签行
- 是否遗留 `content.md`
- 是否缺少归属取证字段（`generator` / `fingerprint_id` 等）

### 修复

```bash
./.venv/bin/python scripts/url_reader.py repair-xhs-format
```

特点：
- 不重新抓取网页
- 离线重建 markdown
- 保留已有深度“个人笔记”内容（避免被模板覆盖）

## 归属取证与证据导出

### 笔记内嵌字段

每篇笔记会写入：
- `generator`
- `generator_version`
- `generator_repo`
- `license_mode`
- `fingerprint_id`
- `provenance_sentinel`

文末还会写入隐藏 trace 注释：`XOP-Trace`

### 导出证据清单

```bash
./.venv/bin/python scripts/url_reader.py export-xhs-proof
```

默认输出：
- `小红书/_proof/xhs_proof_report.csv`

CSV 包含：
- 文件路径
- 标题 / URL / 各类 ID
- `fingerprint_id`
- `license_mode`
- `file_sha256`

详细流程见：`IP_ENFORCEMENT.md`

## 其他维护命令

```bash
# 历史命名迁移（content.md -> 目录同名 .md）
./.venv/bin/python scripts/url_reader.py migrate-md-names 小红书

# 删除同 note_id 重复目录（保留一个）
./.venv/bin/python scripts/url_reader.py dedupe-xhs "<保留目录名>" <note_id>
```

## 开发与测试

```bash
python3 -m py_compile scripts/url_reader.py scripts/ai_enricher.py scripts/chat_bridge.py
./.venv/bin/python -m unittest tests/test_format_rules.py tests/test_chat_bridge.py
```

CI（GitHub Actions）建议至少运行：
- `py_compile`
- `tests/test_format_rules.py`
- `tests/test_chat_bridge.py`

## 开发调试脚本（非正式入口）

- `scripts/debug/debug_selectors.py`：调试小红书页面选择器
- `examples/test_xhs.py`：小红书抓取烟雾测试示例

## License / 商业化

- 社区版：`AGPL-3.0-or-later`
- 商业版：见 `COMMERCIAL_LICENSE.md`
- 双授权说明：`LICENSING.md`
- 商标政策：`TRADEMARK.md`
- 上游归属：`NOTICE`、`THIRD_PARTY_LICENSES.md`

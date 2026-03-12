# xhs-obsidian-pipeline

不再让收藏夹吃灰：把小红书链接一键沉淀成可复用、可连接、可长期积累的 Obsidian 知识卡片（含高赞评论、深度个人笔记、对象分级、关键词双链）。

## 为什么做这个

很多人收藏了很多小红书内容，但最后都停留在“看过、点赞、收藏”，价值没有真正进入自己的知识系统。

这个项目把“小红书内容消费”变成“可复用知识生产”流程：

- 输入链接
- 自动提取正文 / 图片 / 互动数据 / 高赞评论
- 自动生成统一笔记结构（你确认过的高质量模板）
- 落到 Obsidian，进入关系图谱与长期沉淀

## 核心能力

- 小红书结构化提取：正文、图片、互动数据、高赞评论、`note_id` / `author_id` / `xiaohongshu_id`
- Obsidian 笔记固化模板：正文 / 图片 / 标签 / 高赞评论 / 个人笔记 / 对象分级 / 关键词索引
- 领域化“个人笔记”生成：金融投资 / 赛博PM方法论 / AI自动化运营 / OSINT / 社交
- 稳定更新不分叉：按 `note_id` 复用目录、短标题固化、历史深度内容保护
- 质量治理：`audit-xhs-format` / `repair-xhs-format` 批量巡检与修复
- 归属取证：`fingerprint_id`、`XOP-Trace`、CSV 证据导出（含文件 SHA256）

## 适用人群

- Obsidian 用户（知识管理 / 卡片沉淀）
- 内容研究者（拆解爆文结构与评论反馈）
- 产品经理 / 运营 / 自媒体从业者
- 想把“收藏夹”变成“知识库”的个人用户

## 快速开始（3 分钟）

### 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置输出目录（可选）

```bash
export URL_READER_OUTPUT_DIR="/你的Obsidian/🌐 网络收藏"
```

### 3. 首次扫码保存小红书登录态

```bash
./.venv/bin/python scripts/url_reader.py setup-xhs
```

### 4. 输入链接生成笔记

```bash
./.venv/bin/python scripts/url_reader.py "https://www.xiaohongshu.com/explore/xxxx" --save
```

## 常用命令

```bash
# 单篇生成
./.venv/bin/python scripts/url_reader.py "<小红书链接>" --save

# 批量生成（支持 links.txt）
./.venv/bin/python scripts/url_reader.py batch links.txt --retry 1

# 巡检 / 修复历史笔记格式（不重新抓取网页）
./.venv/bin/python scripts/url_reader.py audit-xhs-format
./.venv/bin/python scripts/url_reader.py repair-xhs-format

# 导出归属证据清单（指纹 + SHA256）
./.venv/bin/python scripts/url_reader.py export-xhs-proof
```

## 聊天桥接（微信/飞书）+ OpenCode 免费智能

> 不强制做 OpenClaw skill 插件。可直接在仓库内跑桥接服务，把聊天消息里的链接自动转成笔记。

### 1) 启动桥接服务

```bash
# 可选：桥接鉴权 token
export BRIDGE_TOKEN="your-bridge-token"

# 可选：指定 OpenCode 免费模型（默认已是 minimax free）
export OPENCODE_MODEL="opencode/minimax-m2.5-free"

./.venv/bin/python scripts/chat_bridge.py serve --host 127.0.0.1 --port 8765
```

### 2) （可选）启动来源监听器（微信MVP / 飞书）

```bash
# 微信监听MVP（最小闭环）
./.venv/bin/python scripts/inbound_listener.py --source wechat --host 127.0.0.1 --port 8877

# 飞书监听（第二阶段，复用同一监听器）
./.venv/bin/python scripts/inbound_listener.py --source feishu --host 127.0.0.1 --port 8878
```

### 2.1) 微信个人号直连（文件传输助手）

如果你要直接监听个人微信消息（如「文件传输助手」），可启动 UOS 桥接器，把微信文本消息自动转发到 `/event`：

```bash
# 终端 A：先启动来源监听器
./.venv/bin/python scripts/inbound_listener.py --source wechat --host 127.0.0.1 --port 8877

# 终端 B：启动微信桥接（默认仅转发 filehelper）
./.venv/bin/python scripts/wechat_uos_bridge.py \
  --event-url http://127.0.0.1:8877/event \
  --listen-mode filehelper \
  --cmd-qr
```

说明：
- `--listen-mode filehelper`：只转发文件传输助手会话
- `--listen-mode all`：转发所有文本会话（群/私聊）
- 若配置了 `LISTENER_TOKEN`，桥接器会自动带 `x-listener-token`
- `--max-retries`：转发失败时重试次数（默认 2）
- `--max-login-retries`：登录异常重试次数（默认 `-1`，持续重试）

如果 UOS 登录反复出现“确认后超时”，可切换数据库监听桥接（不走 Web 登录）：

```bash
# 1) 准备密钥（需要 sudo，一次性）
cd /tmp/wechat-decrypt-mac
source /Users/baijinde/code/url-reader/.venv/bin/activate
sudo /Users/baijinde/code/url-reader/.venv/bin/python find_all_keys.py

# 2) 启动来源监听器
cd /Users/baijinde/code/url-reader
./.venv/bin/python scripts/inbound_listener.py --source wechat --host 127.0.0.1 --port 8877

# 3) 启动数据库桥接（只转发文件传输助手）
./.venv/bin/python scripts/wechat_db_bridge.py \
  --monitor-script /tmp/wechat-decrypt-mac/monitor.py \
  --event-url http://127.0.0.1:8877/event
```

### 2.2) 微信网关转发（推荐兜底）

新增：`scripts/wechat_gateway_bridge.py`

用途：把第三方微信网关回调（如 Gewechat/Gewechaty）统一转换后转发到 `POST /event`。

```bash
# 终端 A：来源监听器
./.venv/bin/python scripts/inbound_listener.py --source wechat --host 127.0.0.1 --port 8877

# 终端 B：网关回调桥接（默认只转发 filehelper）
./.venv/bin/python scripts/wechat_gateway_bridge.py \
  --host 127.0.0.1 \
  --port 8899 \
  --route /wechat/callback \
  --target-url http://127.0.0.1:8877/event \
  --listen-mode filehelper
```

把你的微信网关回调 URL 配置为：
- `http://127.0.0.1:8899/wechat/callback`

可用脚本自动设置 GeWe 回调（需要 GeWe 后台 token）：

```bash
export GEWE_TOKEN='你的_gewe_token'
./.venv/bin/python scripts/gewe_set_callback.py \
  --base-api http://api.geweapi.com/gewe/v2/api \
  --callback-url http://127.0.0.1:8899/wechat/callback
```

说明：
- `--listen-mode filehelper`：只收文件传输助手
- `--listen-mode all`：收所有会话
- `--timeout`：转发到 `/event` 的超时（默认 120 秒）
- `--gateway-token`：要求网关携带 `x-gateway-token`/`token`（建议开启）

然后把上游消息转成 HTTP POST 到 `/event`：

```bash
curl -X POST http://127.0.0.1:8877/event \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "这个链接帮我沉淀成笔记 https://www.xiaohongshu.com/explore/xxxx",
    "sender": "boss"
  }'
```

### 3) 发送聊天消息到桥接端点

```bash
curl -X POST http://127.0.0.1:8765/ingest \
  -H 'Content-Type: application/json' \
  -H 'x-bridge-token: your-bridge-token' \
  -d '{
    "source": "feishu",
    "sender": "boss",
    "text": "这个链接帮我沉淀成笔记 https://www.xiaohongshu.com/explore/xxxx"
  }'
```

桥接行为：
- 自动抽取消息里的 URL
- 用 OpenCode 免费模型做轻量“是否入库/标签建议”
- 调用现有 url_reader 流程落盘到 Obsidian

### 3) 本地快速调试（不走 HTTP）

```bash
./.venv/bin/python scripts/chat_bridge.py ingest "帮我存这个 https://www.xiaohongshu.com/explore/xxxx" --source cli
```

## 输出效果（结构）

每条小红书链接会生成一个独立目录：

```text
🌐 网络收藏/
└── 小红书/
    └── 2026-02-19_银行人眼里的美的集团/
        ├── 2026-02-19_银行人眼里的美的集团.md
        └── images/
            ├── img_01.webp
            ├── img_02.webp
            └── ...
```

笔记内容结构固定为：

- 笔记元数据（含互动数据、ID、生成器指纹）
- 正文内容
- 笔记图片
- 标签
- 高赞评论（带具体赞数）
- 个人笔记（核心概念 / 对象分级 / 关键词索引）

## 进阶能力（长期使用很关键）

### 格式治理

- `audit-xhs-format`：巡检历史笔记是否存在格式回退（例如正文混入话题标签）
- `repair-xhs-format`：一键离线修复，不需要重新抓取网页

### 归属取证（开源 / 商业版都可用）

每篇笔记会自动写入：

- `generator`
- `generator_version`
- `license_mode`
- `fingerprint_id`
- `provenance_sentinel` (`XOP-Trace`)

并可导出证据清单：

```bash
./.venv/bin/python scripts/url_reader.py export-xhs-proof
```

## 文档导航

- 开发者文档（安装、架构、完整命令、详细流程）：`docs/DEVELOPER.md`
- 取证与维权流程：`IP_ENFORCEMENT.md`
- 双授权说明：`LICENSING.md`
- 商业授权模板：`COMMERCIAL_LICENSE.md`
- 商标政策：`TRADEMARK.md`

## 致谢

感谢上游项目与原作者提供的初始能力与结构基础：

- `yhslgg-arch/url-reader`（MIT）
- 原作者：`yhslgg` 及贡献者

本项目在此基础上，围绕小红书 -> Obsidian 的结构化沉淀、格式治理、归属取证与双授权进行了大量扩展。

## 商业版 / 私有版（规划中）

当前仓库聚焦开源单机引擎（高质量抓取 + 知识卡片生产 + 格式治理）。

后续商业版 / 私有版将围绕：

- 多用户与权限体系
- 订阅与配额管理
- 云端任务队列与自动化调度
- 团队协作与审计日志
- 企业私有化部署

## Roadmap（后续能力规划）

这条产品路线会沿着一条主线推进：

`链接采集 -> 结构化笔记 -> 知识库 -> 灵感沉淀 -> 产品化执行`

### 1) 分享即生成（自动入口）

- 微信 / 飞书收到分享链接后，自动生成笔记
- 飞书优先（机器人 / Webhook / 应用接入）
- 微信场景会优先选择合规、可长期维护的接入方式

### 2) 多平台支持（统一提取层）

- 在小红书能力基础上扩展到更多平台（如微信公众号、知乎、B站、微博等）
- 用统一结构化字段输出（标题 / 正文 / 图片 / 作者 / 互动 / 评论 / 平台ID）
- 让“上层模板与知识库能力”不依赖单一平台

### 3) 多笔记软件打通（统一导出层）

- Obsidian（已支持，持续强化）
- Notion（计划中）
- 后续可扩展更多知识库/文档工具

目标是：同一份结构化数据可输出到不同笔记系统，而不是为每个平台重复造轮子。

### 4) 从笔记与关键词构建知识库

- 基于关键词、主题、对象、时间维度建立索引
- 构建关系图谱（概念 / 场景 / 方法 / 人群 / 工具）
- 提供检索、聚类、主题追踪能力
- 让“收藏内容”升级为“可查询、可连接、可迭代”的个人知识资产

### 5) 从知识库沉淀灵感，并转化成产品

- 从高频主题、重复痛点、评论共鸣中抽取灵感候选
- 生成机会卡（用户 / 痛点 / 场景 / 证据 / 可执行动作）
- 把灵感推进到产品假设、MVP、验证、复盘的完整闭环
- 最终目标：帮助个人把内容洞察沉淀为自己的方法论、产品与业务

### 6) 开源版与商业版边界（长期）

- 开源版：本地引擎、结构化提取、标准模板、Obsidian 导出、巡检修复
- 商业版 / 私有版：自动入口、多平台管理、Notion/团队协作、知识洞察面板、配额与权限体系

## License

本项目采用双授权：

1. `AGPL-3.0-or-later`（社区版 / 开源使用）
2. 商业授权（闭源 / 商业使用）

- 社区许可证全文：`LICENSE`
- 双授权说明：`LICENSING.md`
- 商业授权模板：`COMMERCIAL_LICENSE.md`
- 上游与第三方归属：`NOTICE`、`THIRD_PARTY_LICENSES.md`

## 免责声明

使用者需自行遵守目标平台条款、当地法律法规与数据合规要求。本项目仅用于个人知识管理、研究与合法授权场景。

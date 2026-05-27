---
name: feishu-bot
description: "飞书集成插件 - 让 OpenCode AI 连接飞书，实现消息收发、通知推送、任务处理。基于飞书官方 SDK（lark-oapi）WebSocket 长连接，无需公网 IP，仅需出网能力。"
---

# 飞书机器人插件 — WebSocket 长连接模式

让 AI 能够通过飞书与用户交互：**收发消息、发送通知、处理任务请求**，就像在终端中对话一样自然。

## 核心优势

🔌 **WebSocket 长连接** — 使用飞书官方 SDK 建立全双工 WebSocket 通道
🌐 **无需公网 IP** — 仅需服务器有出网能力即可，本地开发也能用
🔒 **加密传输** — SDK 内置加密和鉴权，无需额外处理验签解密
♻️ **自动重连** — SDK 内置心跳保活和断线重连机制

## 架构概览

```
┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  飞书客户端    │ ──→ │  WebSocket 长连接  │ ──→ │  feishu_bot       │
│  (用户/群聊)   │ ←── │  (lark-oapi)      │ ←── │  (on_message)     │
└──────────────┘     └──────────────────┘     └────────┬──────────┘
                                                        │ 写入
                                                  ┌──────┴──────────┐
                                                  │ /tmp/feishu-    │
                                                  │ inbox.json      │ ← 30s 时效过滤
                                                  └──────┬──────────┘
                                                         │ 轮询
                                                  ┌──────┴──────────┐
                                                  │  watch_feishu   │
                                                  │  (poll_messages) │
                                                  └──────┬──────────┘
                                                         │ opencode run --attach
                                                  ┌──────┴──────────┐
                                                  │  OpenCode AI    │
                                                  │  (DB 写回复)     │
                                                  └──────┬──────────┘
                                                         │ 轮询 DB (time_updated)
                                                  ┌──────┴──────────┐
                                                  │  watch_feishu   │
                                                  │  (稳定检测 5s)   │
                                                  └──────┬──────────┘
                                                         │ feishu_client.send_text
                                                  ┌──────┴──────────┐
                                                  │  用户收到回复     │
                                                  └─────────────────┘
```
- **feishu_bot** — WebSocket 长连接接收飞书消息，写入 inbox 队列
- **inbox 文件** — `/tmp/feishu-inbox.json`，每条消息带时间戳
- **watch_feishu** — 轮询 inbox，30 秒时效过滤，转发到 AI，轮询回复
- **稳定检测** — 轮询 AI 回复时按 `time_updated` 等待 5 秒无变化才返回
- **防循环** — `BOT_OPEN_ID` 过滤机器人自己的消息

## 核心能力

### 1. 发送消息到飞书
- **文本消息** — 向用户或群聊发送纯文本
- **富文本消息** — 支持格式化的富文本内容
- **卡片消息** — 交互式消息卡片（按钮、Markdown）
- **图片消息** — 发送图片到对话

### 2. 接收并处理飞书消息（长连接）
- 通过 WebSocket 长连接实时接收飞书事件
- 自动解析消息内容（文本、图片、@提及等）
- 消息进入队列供 AI 拉取处理

### 3. 通知推送
- AI 完成任务后主动发送通知到指定用户或群聊
- 支持异步通知（任务完成后推送结果）

### 4. 飞书信息查询
- 查询机器人信息
- 查询用户信息（需对应权限）

## 快速开始

### 前置条件

1. 在 [飞书开发者后台](https://open.feishu.cn/app) 创建**企业自建应用**
2. 获取应用的 **App ID** 和 **App Secret**
3. 在应用中启用 **机器人** 能力
4. 在「事件与回调」中选择 **使用长连接接收事件** 模式
5. 添加 **im:message** 等必要权限
6. 发布应用并授权给组织

### 安装与运行

```bash
SKILL_DIR=~/.config/opencode/skills/feishu-bot

# 1. 一键安装（创建 venv + 安装依赖）
bash "$SKILL_DIR/setup.sh"

# 2. 配置飞书凭证
#    编辑 .env 文件，填入 App ID 和 App Secret
nano "$SKILL_DIR/.env"

# 3. 一键启动（推荐）
bash "$SKILL_DIR/start.sh"
```

一键启动会同时拉起 `opencode web`、`feishu_bot`（WebSocket 网关）、`watch_feishu`（消息监控），关闭终端后仍可运行。

或分别启动：
```bash
# 启动 opencode Web 服务（AI 处理引擎）
opencode web --port 4096

# 启动飞书消息接收网关（WebSocket 长连接）
"$SKILL_DIR/venv/bin/python" "$SKILL_DIR/feishu_bot.py"

# 启动消息监控（自动转发飞书消息到 AI 并回复）
"$SKILL_DIR/venv/bin/python" "$SKILL_DIR/watch_feishu.py"
```

看到 `connected to wss://...` 即表示连接成功。

### 测试消息发送

```bash
SKILL_DIR=~/.config/opencode/skills/feishu-bot

# 查看机器人状态
"$SKILL_DIR/venv/bin/python" "$SKILL_DIR/feishu_client.py" --action status

# 发送文本消息（需要先获取接收者的 open_id）
"$SKILL_DIR/venv/bin/python" "$SKILL_DIR/feishu_client.py" \
  --action send --to "ou_xxx" --type text --content "你好世界"
```

## AI 使用指南

当本技能加载后，AI 可以通过以下方式操作飞书：

### 发送消息

使用 `FeishuClient` API 客户端发送消息：

```python
from feishu_client import FeishuClient

client = FeishuClient()
result = client.send_text(
    receive_id="ou_xxx",  # 或 chat_id
    content="你好，任务已完成！"
)
```

### 查看待处理消息

AI 可以拉取飞书消息队列：

```python
from feishu_bot import get_pending_messages

messages = get_pending_messages(limit=5)
for msg in messages:
    print(f"{msg['sender_id']}: {msg['text']}")
```

### 命令行快捷操作

```bash
# 查看机器人状态
python feishu_client.py --action status

# 发送文本消息
python feishu_client.py --action send --to ou_xxx --type text --content "你好"

# 发送富文本消息
python feishu_client.py --action send --to ou_xxx --type rich_text \
  --title "通知" --content "第一行\n第二行"

# 发送卡片消息
python feishu_client.py --action send --to ou_xxx --type card \
  --title "任务完成" --content "任务已完成\n点击下方按钮查看"
```

## 工作原理

### WebSocket 长连接流程

```
飞书开放平台                  feishu_bot.py
     │                            │
     │  ←── 请求 WS 地址 ────    │
     │  ───→ 返回 wss://... ──→  │
     │  ←── 建立加密连接 ────    │
     │  ──→ 事件推送(加密) ──→  │  ← 自动解密
     │  ──→ 心跳 Ping ──────→  │  ← 自动回复 Pong
     │  ──→ 事件推送 ───────→  │  → 分发到处理器
     │                            │  → API 客户端发送回复
     │  ←── API 调用 ────────    │
```

### 发送消息流程

```
AI 决定发送消息
    │
    ├─ 调用 feishu_client.py 发送消息
    │    ├─ 自动获取 tenant_access_token（缓存+自动刷新）
    │    ├─ 构造消息体
    │    └─ 调用飞书 API 发送
    │
    └─ 返回发送结果
```

### 接收消息流程

```
飞书 WS 长连接推送事件
    │
    ├─ SDK 自动解密
    ├─ 分发到 on_message
    ├─ 解析消息（发送者、内容、类型等）
    ├─ BOT_OPEN_ID 过滤（自己的消息跳过）
    ├─ 加入 inbox 队列（带时间戳）
    └─ watch_feishu 轮询
         ├─ 30 秒时效过滤（>30s 的丢弃）
         ├─ opencode run --attach 发送给 AI
         ├─ 轮询 SQLite DB 等待回复
         │   └─ 稳定检测（按 time_updated 等 5s）
         └─ feishu_client 发送回复到飞书
```

## 配置参考

### .env 配置项

| 配置项 | 说明 | 是否必填 |
|--------|------|----------|
| `FEISHU_APP_ID` | 飞书应用的 App ID | **是** |
| `FEISHU_APP_SECRET` | 飞书应用的 App Secret | **是** |
| `AI_RESPONSE_ENABLED` | 是否开启自动回复确认（默认 true） | 否 |
| `BOT_OPEN_ID` | 机器人自己的 open_id，用于过滤自己的消息防止循环 | 启动日志中可见 |

### 需要的飞书权限

在飞书开发者后台 → 权限管理中添加：

| 权限 | 说明 |
|------|------|
| `im:message` | 发送消息 |
| `im:message:send_as_bot` | 以 bot 身份发送消息 |
| `im:message:readonly` | 读取消息（接收事件需要） |
| `im:chat:readonly` | 读取群组信息 |

### 需要订阅的事件

在飞书开发者后台 → 事件与回调 → 添加事件：

| 事件 | 说明 |
|------|------|
| `im.message.receive_v1` | 接收消息（必选） |
| `bot.p2p_chat_entered` | 用户首次进入机器人会话（推荐） |

## 注意事项

1. **只需要出网能力** — 服务器能访问外网即可，不需要公网 IP 或端口映射
2. **长连接模式仅支持企业自建应用** — 商店应用需要使用 Webhook 模式
3. **自动重连** — 网络中断后 SDK 会自动重连，无需手动干预
4. **每个应用最多 50 个连接** — 同一时间最多 50 个 WS 客户端连接
5. **消息频率限制** — 飞书 API 有 QPS 限制，大量消息建议排队发送
6. **3 秒处理超时** — 事件处理器需在 3 秒内完成，否则触发重推

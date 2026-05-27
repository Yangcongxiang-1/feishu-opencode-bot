# 飞书 OpenCode Bot 🤖

> 基于飞书 WebSocket 长连接的 AI 机器人 —— 接收飞书消息 → OpenCode AI 处理 → 自动回复

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 目录

- [概述](#概述)
- [架构](#架构)
- [核心功能](#核心功能)
- [快速开始](#快速开始)
- [文件说明](#文件说明)
- [配置参考](#配置参考)
- [工作原理](#工作原理)
- [常见问题](#常见问题)

---

## 概述

**飞书 OpenCode Bot** 让 AI 能够通过飞书与用户交互。用户在飞书中给机器人发消息，消息通过 WebSocket 长连接实时推送，由 OpenCode AI 处理，并自动回复到飞书。

### 适用场景

- 🤖 **AI 助手** — 在飞书里直接和 AI 对话
- 🔔 **通知推送** — AI 完成任务后主动通知用户
- 📋 **任务处理** — 通过飞书提交任务，AI 自动处理并返回结果

### 技术特点

- 🔌 **WebSocket 长连接** — 无需公网 IP，仅需出网能力
- 🔒 **加密传输** — 飞书官方 SDK 内置加密和鉴权
- ♻️ **自动重连** — SDK 内置心跳保活和断线重连
- 🏃 **后台运行** — 关闭终端后仍可运行
- 🧹 **防循环** — 自动过滤机器人自己的消息，避免死循环
- ⏱ **时效过滤** — 只处理 30 秒内的消息，防止旧消息重放

---

## 架构

```
┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  飞书客户端    │ ──→ │  WebSocket 长连接  │ ──→ │  feishu_bot       │
│  (用户/群聊)   │ ←── │  (lark-oapi)      │ ←── │  (on_message)     │
└──────────────┘     └──────────────────┘     └────────┬──────────┘
                                                        │ 写入 inbox
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
                                                  │  (SQLite 写回复)  │
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

### 核心流程

1. **feishu_bot** — WebSocket 长连接网关，接收飞书消息，写入 inbox 队列
2. **inbox 文件** — `/tmp/feishu-inbox.json`，每条消息带时间戳
3. **watch_feishu** — 轮询 inbox，30 秒时效过滤 → `opencode run --attach` 发送给 AI
4. **AI 处理** — OpenCode AI 处理消息，回复写入 SQLite 数据库
5. **稳定检测** — watch_feishu 轮询数据库，按 `time_updated` 等待 5 秒无变化才返回
6. **回复发送** — feishu_client 调用飞书 API 发送回复

### 防循环机制

- `BOT_OPEN_ID` 过滤：机器人自己发出的消息不会被写入 inbox
- 30 秒时效过滤：超过 30 秒的旧消息自动丢弃
- 消息 ID 去重：已处理的消息 ID 不会重复处理

---

## 核心功能

### 1. 消息收发

| 功能 | 说明 |
|------|------|
| 文本消息 | 支持发送和接收纯文本消息 |
| 自动回复 | AI 自动处理消息并回复 |
| 私聊/群聊 | 支持私聊和群聊场景 |

### 2. 多会话管理

- 所有飞书消息汇集到同一个 AI 会话
- 保持对话上下文连续性
- 支持通过 Web UI 查看完整对话历史

### 3. 后台运行

- 所有进程通过 `nohup` 在后台运行
- 关闭终端后仍然正常工作
- 一键启动脚本，重启后一条命令恢复

### 4. 通知推送

- AI 完成任务后主动发送通知到飞书
- 支持异步通知推送

---

## 快速开始

### 前置条件

- Python 3.10+
- [OpenCode](https://github.com/opencode-ai/opencode) 已安装
- 飞书**企业自建应用**（已启用机器人能力）

### 1. 飞书开发者后台配置

1. 在 [飞书开发者后台](https://open.feishu.cn/app) 创建**企业自建应用**
2. 获取 **App ID** 和 **App Secret**
3. 启用 **机器人** 能力
4. 在「事件与回调」中选择 **使用长连接接收事件** 模式
5. 添加事件：`im.message.receive_v1`
6. 添加权限：`im:message`、`im:message:send_as_bot`、`im:message:readonly`
7. 发布应用并授权给组织

### 2. 安装

```bash
# 进入项目目录
cd feishu-opencode-bot

# 一键安装（创建虚拟环境 + 安装依赖）
bash setup.sh

# 配置飞书凭证
# 编辑 .env 文件，填入 App ID 和 App Secret
nano .env
```

### 3. 启动

```bash
# 一键启动（推荐）
bash start.sh
```

启动后看到 `connected to wss://...` 表示连接成功。

### 4. 测试

在飞书中给机器人发送一条消息，AI 会自动回复。

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `feishu_bot.py` | WebSocket 长连接网关，接收飞书消息并写入队列 |
| `watch_feishu.py` | 消息监控，轮询队列转发 AI 并取回回复（核心逻辑） |
| `feishu_client.py` | 飞书 API 客户端，封装消息发送、文件上传等操作 |
| `feishu_server_webhook.py` | Webhook 模式服务器（备选，长连接不可用时） |
| `config.py` | 配置管理，从环境变量或 .env 加载 |
| `SKILL.md` | OpenCode 技能定义，加载后 AI 自动获得飞书能力 |
| `start.sh` | 一键启动脚本（opencode web + feishu_bot + watch_feishu） |
| `setup.sh` | 首次安装脚本（创建 venv + 安装依赖） |
| `requirements.txt` | Python 依赖（lark-oapi） |
| `keep_alive.sh` | 进程保活脚本（可选） |
| `.env.example` | 飞书凭证配置模板 |

---

## 配置参考

### .env 配置项

| 配置项 | 说明 | 必填 |
|--------|------|------|
| `FEISHU_APP_ID` | 飞书应用的 App ID | **是** |
| `FEISHU_APP_SECRET` | 飞书应用的 App Secret | **是** |
| `AI_RESPONSE_ENABLED` | 是否开启自动回复（默认 true） | 否 |
| `BOT_OPEN_ID` | 机器人自己的 open_id，用于过滤自己的消息防循环 | 启动日志可见 |

### 运行时参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `POLL_INTERVAL` | 1.5 秒 | inbox 队列轮询间隔 |
| `STABLE_WAIT` | 5 秒 | AI 回复稳定检测等待时间 |
| `MSG_FRESH_SEC` | 30 秒 | 消息时效过滤阈值 |
| `OPENCODE_PORT` | 4096 | OpenCode Web 服务端口 |

---

## 工作原理

### WebSocket 长连接

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

### 消息处理时序

```
用户发送消息
    │
    ├─ [0s] feishu_bot 接收 → 写入 inbox
    │
    ├─ [~1.5s] watch_feishu 轮询到消息
    │    ├─ 检查时效（>30s? 丢弃）
    │    └─ opencode run --attach 发送给 AI
    │
    ├─ [~3s] AI 开始处理
    │    ├─ 保持全部 skill 能力
    │    └─ 回复写入 SQLite（time_updated 持续更新）
    │
    ├─ [~20s] watch_feishu 轮询到 AI 回复
    │    └─ 等待 5s 确认 time_updated 不再变化
    │
    └─ [~25s] feishu_client 发送回复到飞书
```

---

## 常见问题

### Q: 需要公网 IP 吗？

不需要。WebSocket 长连接是客户端主动发起连接，只需要服务器能访问外网即可。

### Q: 关闭终端后还能用吗？

可以。所有进程通过 `nohup` 后台运行，关闭终端不影响。重启电脑后运行 `bash start.sh` 即可恢复。

### Q: AI 回复不完整怎么办？

系统使用稳定检测机制：持续监控数据库记录更新时间（`time_updated`），当 5 秒内没有新更新时，才认为 AI 回复完成。

### Q: 如何查看对话历史？

浏览器打开 `http://localhost:4096` 查看 OpenCode Web UI。

### Q: 机器人进入死循环怎么办？

系统内置三重防护：
1. `BOT_OPEN_ID` 过滤 — 机器人自己的消息不处理
2. 30 秒时效过滤 — 超过 30 秒的消息丢弃
3. 消息 ID 去重 — 已处理消息不重复处理

### Q: 支持图片/文件吗？

当前仅支持文本消息。图片和文件需要额外开发（OCR 或文件内容提取）。

---

## License

MIT

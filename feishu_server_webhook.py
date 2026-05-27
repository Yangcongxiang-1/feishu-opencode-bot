"""
飞书 Webhook 回调服务器
======================

接收飞书服务器推送的事件回调（消息、群组事件等），
解析后供 AI 处理，并支持自动回复。

启动方式：
    python feishu_server.py
    python feishu_server.py --port 8080
    python feishu_server.py --host 0.0.0.0 --port 8080 --debug
"""

import hashlib
import json
import sys
import argparse
from pathlib import Path
from typing import Any, Callable

# 将父目录加入路径以便导入
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from config import Config
from feishu_client import FeishuClient

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("❌ 缺少 Flask 依赖，请运行: pip install flask")
    sys.exit(1)

try:
    from loguru import logger
except ImportError:
    import logging as logger
    logger.info = logger.info  # type: ignore  # fallback


# ── 事件处理函数注册表 ──────────────────────────────────────────────────────

# 事件处理器注册表：event_type -> handler_function
_event_handlers: dict[str, list[Callable[[dict], dict | None]]] = {}


def on_event(event_type: str):
    """装饰器：注册飞书事件处理器。

    Args:
        event_type: 事件类型，如 "im.message.receive_v1"
    """
    def decorator(func: Callable[[dict], dict | None]):
        _event_handlers.setdefault(event_type, []).append(func)
        return func

    return decorator


# ── Flask 应用 ──────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/webhook/event", methods=["POST"])
def handle_event():
    """接收飞书事件回调的主入口。

    支持两种模式：
    1. URL 验证（飞书首次配置时校验）
    2. 事件回调（消息、群组等事件）
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "无效的请求体"}), 400

    # ── 1. URL 验证 ────────────────────────────────────────────────────────
    if "challenge" in data:
        logger.info("收到 URL 验证请求，通过")
        # 如果配置了 VERIFY_TOKEN，验证 token
        if Config.VERIFY_TOKEN:
            if data.get("token") != Config.VERIFY_TOKEN:
                logger.warning("URL 验证 token 不匹配")
                return jsonify({"error": "token 验证失败"}), 403
        return jsonify({"challenge": data["challenge"]})

    # ── 2. 事件回调 ─────────────────────────────────────────────────────────
    # 解密（飞书使用 AES 加密，当前版本简化处理）
    # 生产环境建议使用飞书官方 SDK 进行加解密
    event_type = data.get("header", {}).get("event_type", "") or data.get("event_type", "")
    event_id = data.get("header", {}).get("event_id", "") or data.get("event_id", "")

    # 提取事件体
    event_body = data.get("event", {}) or data

    # 解析通用事件结构
    # 飞书 v2.0 事件格式：
    #   {"header": {"event_type": "...", "event_id": "..."}, "event": {...}}
    # 兼容 v1.0 格式：
    #   {"event_type": "...", "event_id": "...", ...}
    event_type_v2 = data.get("header", {}).get("event_type", "")

    logger.info(f"收到事件: type={event_type}, event_id={event_id}")

    # ── 3. 分发事件到已注册的处理器 ────────────────────────────────────────
    responses = []
    matched_handlers = _event_handlers.get(event_type, [])
    matched_handlers += _event_handlers.get(event_type_v2, [])

    if matched_handlers:
        for handler in matched_handlers:
            try:
                result = handler(event_body)
                if result:
                    responses.append(result)
            except Exception as e:
                logger.error(f"事件处理器 {handler.__name__} 异常: {e}")
    else:
        logger.info(f"未注册的事件类型: {event_type}")

    # 飞书要求返回 200 OK（防止重试）
    return jsonify({"code": 0, "msg": "ok", "data": responses})


@app.route("/webhook/health", methods=["GET"])
def health_check():
    """健康检查接口。"""
    return jsonify({
        "status": "ok",
        "app_id": Config.APP_ID[:8] + "***" if Config.APP_ID else None,
        "ai_enabled": Config.AI_RESPONSE_ENABLED,
        "handlers": list(_event_handlers.keys()),
    })


@app.route("/webhook/status", methods=["GET"])
def status_check():
    """详细状态检查，包含飞书 API 连通性。"""
    if not Config.is_valid():
        return jsonify({
            "status": "error",
            "message": "飞书凭证未配置",
            "missing": Config.validate(),
        })

    try:
        client = FeishuClient()
        result = client.status_check()
        if result.get("ok"):
            return jsonify({
                "status": "ok",
                "bot": result.get("data", {}),
                "config": Config.summary(),
            })
        else:
            return jsonify({"status": "error", "message": result.get("error")})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ── 默认事件处理器 ──────────────────────────────────────────────────────────


@on_event("im.message.receive_v1")
def handle_message(event: dict) -> dict | None:
    """处理收到的消息事件。

    解析消息内容，如果开启了 AI 自动回复，则构建回复消息发送回去。

    事件数据结构：
        {
            "sender": {"sender_id": {"open_id": "..."}, ...},
            "message": {
                "message_id": "...",
                "content": "...",  # JSON 字符串
                "chat_type": "p2p" / "group",
                "message_type": "text" / "image" / ...
            }
        }
    """
    sender = event.get("sender", {})
    message = event.get("message", {})

    sender_id = sender.get("sender_id", {}).get("open_id", "")
    message_id = message.get("message_id", "")
    chat_type = message.get("chat_type", "p2p")  # p2p=私聊 / group=群聊
    msg_type = message.get("message_type", "text")

    # 解析消息内容（飞书的消息 content 是 JSON 字符串）
    raw_content = message.get("content", "{}")
    try:
        content_data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    except json.JSONDecodeError:
        content_data = {"text": raw_content}

    text = content_data.get("text", "")

    # 获取群聊 ID（如果是群消息）
    chat_id = message.get("chat_id", "")

    logger.info(
        f"收到消息: from={sender_id}, type={msg_type}, "
        f"chat={chat_type}, text={text[:100]}"
    )

    # AI 自动回复逻辑
    if Config.AI_RESPONSE_ENABLED:
        # 这里构建回复消息的上下文
        # 注意：此时 AI 可能不会立即处理，取决于 OpenCode 的调度
        # 消息会被记录到日志，供 AI 在下次交互时查看和处理
        logger.info(
            f"📩 待处理消息: [from={sender_id}] {text[:200]}"
        )

        # 如果是私聊消息，可以自动回复一个简单的确认
        # 更复杂的回复会由 AI 通过 feishu_client 发送
        try:
            client = FeishuClient()
            reply_text = f"已收到你的消息，我正在处理中..."
            client.send_text(sender_id, reply_text)
            logger.info(f"已发送自动回复确认")
        except Exception as e:
            logger.error(f"自动回复失败: {e}")

    return {
        "handled": True,
        "sender_id": sender_id,
        "message_id": message_id,
        "text": text,
    }


@on_event("im.message.receive_v1")
def log_all_messages(event: dict) -> None:
    """记录所有消息到日志（辅助处理器）。"""
    message = event.get("message", {})
    sender = event.get("sender", {})
    text_raw = message.get("content", "{}")

    try:
        content = json.loads(text_raw) if isinstance(text_raw, str) else text_raw
    except json.JSONDecodeError:
        content = {"text": text_raw}

    # 写入日志文件
    log_entry = {
        "type": "message",
        "sender": sender.get("sender_id", {}),
        "message_id": message.get("message_id"),
        "chat_type": message.get("chat_type"),
        "chat_id": message.get("chat_id"),
        "text": content.get("text", ""),
    }
    logger.debug(f"消息日志: {json.dumps(log_entry, ensure_ascii=False)}")


@on_event("im.message.receive_v1")
def handle_mention(event: dict) -> None:
    """处理 @ 机器人的消息（群聊中被 @ 时）。"""
    message = event.get("message", {})
    mentions = message.get("mentions", [])

    if not mentions:
        return

    for mention in mentions:
        if mention.get("key", "") == "@_user_1":  # 被 @ 标识
            logger.info(f"机器人被 @ 了: {mention.get('name', '')}")


@on_event("url_verify")
def handle_url_verify(event: dict) -> dict:
    """处理 URL 验证（兼容 v1.0 格式）。"""
    logger.info("URL 验证事件")
    return {"verified": True}


# ── 消息队列/缓存（供 AI 查询待处理消息）───────────────────────────────────

_message_queue: list[dict] = []


def get_pending_messages(limit: int = 10) -> list[dict]:
    """获取待处理的飞书消息。

    AI 可以通过此接口拉取飞书消息并处理。

    Args:
        limit: 最多返回的消息数

    Returns:
        待处理消息列表。
    """
    global _message_queue
    messages = _message_queue[-limit:]
    _message_queue = []
    return messages


# ── 启动入口 ────────────────────────────────────────────────────────────────


def main():
    """Webhook 服务器入口。"""
    parser = argparse.ArgumentParser(
        description="飞书机器人 Webhook 服务器",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--host", default=Config.WEBHOOK_HOST, help="监听地址")
    parser.add_argument("--port", type=int, default=Config.WEBHOOK_PORT, help="监听端口")
    parser.add_argument("--debug", action="store_true", default=False, help="调试模式")
    args = parser.parse_args()

    # 验证配置
    missing = Config.validate()
    if missing:
        logger.warning(f"⚠️ 配置缺失: {', '.join(missing)}")
        logger.warning("   请创建 .env 文件并设置飞书应用凭证。")
        logger.warning(f"   参考: {Path(__file__).parent / '.env.example'}")
        logger.warning("   服务器将在配置不全的情况下启动，但部分功能不可用。")

    # 注册的处理器摘要
    if _event_handlers:
        logger.info("已注册的事件处理器:")
        for event_type, handlers in _event_handlers.items():
            logger.info(f"  - {event_type}: {len(handlers)} 个处理器")

    logger.info(f"🚀 飞书 Webhook 服务器启动: http://{args.host}:{args.port}")
    logger.info(f"   事件回调 URL: http://{args.host}:{args.port}/webhook/event")
    logger.info(f"   健康检查: http://{args.host}:{args.port}/webhook/health")
    logger.info(f"   状态检查: http://{args.host}:{args.port}/webhook/status")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

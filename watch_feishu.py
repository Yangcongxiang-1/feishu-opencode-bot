"""
飞书消息监控 — 自动通过 OpenCode AI 处理并回复
============================================

工作流程：
    飞书消息 → feishu_bot → /tmp/feishu-inbox.json
                         → watch 检测到 → opencode run --attach 发送给 AI
                         → AI 处理（保留全部 skill 能力）
                         → 捕获 AI 回复 → 发回飞书
    24小时全自动运行，AI 保留全部 skill 能力。

使用方法：
    python watch_feishu.py                  # 启动监控
    python watch_feishu.py --history         # 查看对话历史
    python watch_feishu.py --init-session    # 初始化飞书专用会话
"""

import json
import os
import sys
import time
import signal
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from feishu_client import FeishuClient
from config import Config

# ── 常量 ─────────────────────────────────────────────────────────────────

INBOX_FILE = "/tmp/feishu-inbox.json"
CHAT_LOG = "/tmp/feishu-chat.log"
SESSION_FILE = os.path.expanduser("~/.config/opencode/skills/feishu-bot/.feishu_session_id")
OPENCODE_WEB_URL = "http://127.0.0.1:4096"
POLL_INTERVAL = 1.5

# ── 状态 ─────────────────────────────────────────────────────────────────

_running = True
_processed_ids: set[str] = set()
_client: FeishuClient | None = None
_feishu_session_id: str | None = None


# ── 日志 ─────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def append_chat_log(entry: dict) -> None:
    try:
        with open(CHAT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"⚠️ 写入对话日志失败: {e}")


# ── 会话管理 ─────────────────────────────────────────────────────────────

def get_session_id() -> str | None:
    """从文件读取保存的飞书会话 ID。"""
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r") as f:
                sid = f.read().strip()
                if sid:
                    return sid
        except Exception:
            pass
    return None


def save_session_id(session_id: str) -> None:
    """保存飞书会话 ID 到文件。"""
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, "w") as f:
            f.write(session_id.strip())
        log(f"✅ 已保存飞书会话 ID: {session_id[:20]}...")
    except Exception as e:
        log(f"⚠️ 保存会话 ID 失败: {e}")


def create_feishu_session() -> str | None:
    """创建新的飞书专用会话，并返回会话 ID。

    通过 opencode run 创建一个专用会话，从 JSON 输出中提取 sessionID。
    """
    log("🔄 正在创建飞书专用会话...")
    try:
        result = subprocess.run(
            [
                "opencode", "run", "--attach", OPENCODE_WEB_URL,
                "--title", "飞书消息处理",
                "--format", "json",
                "初始化飞书处理会话",
            ],
            capture_output=True, text=True, timeout=30,
        )
        # 从 JSON lines 中提取 sessionID
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                sid = event.get("sessionID", "")
                if sid and sid.startswith("ses_"):
                    save_session_id(sid)
                    return sid
            except json.JSONDecodeError:
                continue

        # 从 stderr 或错误输出中尝试提取
        for line in result.stderr.splitlines():
            sid_match = re.search(r'(ses_[a-zA-Z0-9]+)', line)
            if sid_match:
                sid = sid_match.group(1)
                save_session_id(sid)
                return sid

        log("⚠️ 无法从输出中提取会话 ID")
        return None
    except subprocess.TimeoutExpired:
        log("⚠️ 创建会话超时")
        return None
    except FileNotFoundError:
        log("❌ 找不到 opencode 命令，请确认 opencode 已安装")
        return None
    except Exception as e:
        log(f"❌ 创建会话失败: {e}")
        return None


def ensure_session() -> str | None:
    """确保飞书会话存在，返回会话 ID。"""
    global _feishu_session_id

    # 先从文件读
    sid = get_session_id()
    if sid:
        _feishu_session_id = sid
        return sid

    # 没有则创建
    sid = create_feishu_session()
    if sid:
        _feishu_session_id = sid
        return sid

    # 如果创建失败，尝试从已有会话列表中找飞书相关会话
    try:
        result = subprocess.run(
            ["opencode", "session", "list"],
            capture_output=True, text=True, timeout=10,
        )
        # 找标题包含 "飞书" 的会话
        for line in result.stdout.splitlines():
            if "飞书" in line:
                parts = line.split()
                if parts and parts[0].startswith("ses_"):
                    sid = parts[0]
                    save_session_id(sid)
                    _feishu_session_id = sid
                    return sid
    except Exception:
        pass

    return None


# ── AI 处理 ──────────────────────────────────────────────────────────────

OPCODE_DB = os.path.expanduser("~/.local/share/opencode/opencode.db")


def _get_latest_ai_text(session_id: str, since_time: int = 0) -> tuple[int, str] | None:
    """获取 AI 最新文本回复的时间戳和内容。

    只取 AI 生成的回复（有 time.start 字段的 type=text 记录），
    排除用户消息本身（没有 time 字段的纯文本记录）。
    返回 (time_updated, text) 或 None。
    """
    import sqlite3
    try:
        conn = sqlite3.connect(OPCODE_DB)
        if since_time > 0:
            rows = conn.execute(
                """SELECT time_updated, data FROM part
                   WHERE session_id = ?
                     AND json_extract(data, '$.type') = 'text'
                     AND json_extract(data, '$.time.start') IS NOT NULL
                     AND time_updated > ?
                   ORDER BY time_updated DESC LIMIT 1""",
                (session_id, since_time),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT time_updated, data FROM part
                   WHERE session_id = ?
                     AND json_extract(data, '$.type') = 'text'
                     AND json_extract(data, '$.time.start') IS NOT NULL
                   ORDER BY time_updated DESC LIMIT 1""",
                (session_id,),
            ).fetchall()
        conn.close()
        if rows:
            ts, data_str = rows[0]
            d = json.loads(data_str)
            text = d.get("text", "")
            if text:
                return (ts, text)
    except Exception:
        pass
    return None


def process_with_ai(text: str, sender_id: str, chat_id: str) -> str | None:
    """把飞书消息发给 AI，返回 AI 的完整文本回复。

    通过 opencode run --attach 发送消息到 web 服务器的飞书专用会话，
    AI 在后台处理（保留全部 skill 能力）。
    轮询数据库获取 AI 回复，等待回复稳定（连续 5 秒无新内容）才返回。
    """
    session_id = _feishu_session_id
    if not session_id:
        log("⚠️ 没有飞书会话 ID，无法处理消息")
        return None

    context_msg = f"[飞书消息] 用户说: {text}"

    # 记录当前时间戳，只查之后新增的 AI 回复
    import sqlite3
    try:
        conn = sqlite3.connect(OPCODE_DB)
        before_max = conn.execute(
            "SELECT COALESCE(MAX(time_updated), 0) FROM part WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        conn.close()
    except Exception:
        before_max = 0
    log(f"   ↳ 发送给 AI 处理（时间戳基准: {before_max}）...")

    try:
        subprocess.run(
            [
                "opencode", "run", "--attach", OPENCODE_WEB_URL,
                "-c", "-s", session_id,
                context_msg,
            ],
            capture_output=True, timeout=30,
        )
    except FileNotFoundError:
        log("❌ 找不到 opencode 命令")
        return None
    except subprocess.TimeoutExpired:
        log("   ⚠️ 发送命令超时，继续等待 AI 处理...")
    except Exception as e:
        log(f"   ⚠️ 发送消息异常: {e}，继续等待 AI 处理...")

    # 轮询数据库等待 AI 回复（最长 120 秒）
    # 核心改进：等到 AI 回复稳定后才返回
    # 当检测到新的 type=text 后，继续观察 5 秒确认没有更新
    import time as _time

    stable_text = None
    stable_time = 0
    STABLE_WAIT = 5  # 5 秒无变化认为稳定

    for _ in range(120):
        result = _get_latest_ai_text(session_id, since_time=before_max)
        now = int(_time.time())

        if result:
            ts, text_content = result
            if ts != stable_time:
                # 发现新回复，记录并继续等待稳定
                stable_text = text_content
                stable_time = ts
                log(f"   ↳ 检测到 AI 新回复（等待 {STABLE_WAIT}s 确认稳定）...")
                # 重置稳定计时器，重新等待
                _time.sleep(1)
                continue
            else:
                # 和上次一样，计算稳定时长
                elapsed = now - int(ts / 1000)
                if elapsed >= STABLE_WAIT:
                    log(f"✅ AI 回复稳定（{elapsed}s 无变化）: {stable_text[:150]}")
                    return stable_text

        _time.sleep(1)

    # 超时后，有稳定回复则返回，没有则返回 None
    if stable_text:
        log(f"⚠️ AI 回复未完全稳定，返回最后内容: {stable_text[:150]}")
        return stable_text

    log("⚠️ AI 未在 120 秒内回复")
    return None


def _last_message_count(session_id: str) -> int:
    import sqlite3
    try:
        conn = sqlite3.connect(OPCODE_DB)
        cnt = conn.execute(
            "SELECT COUNT(*) FROM part WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return 0


# ── 消息处理 ─────────────────────────────────────────────────────────────

def _extract_open_id(sender_id) -> str:
    """从 sender_id（可能是 dict 或字符串）中提取 open_id。"""
    if isinstance(sender_id, dict):
        return sender_id.get("open_id", str(sender_id.get("open_id", "")))
    return str(sender_id) if sender_id else ""


def _handle_slash_command(text: str) -> str | None:
    """处理斜杠命令。内置命令直接回复，其他转发 AI 处理。"""
    global _feishu_session_id
    cmd = text.strip()
    cmd_lower = cmd.lower()

    # ── /help 命令列表 ──
    if cmd_lower in ("/", "/help", "/start"):
        return (
            "🤖 飞书机器人命令列表\n\n"
            "━━━ 飞书命令 ━━━\n"
            "/help     显示此命令列表\n"
            "/status   查看机器人运行状态\n"
            "/session  查看当前会话信息\n"
            "/new      创建一个全新的 AI 会话\n"
            "/history  查看最近对话记录\n"
            "/config   查看系统配置\n"
            "/version  查看版本信息\n"
            "/clear    清空对话上下文\n"
            "/docs     读取飞书文档内容\n"
            "/feedback 反馈问题或建议\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "其他 OpenCode 斜杠命令可直接发送，AI 会自动处理。\n"
        )

    # ── 内置命令 ──
    if cmd_lower == "/clear":
        return "🧹 清空对话功能目前需要手动处理，后续版本将支持一键清空。"
    if cmd_lower == "/status":
        lines = ["📊 机器人运行状态", ""]
        try:
            import subprocess
            for name, pattern in [("OpenCode Web", "opencode web"),
                                   ("feishu_bot", "feishu_bot"),
                                   ("watch_feishu", "watch_feishu")]:
                r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=5)
                lines.append(f"{name}: {'✅ 运行中' if r.returncode == 0 else '❌ 未运行'}")
        except Exception:
            lines.append("状态检查异常")
        lines.append("")
        lines.append("会话: " + (_feishu_session_id or "无"))
        return "\n".join(lines)
    if cmd_lower == "/session":
        return f"📋 会话 ID: {_feishu_session_id or '无'}\nWeb UI: http://localhost:4096"
    if cmd_lower in ("/new", "/newsession"):
        log("🔄 用户请求创建新会话...")
        sid = create_feishu_session()
        if sid:
            _feishu_session_id = sid
            return (
                f"✅ 已创建新会话\n\n"
                f"会话 ID: {sid}\n"
                f"从现在开始，你的消息将使用新会话处理。\n"
                f"旧会话仍可在 Web UI 查看。"
            )
        else:
            return "❌ 创建新会话失败，请稍后重试。"
    if cmd_lower == "/history":
        return "📜 历史记录功能正在开发中，敬请期待。"
    if cmd_lower == "/config":
        return f"⚙️ 端口: 4096 | 会话: {_feishu_session_id or '无'}\n时效: 30s | 稳定检测: 5s"
    if cmd_lower == "/version":
        return "📦 飞书 OpenCode Bot v1.0\nAI: OpenCode (big-pickle)\nSDK: lark-oapi"
    if cmd_lower == "/feedback":
        return "💬 请直接描述你的问题或建议，AI 会处理。"
    if cmd_lower.startswith("/docs"):
        return "📄 请直接发送飞书文档链接给我。"

    # ── 其他 / 命令 → 返回 None，走 AI 处理 ──
    return None


def handle_message(msg: dict) -> None:
    """处理单条飞书消息。"""
    global _client
    msg_id = msg.get("message_id", "")
    if not msg_id or msg_id in _processed_ids:
        return
    _processed_ids.add(msg_id)

    sender_id_raw = msg.get("sender_id", "")
    text = msg.get("text", "")
    chat_type = msg.get("chat_type", "p2p")
    chat_id = msg.get("chat_id", "")
    sender_id = _extract_open_id(sender_id_raw)

    # ── 时效过滤：只处理 30 秒内的消息 ──
    msg_time = msg.get("timestamp", 0)
    if not msg_time or int(time.time()) - msg_time > 30:
        if msg_time:
            log(f"⏭️ 跳过过期消息（>30s）: {text[:80]}")
        return

    log(f"📩 {'私聊' if chat_type == 'p2p' else '群聊'} {sender_id[-12:]}: {text[:200]}")

    append_chat_log({
        "time": datetime.now().isoformat(),
        "sender_id": sender_id,
        "message_id": msg_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "text": text,
        "direction": "in",
    })

    # 只有私聊消息才自动处理
    if chat_type != "p2p":
        return

    if not _client:
        log("⚠️ FeishuClient 未初始化，跳过回复")
        return

    # ── 斜杠命令：直接返回命令列表，不经过 AI ──
    if text.startswith("/"):
        reply = _handle_slash_command(text)
        if reply:
            _send_reply(sender_id, reply)
            return

    # 通过 AI 处理消息
    reply = process_with_ai(text, sender_id, chat_id)
    if reply is None:
        # fallback: 简单回复
        reply = f"收到你的消息了 ✅ 我会尽快处理。消息内容：{text[:100]}"

    _send_reply(sender_id, reply)


def _send_reply(send_to: str, reply_text: str) -> None:
    """发送回复到飞书并记录日志。"""
    global _client
    if not _client:
        log("⚠️ FeishuClient 未初始化，无法发送")
        return
    try:
        result = _client.send_text(send_to, reply_text)
        if result.get("ok"):
            append_chat_log({
                "time": datetime.now().isoformat(),
                "sender_id": "bot",
                "text": reply_text,
                "direction": "out",
            })
            log(f"✅ 已回复飞书用户: {reply_text[:100]}")
        else:
            log(f"⚠️ 回复失败: {result.get('error')}")
    except Exception as e:
        log(f"⚠️ 回复异常: {e}")


# ── 轮询 ─────────────────────────────────────────────────────────────────

def poll_messages() -> None:
    """轮询检查新消息。"""
    if not Path(INBOX_FILE).exists():
        return
    try:
        with open(INBOX_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content or content == "[]":
                return
            messages = json.loads(content)
    except (json.JSONDecodeError, OSError):
        return
    if not messages:
        return
    for msg in messages:
        handle_message(msg)
    try:
        with open(INBOX_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    except OSError as e:
        log(f"⚠️ 清空消息文件失败: {e}")


# ── 信号处理 ─────────────────────────────────────────────────────────────

def signal_handler(sig, frame) -> None:
    global _running
    if not _running:
        return
    _running = False
    log(f"\n🛑 监控停止，共处理 {len(_processed_ids)} 条消息")


# ── 历史查看 ─────────────────────────────────────────────────────────────

def show_history(lines: int = 30) -> None:
    if not Path(CHAT_LOG).exists():
        print("暂无对话记录。")
        return
    try:
        with open(CHAT_LOG, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        recent = all_lines[-lines:]
        print(f"\n📋 最近对话 ({len(recent)} 条):")
        print("-" * 60)
        for line in recent:
            entry = json.loads(line)
            who = "🤖" if entry.get("direction") == "out" else "👤"
            ts = entry.get("time", "")[11:19]
            txt = entry.get("text", "")
            print(f"{who} [{ts}] {txt[:150]}")
        print("-" * 60)
    except Exception as e:
        print(f"读取对话日志失败: {e}")


# ── 入口 ─────────────────────────────────────────────────────────────────

def main() -> NoReturn:
    global _client

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 初始化飞书 API 客户端
    try:
        _client = FeishuClient()
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # 确保飞书专用会话存在
    print(f"\n{'='*50}")
    print(f"  飞书消息监控 (AI 处理模式)")
    print(f"  收到消息 → opencode AI 处理 → 回复飞书")
    print(f"  AI 保留全部 skill 插件能力")
    print(f"{'='*50}")

    sid = ensure_session()
    if sid:
        global _feishu_session_id
        _feishu_session_id = sid
        print(f"\n✅ 飞书会话: {sid}")
    else:
        print(f"\n⚠️ 未能获取飞书会话，AI 处理将不可用")
        print(f"   可稍后运行: python {__file__} --init-session")

    print(f"  按 Ctrl+C 停止\n")

    while _running:
        try:
            poll_messages()
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"❌ 监控异常: {e}")
            time.sleep(POLL_INTERVAL * 2)

    print(f"\n👋 监控停止")


def init_session_main() -> None:
    """仅初始化飞书会话（--init-session 模式）。"""
    sid = ensure_session()
    if sid:
        print(f"✅ 飞书会话就绪: {sid}")
        print(f"   保存在: {SESSION_FILE}")
    else:
        print("❌ 创建飞书会话失败")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("--history", "-h"):
            show_history()
        elif arg in ("--init-session", "-i"):
            init_session_main()
        else:
            print(f"未知参数: {arg}")
            print(f"用法: python {__file__} [--history | --init-session]")
            sys.exit(1)
    else:
        main()

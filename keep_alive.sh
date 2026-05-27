#!/bin/bash
# 飞书机器人保活脚本
# 持续监控 feishu_bot 和 watch_feishu，崩溃后自动重启

SKILL_DIR="$HOME/.config/opencode/skills/feishu-bot"
VENV_PYTHON="$SKILL_DIR/venv/bin/python"
BOT_LOG="/tmp/feishu-bot.log"
WATCH_LOG="/tmp/watch-feishu.log"
INBOX_FILE="/tmp/feishu-inbox.json"
PENDING_FILE="/tmp/feishu-pending.json"

echo "[保活] 飞书机器人保活脚本已启动 (PID: $$)"
echo "[保活] 监控频率: 每 10 秒检查一次"

while true; do
    # 检查 feishu_bot
    BOT_PID=$(pgrep -f "python.*feishu_bot\.py" | head -1)
    if [ -z "$BOT_PID" ] || ! kill -0 "$BOT_PID" 2>/dev/null; then
        echo "[保活] feishu_bot 已停止，正在重启..."
        rm -f "$INBOX_FILE"
        nohup "$VENV_PYTHON" "$SKILL_DIR/feishu_bot.py" > "$BOT_LOG" 2>&1 &
        echo "[保活] feishu_bot 已重启 (PID: $!)"
    fi

    # 检查 watch_feishu
    WATCH_PID=$(pgrep -f "python.*watch_feishu\.py" | head -1)
    if [ -z "$WATCH_PID" ] || ! kill -0 "$WATCH_PID" 2>/dev/null; then
        echo "[保活] watch_feishu 已停止，正在重启..."
        nohup "$VENV_PYTHON" "$SKILL_DIR/watch_feishu.py" > "$WATCH_LOG" 2>&1 &
        echo "[保活] watch_feishu 已重启 (PID: $!)"
    fi

    sleep 10
done

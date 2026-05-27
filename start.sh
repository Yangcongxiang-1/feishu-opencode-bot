#!/bin/bash
# 飞书机器人一键启动脚本
# 重启电脑后运行：bash start.sh

DIR="/home/yang/.config/opencode/skills/feishu-bot"
VENV_P="$DIR/venv/bin/python"

# 清空旧消息队列
:> /tmp/feishu-inbox.json

echo "🚀 启动飞书机器人系统..."

# 1. 启动 opencode Web 服务（AI 处理引擎）
nohup opencode web --port 4096 > /tmp/opencode-web.log 2>&1 &
echo "  opencode web PID: $!"

# 2. 启动飞书消息接收网关（WebSocket 长连接）
nohup "$VENV_P" "$DIR/feishu_bot.py" > /tmp/feishu-bot.log 2>&1 &
echo "  feishu_bot PID: $!"

sleep 3

# 3. 启动消息监控（自动转发飞书消息到 AI 并回复）
nohup "$VENV_P" "$DIR/watch_feishu.py" > /tmp/watch-feishu.log 2>&1 &
echo "  watch_feishu PID: $!"

sleep 2

echo ""
echo "✅ 全部启动完成！"
echo "   浏览器打开 http://localhost:4096 查看对话"
echo "   飞书发消息给 apibot 即可对话"

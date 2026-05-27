#!/bin/bash
set -e

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SKILL_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python3"
PIP_BIN="$VENV_DIR/bin/pip"

echo "=========================================="
echo "  飞书机器人插件 - 安装向导"
echo "  (WebSocket 长连接模式)"
echo "=========================================="
echo ""
echo "安装目录: $SKILL_DIR"
echo ""

# ── 0. 创建虚拟环境 ────────────────────────────────────────────
echo "▶ 步骤 1/3: 创建 Python 虚拟环境..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "   ✅ 虚拟环境已创建"
else
    echo "   ✅ 虚拟环境已存在"
fi
echo ""

# ── 1. 安装 lark-oapi SDK ─────────────────────────────────────
echo "▶ 步骤 2/3: 安装飞书 SDK (lark-oapi)..."
$PIP_BIN install -r "$SKILL_DIR/requirements.txt" -q
echo "   ✅ 依赖安装完成"
echo ""

# ── 2. 配置 .env 文件 ──────────────────────────────────────────
echo "▶ 步骤 3/3: 配置飞书应用凭证..."
if [ ! -f "$SKILL_DIR/.env" ]; then
    cp "$SKILL_DIR/.env.example" "$SKILL_DIR/.env"
    echo "   📝 已创建 .env 文件模板: $SKILL_DIR/.env"
    echo "   ⚠️  请编辑该文件，填入你的 App ID 和 App Secret"
    echo ""
    echo "   编辑命令:"
    echo "     nano $SKILL_DIR/.env"
    echo ""
else
    echo "   ✅ .env 文件已存在，跳过"
fi

echo ""
echo "=========================================="
echo "  安装完成！"
echo "=========================================="
echo ""
echo "📖 使用说明："
echo ""
echo "  1. 编辑 .env 文件填入飞书凭证:"
echo "     nano \"$SKILL_DIR/.env\""
echo ""
echo "  2. 启动机器人（WebSocket 长连接，无需公网 IP）:"
echo "     $PYTHON_BIN \"$SKILL_DIR/feishu_bot.py\""
echo ""
echo "  3. 发送测试消息:"
echo "     $PYTHON_BIN \"$SKILL_DIR/feishu_client.py\" --action status"
echo "     $PYTHON_BIN \"$SKILL_DIR/feishu_client.py\" --action send --to ou_xxx --type text --content \"你好\""
echo ""
echo "  4. 飞书开发者后台配置:"
echo "     - 选择「使用长连接接收事件」"
echo "     - 添加事件: im.message.receive_v1"
echo "     - 添加权限: im:message 等"
echo "     - 发布应用"
echo ""
echo "  5. 创建快捷命令（可选）:"
echo '     alias feishu-bot="$PYTHON_BIN $SKILL_DIR/feishu_bot.py"'
echo '     alias feishu-send="$PYTHON_BIN $SKILL_DIR/feishu_client.py"'
echo "     将以上 alias 添加到 ~/.bashrc 即可使用快捷命令"
echo ""

#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="${OPENCODE_SKILL_DIR:-$HOME/.config/opencode/skills/feishu-bot}"

echo "=========================================="
echo "  飞书机器人插件 - 安装向导"
echo "  (WebSocket 长连接模式)"
echo "=========================================="
echo ""

# ── 如果不在目标目录，先部署 ──
if [ "$SCRIPT_DIR" != "$TARGET_DIR" ]; then
    echo "▶ 步骤 0/3: 部署到 OpenCode Skill 目录..."
    mkdir -p "$TARGET_DIR"
    for f in feishu_bot.py watch_feishu.py feishu_client.py feishu_server_webhook.py config.py start.sh keep_alive.sh requirements.txt .env.example SKILL.md; do
        if [ -f "$SCRIPT_DIR/$f" ]; then
            cp "$SCRIPT_DIR/$f" "$TARGET_DIR/$f"
        fi
    done
    # 如果 .env 已存在则不覆盖
    if [ ! -f "$TARGET_DIR/.env" ] && [ -f "$TARGET_DIR/.env.example" ]; then
        cp "$TARGET_DIR/.env.example" "$TARGET_DIR/.env"
        echo "   📝 已创建 .env 文件模板"
    fi
    echo "   ✅ 文件已部署到: $TARGET_DIR"
    echo ""
    # 切换到目标目录继续安装
    cd "$TARGET_DIR"
else
    cd "$TARGET_DIR"
fi

SKILL_DIR="$TARGET_DIR"
VENV_DIR="$SKILL_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python3"
PIP_BIN="$VENV_DIR/bin/pip"

echo "安装目录: $SKILL_DIR"
echo ""

# ── 1. 创建虚拟环境 ────────────────────────────────────────────
echo "▶ 步骤 1/3: 创建 Python 虚拟环境..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "   ✅ 虚拟环境已创建"
else
    echo "   ✅ 虚拟环境已存在"
fi
echo ""

# ── 2. 安装 lark-oapi SDK ─────────────────────────────────────
echo "▶ 步骤 2/3: 安装飞书 SDK (lark-oapi)..."
$PIP_BIN install -r "$SKILL_DIR/requirements.txt" -q
echo "   ✅ 依赖安装完成"
echo ""

# ── 3. 配置 .env 文件 ──────────────────────────────────────────
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
echo "  2. 启动机器人:"
echo "     bash \"$SKILL_DIR/start.sh\""
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
echo "  5. 查看对话记录:"
echo "     http://localhost:4096"
echo ""
echo "  环境变量:"
echo "     OPENCODE_SKILL_DIR  - 指定安装目录（默认 ~/.config/opencode/skills/feishu-bot）"
echo ""

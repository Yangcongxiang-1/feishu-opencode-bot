"""
飞书机器人配置管理模块
====================

负责从环境变量或 .env 文件加载飞书应用配置。
支持 Flask 和 CLI 两种使用模式。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 尝试加载 .env 文件（如果存在）
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


class Config:
    """飞书机器人配置。

    通过环境变量或 .env 文件配置，所有配置项均有默认值或明确的错误提示。
    """

    # ── 飞书应用凭证 ──────────────────────────────────────────────────────
    APP_ID: str = os.getenv("FEISHU_APP_ID", "")
    """飞书应用的 App ID，在开发者后台获取。"""

    APP_SECRET: str = os.getenv("FEISHU_APP_SECRET", "")
    """飞书应用的 App Secret，在开发者后台获取。"""

    VERIFY_TOKEN: str = os.getenv("FEISHU_VERIFY_TOKEN", "")
    """飞书事件验证令牌。可选，但推荐配置以增强安全性。"""

    # ── Webhook 服务器 ────────────────────────────────────────────────────
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    """Webhook 服务器监听地址，默认监听所有网络接口。"""

    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))
    """Webhook 服务器监听端口，默认 8080。"""

    # ── AI 行为控制 ───────────────────────────────────────────────────────
    AI_RESPONSE_ENABLED: bool = os.getenv("AI_RESPONSE_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    """是否开启 AI 自动回复。关闭后机器人仅接收消息但不自动回复。"""

    BOT_OPEN_ID: str = os.getenv("BOT_OPEN_ID", "")
    """机器人的 open_id，用于过滤机器人自己发出的消息，防止循环。
    首次启动日志中可找到: open_id=ou_xxx... 填入即可。"""

    # ── 飞书 API 端点 ────────────────────────────────────────────────────
    BASE_URL: str = "https://open.feishu.cn/open-apis"
    """飞书开放 API 基础地址。"""

    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置是否完整。

        Returns:
            缺失配置项的列表。如果返回空列表则表示配置完整。
        """
        missing: list[str] = []
        if not cls.APP_ID:
            missing.append("FEISHU_APP_ID")
        if not cls.APP_SECRET:
            missing.append("FEISHU_APP_SECRET")
        return missing

    @classmethod
    def is_valid(cls) -> bool:
        """配置是否有效（必要项均已配置）。"""
        return len(cls.validate()) == 0

    @classmethod
    def summary(cls) -> dict:
        """返回配置摘要（隐藏敏感信息）。"""
        return {
            "app_id": cls.APP_ID[:8] + "***" if cls.APP_ID else "(未设置)",
            "has_secret": bool(cls.APP_SECRET),
            "has_verify_token": bool(cls.VERIFY_TOKEN),
            "webhook_host": cls.WEBHOOK_HOST,
            "webhook_port": cls.WEBHOOK_PORT,
            "ai_response_enabled": cls.AI_RESPONSE_ENABLED,
        }

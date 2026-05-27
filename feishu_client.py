"""
飞书 API 客户端模块
==================

封装飞书开放平台的核心 API 调用，提供：
- 自动管理 tenant_access_token（获取 + 缓存 + 自动刷新）
- 发送消息（文本、富文本、卡片、图片）
- 查询用户 / 群组信息
- 命令行模式（支持脚本调用）

用法（Python 调用）：
    from feishu_client import FeishuClient
    client = FeishuClient()
    result = client.send_text(open_id="ou_xxx", text="你好！")

用法（命令行）：
    python feishu_client.py --action send --to "ou_xxx" --type text --content "你好"
    python feishu_client.py --action status
"""

import json
import sys
import time
import argparse
from pathlib import Path
from typing import Any

import requests

# 将父目录加入路径以便导入 config
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from config import Config


class FeishuClient:
    """飞书 API 客户端。

    封装飞书开放平台的 REST API，自动处理 token 获取和刷新。
    所有公有方法返回统一的 dict 格式：{"ok": bool, "data": Any, "error": str}
    """

    def __init__(self, app_id: str = None, app_secret: str = None):
        """初始化客户端。

        Args:
            app_id: 飞书 App ID。为 None 时从 Config 读取。
            app_secret: 飞书 App Secret。为 None 时从 Config 读取。
        """
        self._app_id = app_id or Config.APP_ID
        self._app_secret = app_secret or Config.APP_SECRET
        self._base_url = Config.BASE_URL

        # Token 缓存
        self._token: str | None = None
        self._token_expire_at: float = 0.0  # Unix 时间戳

        # HTTP 会话（复用连接）
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

        # 验证凭证
        if not self._app_id or not self._app_secret:
            raise ValueError(
                "缺少飞书凭证：请在 .env 文件中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
            )

    # ── Token 管理 ──────────────────────────────────────────────────────────

    def _get_tenant_access_token(self) -> str:
        """获取 tenant_access_token（自动缓存和刷新）。

        Returns:
            有效的 tenant_access_token。

        Raises:
            RuntimeError: 获取 token 失败。
        """
        # 缓存命中且在有效期内（预留 5 分钟缓冲）
        if self._token and time.time() < self._token_expire_at - 300:
            return self._token

        url = f"{self._base_url}/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self._app_id, "app_secret": self._app_secret}

        resp = self._session.post(url, json=payload, timeout=10)
        data = resp.json()

        if data.get("code") != 0 or "tenant_access_token" not in data:
            raise RuntimeError(
                f"获取 tenant_access_token 失败: {data.get('msg', '未知错误')} "
                f"(code={data.get('code')})"
            )

        self._token = data["tenant_access_token"]
        self._token_expire_at = time.time() + data.get("expire", 7200)
        return self._token

    @property
    def _headers(self) -> dict:
        """包含有效 Authorization 的请求头。"""
        token = self._get_tenant_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── 通用 API 调用 ──────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict | None = None) -> dict:
        """发送 POST 请求到飞书 API。

        Args:
            path: API 路径（如 /im/v1/messages）
            payload: 请求体

        Returns:
            飞书 API 的完整响应（已解析为 dict）。
        """
        url = f"{self._base_url}{path}"
        resp = self._session.post(url, headers=self._headers, json=payload or {}, timeout=15)
        return resp.json()

    def _get(self, path: str, params: dict | None = None) -> dict:
        """发送 GET 请求到飞书 API。

        Args:
            path: API 路径
            params: 查询参数

        Returns:
            飞书 API 的完整响应。
        """
        url = f"{self._base_url}{path}"
        resp = self._session.get(url, headers=self._headers, params=params or {}, timeout=15)
        return resp.json()

    # ── 消息发送 ────────────────────────────────────────────────────────────

    def send_text(
        self,
        receive_id: str,
        content: str,
        receive_id_type: str = "open_id",
    ) -> dict:
        """发送文本消息。

        Args:
            receive_id: 接收方 ID（open_id / union_id / user_id / chat_id）
            content: 文本内容（纯文本，支持 @ 用户语法）
            receive_id_type: ID 类型。可选：open_id / union_id / user_id / chat_id

        Returns:
            {"ok": True, "data": message_id} 或 {"ok": False, "error": ...}
        """
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        }
        result = self._post(
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            payload,
        )

        if result.get("code") == 0:
            message_id = result.get("data", {}).get("message_id", "")
            return {"ok": True, "data": message_id}
        else:
            return {"ok": False, "error": result.get("msg", "发送失败")}

    def send_rich_text(
        self,
        receive_id: str,
        content: str,
        title: str = "",
        receive_id_type: str = "open_id",
    ) -> dict:
        """发送富文本消息。

        Args:
            receive_id: 接收方 ID
            content: 富文本内容（支持飞书富文本格式，使用 \\n 换行）
            title: 消息标题（可选）
            receive_id_type: ID 类型

        Returns:
            发送结果。
        """
        # 构建富文本结构
        post_content: dict[str, Any] = {
            "zh_cn": {
                "title": title or "消息",
                "content": [],
            }
        }

        # 将文本按行分割，每行作为一个段落
        paragraphs = content.strip().split("\n")
        for para in paragraphs:
            if para.strip():
                post_content["zh_cn"]["content"].append(
                    [{"tag": "text", "text": para.strip()}]
                )

        payload = {
            "receive_id": receive_id,
            "msg_type": "post",
            "content": json.dumps(post_content),
        }
        result = self._post(
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            payload,
        )

        if result.get("code") == 0:
            message_id = result.get("data", {}).get("message_id", "")
            return {"ok": True, "data": message_id}
        else:
            return {"ok": False, "error": result.get("msg", "发送失败")}

    def send_card(
        self,
        receive_id: str,
        header_title: str,
        elements: list[dict],
        receive_id_type: str = "open_id",
    ) -> dict:
        """发送卡片消息。

        Args:
            receive_id: 接收方 ID
            header_title: 卡片标题
            elements: 卡片元素列表（符合飞书卡片 JSON 格式）
            receive_id_type: ID 类型

        Returns:
            发送结果。

        示例 elements:
            [
                {"tag": "markdown", "content": "这是**卡片**内容"},
                {"tag": "hr"},
                {"tag": "action", "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "确认"},
                     "value": {"action": "confirm"}}
                ]}
            ]
        """
        card_content = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": header_title},
                "template": "blue",
            },
            "elements": elements,
        }

        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card_content),
        }
        result = self._post(
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            payload,
        )

        if result.get("code") == 0:
            message_id = result.get("data", {}).get("message_id", "")
            return {"ok": True, "data": message_id}
        else:
            return {"ok": False, "error": result.get("msg", "发送失败")}

    # ── 信息查询 ────────────────────────────────────────────────────────────

    def get_user_info(self, user_id: str, user_id_type: str = "open_id") -> dict:
        """获取飞书用户信息。

        Args:
            user_id: 用户 ID
            user_id_type: ID 类型（open_id / union_id / user_id）

        Returns:
            查询结果。
        """
        result = self._get(
            "/contact/v3/users/batch_get_id",
            params={user_id_type: user_id},
        )
        if result.get("code") == 0:
            return {"ok": True, "data": result.get("data", {})}
        return {"ok": False, "error": result.get("msg", "查询失败")}

    def get_bot_info(self) -> dict:
        """获取机器人自身信息。

        Returns:
            机器人信息（包括名称、描述等）。
        """
        result = self._get("/im/v1/bots/info")
        if result.get("code") == 0:
            return {"ok": True, "data": result.get("data", {})}
        return {"ok": False, "error": result.get("msg", "查询失败")}

    def status_check(self) -> dict:
        """全面检查机器人连通性。

        依次检查：
        1. Token 获取是否正常
        2. 机器人基本信息是否可查

        Returns:
            {"ok": True, "bot_info": ...} 或 {"ok": False, "error": ...}
        """
        try:
            token = self._get_tenant_access_token()
            if not token:
                return {"ok": False, "error": "获取 token 失败"}
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}

        bot_info = self.get_bot_info()
        return bot_info

    # ── 便捷工具方法 ────────────────────────────────────────────────────────

    @staticmethod
    def build_simple_card(
        title: str,
        content: str,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> list[dict]:
        """构建一个简单的消息卡片元素列表。

        Args:
            title: 卡片标题
            content: 卡片正文（支持 Markdown 格式）
            button_text: 按钮文字（可选）
            button_url: 按钮链接（可选）

        Returns:
            卡片元素列表。
        """
        elements: list[dict] = [
            {"tag": "markdown", "content": content},
        ]

        if button_text and button_url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": button_text},
                            "type": "default",
                            "url": button_url,
                        }
                    ],
                }
            )

        return elements


# ── 命令行入口 ──────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="飞书机器人客户端 — 发送消息、查询状态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 发送文本消息
  python feishu_client.py --action send --to "ou_xxx" --type text --content "你好世界"

  # 发送富文本消息
  python feishu_client.py --action send --to "ou_xxx" --type rich_text --title "通知" --content "第一行\\n第二行"

  # 检查状态
  python feishu_client.py --action status

  # 发送卡片
  python feishu_client.py --action send --to "ou_xxx" --type card --title "任务通知" --content "任务已完成"
        """,
    )
    parser.add_argument(
        "--action",
        choices=["send", "status", "info"],
        default="status",
        help="操作类型：send=发送消息, status=状态检查, info=机器人信息",
    )
    parser.add_argument("--to", help="接收方 ID（open_id / chat_id）")
    parser.add_argument(
        "--type",
        choices=["text", "rich_text", "card"],
        default="text",
        help="消息类型",
    )
    parser.add_argument("--title", default="", help="消息标题（富文本或卡片消息）")
    parser.add_argument("--content", default="", help="消息内容")
    parser.add_argument(
        "--id-type",
        default="open_id",
        choices=["open_id", "union_id", "user_id", "chat_id"],
        help="接收方 ID 类型",
    )
    return parser.parse_args()


def main():
    """命令行入口。"""
    args = _parse_args()

    # 验证配置
    missing = Config.validate()
    if missing:
        print(f"❌ 配置缺失: {', '.join(missing)}")
        print("   请创建 .env 文件并设置飞书应用凭证。")
        print(f"   参考: {Path(__file__).parent / '.env.example'}")
        sys.exit(1)

    try:
        client = FeishuClient()
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    if args.action == "status":
        result = client.status_check()
        if result.get("ok"):
            info = result.get("data", {})
            print(f"✅ 机器人状态正常")
            print(f"   名称: {info.get('app_name', '未知')}")
            print(f"   App ID: {info.get('app_id', '未知')}")
            print(f"   描述: {info.get('description', '无')}")
        else:
            print(f"❌ 状态异常: {result.get('error')}")
        return

    if args.action == "info":
        result = client.get_bot_info()
        if result.get("ok"):
            print(json.dumps(result["data"], ensure_ascii=False, indent=2))
        else:
            print(f"❌ 查询失败: {result.get('error')}")
        return

    if args.action == "send":
        if not args.to:
            print("❌ 请指定接收方 (--to)")
            sys.exit(1)
        if not args.content and args.type != "card":
            print("❌ 请指定消息内容 (--content)")
            sys.exit(1)

        if args.type == "text":
            result = client.send_text(args.to, args.content, args.id_type)
        elif args.type == "rich_text":
            result = client.send_rich_text(
                args.to, args.content, args.title, args.id_type
            )
        elif args.type == "card":
            elements = FeishuClient.build_simple_card(
                args.title or "通知", args.content
            )
            result = client.send_card(args.to, args.title or "通知", elements, args.id_type)
        else:
            result = {"ok": False, "error": f"不支持的消息类型: {args.type}"}

        if result.get("ok"):
            print(f"✅ 消息发送成功 (message_id: {result['data']})")
        else:
            print(f"❌ 消息发送失败: {result.get('error')}")


if __name__ == "__main__":
    main()

"""企业微信群机器人推送。

用法：在企业微信群里「群设置 → 群机器人 → 添加」，复制 Webhook 地址填到 .env 的
WECOM_WEBHOOK。机器人只能往它所在的群里发消息（不能私聊、不能发给外部联系人）。
"""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

WECOM_LIMIT_PER_MINUTE = 20


def webhook_url() -> str:
    return os.getenv("WECOM_WEBHOOK", "").strip()


def is_configured() -> bool:
    return bool(webhook_url())


def send_markdown(content: str, webhook: str | None = None) -> bool:
    """发送 markdown 消息到企业微信群。content 上限 4096 字节，超长按字节截断。"""
    url = webhook or webhook_url()
    if not url:
        raise RuntimeError("WECOM_WEBHOOK 未配置")

    data_bytes = content.encode("utf-8")
    if len(data_bytes) > 3800:
        content = data_bytes[:3800].decode("utf-8", "ignore") + "\n…（内容过长已截断）"

    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    with httpx.Client(timeout=15) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"企业微信推送失败: {data}")
    return True


def send_text(content: str, webhook: str | None = None) -> bool:
    url = webhook or webhook_url()
    if not url:
        raise RuntimeError("WECOM_WEBHOOK 未配置")
    payload = {"msgtype": "text", "text": {"content": content[:2000]}}
    with httpx.Client(timeout=15) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"企业微信推送失败: {data}")
    return True

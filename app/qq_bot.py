"""QQ 官方机器人：被动回复群消息。

QQ 官方平台不允许群机器人主动推送，只能「有人 @ 机器人 / 触发事件」后回复。
因此这里做成指令式：群成员 @机器人 发「日报」「重要」等，机器人回一条摘要。

凭据：.env 中的 QQ_APPID / QQ_APPSECRET（QQ 开放平台 → 机器人 → 开发设置）。
"""
from __future__ import annotations

import logging
import os

from . import db

log = logging.getLogger(__name__)

# 触发词 → 查询类型
COMMANDS = {
    "日报": "daily",
    "今日": "daily",
    "摘要": "daily",
    "通知": "daily",
    "重要": "important",
    "重点": "important",
}

DAILY_LIMIT = 12
IMPORTANT_LIMIT = 8
MAX_TEXT = 1400


def is_configured() -> bool:
    return bool(os.getenv("QQ_APPID", "").strip() and os.getenv("QQ_APPSECRET", "").strip())


def parse_command(text: str | None) -> str | None:
    """从消息文本里识别指令：返回 daily / important / None。"""
    content = (text or "").strip().lstrip("/／").strip()
    if not content:
        return None
    for word, kind in COMMANDS.items():
        if word in content:
            return kind
    return None


def _link_of(row) -> str:
    url = row["url"] or ""
    if ("content.jsp" in url or "tzggnr.jsp" in url) and row["fallback_url"]:
        return row["fallback_url"]
    return url


def build_text(kind: str = "daily") -> str:
    """生成回复文本（纯文本，控制长度）。"""
    conn = db.connect()
    try:
        if kind == "important":
            rows = conn.execute(
                """SELECT n.*, s.name AS source_name
                     FROM notices n LEFT JOIN sources s ON s.code = n.source_code
                    WHERE n.status <> 'archived' AND n.importance >= 60
                    ORDER BY n.importance DESC,
                             COALESCE(n.published_at, n.first_seen_at) DESC
                    LIMIT ?""",
                (IMPORTANT_LIMIT,),
            ).fetchall()
            title = "【武大通知】重要通知"
        else:
            # 「日报」= 站内最新的若干条（按发布时间倒序）
            rows = conn.execute(
                """SELECT n.*, s.name AS source_name
                     FROM notices n LEFT JOIN sources s ON s.code = n.source_code
                    WHERE n.status <> 'archived'
                    ORDER BY COALESCE(n.published_at, n.first_seen_at) DESC,
                             n.importance DESC
                    LIMIT ?""",
                (DAILY_LIMIT,),
            ).fetchall()
            title = "【武大通知】近期摘要"
    finally:
        conn.close()

    lines = [f"{title}（{len(rows)} 条）"]
    if not rows:
        lines.append("暂无新通知。")
    for row in rows:
        if sum(len(x) for x in lines) > MAX_TEXT:
            lines.append("…（还有更多，请到网站查看）")
            break
        date = row["published_at"] or (row["first_seen_at"] or "")[:10]
        deadline = f" ⏰{row['deadline_date']}" if row["deadline_date"] else ""
        lines.append("")
        lines.append(f"· {row['title']}")
        lines.append(f"  {row['source_name'] or row['source_code']} · {date}{deadline}")
        lines.append(f"  {_link_of(row)}")

    site = os.getenv("SITE_URL", "").strip()
    if site:
        lines.append("")
        lines.append(f"网页版：{site}")
    text = "\n".join(lines)
    return text[:MAX_TEXT]


def run() -> int:
    """启动 WebSocket 长连接，监听群 @ 消息并被动回复。"""
    if not is_configured():
        log.warning("QQ_APPID / QQ_APPSECRET 未配置，机器人不启动")
        return 0

    try:
        import botpy
    except ImportError:
        log.error("未安装 qq-botpy，请先 pip install qq-botpy")
        return 1

    appid = os.getenv("QQ_APPID", "").strip()
    secret = os.getenv("QQ_APPSECRET", "").strip()

    class Client(botpy.Client):
        async def on_ready(self):
            log.info("QQ 机器人已上线：%s", self.robot.name if getattr(self, "robot", None) else "")

        async def on_group_at_message_create(self, message):
            kind = parse_command(message.content)
            if not kind:
                await message.reply(
                    content="发送「日报」查看近两日摘要，发送「重要」查看重点通知。"
                )
                return
            try:
                text = build_text(kind)
                await message.reply(content=text)
                log.info("已回复群 %s：%s", message.group_openid, kind)
            except Exception:  # noqa: BLE001
                log.exception("回复失败")
                try:
                    await message.reply(content="生成摘要失败，请稍后再试。")
                except Exception:  # noqa: BLE001
                    pass

    intents = botpy.Intents(public_messages=True)
    log.info("启动 QQ 机器人 WebSocket……")
    Client(intents=intents).run(appid=appid, secret=secret)
    return 0

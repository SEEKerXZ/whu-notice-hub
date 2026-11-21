"""邮件日报与即时推送。"""
from __future__ import annotations

import html
import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from . import db, mailer

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------
def _card(row: sqlite3.Row, show_deadline: bool = False) -> str:
    title = html.escape(row["title"])
    meta = [html.escape(row["source_name"] or row["source_code"])]
    if row["published_at"]:
        meta.append(html.escape(row["published_at"]))
    if row["category"]:
        meta.append(html.escape(row["category"]))
    deadline = ""
    if row["deadline_date"]:
        deadline = (
            f'<span style="color:#cf222e;font-weight:600">⏰ 截止 {html.escape(row["deadline_date"])}</span>'
        )
    summary = html.escape(row["summary"] or "")[:160]
    url = html.escape(row["url"])
    return f"""
    <div style="padding:12px 0;border-bottom:1px solid #e5e7eb">
      <div style="font-size:15px;font-weight:600;line-height:1.5">
        <a href="{url}" style="color:#0969da;text-decoration:none">{title}</a>
      </div>
      <div style="color:#6b7280;font-size:12px;margin-top:4px">{' · '.join(meta)}</div>
      <div style="color:#374151;font-size:13px;margin-top:6px">{summary}</div>
      <div style="font-size:12px;margin-top:6px">{deadline}</div>
    </div>"""


def build_html(title: str, sections: list[tuple[str, list[sqlite3.Row]]]) -> str:
    body = ""
    for heading, rows in sections:
        if not rows:
            continue
        body += f'<h2 style="font-size:16px;margin:22px 0 6px">{html.escape(heading)}</h2>'
        body += "".join(_card(r) for r in rows)
    today = datetime.now().strftime("%Y-%m-%d")
    site = os.getenv("SITE_URL", "").strip()
    site_link = (
        f'<a href="{html.escape(site)}" style="color:#6b7280">打开网页版</a>'
        if site else ""
    )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f9fafb">
  <div style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px 22px">
    <div style="font-size:18px;font-weight:700">{html.escape(title)}</div>
    <div style="color:#6b7280;font-size:12px;margin-top:4px">{today} · WHU Notice Hub</div>
    {body or '<p style="color:#6b7280;font-size:13px">今天没有新通知。</p>'}
    <div style="color:#9ca3af;font-size:11px;margin-top:24px;border-top:1px solid #e5e7eb;padding-top:10px">
      信息来自武汉大学各公开网站，仅供个人参考，一切以官网原文为准。<br>
      {site_link}
    </div>
  </div>
</body></html>"""


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, args))


def default_subscription(conn: sqlite3.Connection) -> int:
    """确保存在默认邮件订阅，返回其 id。"""
    row = conn.execute("SELECT id FROM subscriptions WHERE name='默认邮件'").fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO subscriptions (name, channel, target, rules_json, enabled)
           VALUES ('默认邮件','email',?, '{}', 1)""",
        (os.getenv("MAIL_TO") or os.getenv("SMTP_USER") or "me@example.com",),
    )
    conn.commit()
    return int(cur.lastrowid)


# --------------------------------------------------------------------------
# 即时推送
# --------------------------------------------------------------------------
def push_high_importance(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """把未推送过的高重要度通知合成一封邮件发出。"""
    sub_id = default_subscription(conn)
    threshold = int(os.getenv("PUSH_MIN_IMPORTANCE", "75"))
    rows = _rows(conn, """
        SELECT n.*, s.name AS source_name
          FROM notices n
          LEFT JOIN sources s ON s.code = n.source_code
          LEFT JOIN deliveries d ON d.notice_id = n.id AND d.subscription_id = ?
         WHERE d.id IS NULL
           AND n.importance >= ?
           AND n.status IN ('new','updated')
           AND (n.published_at >= date('now','-7 day')
                OR n.first_seen_at >= datetime('now','-7 day'))
         ORDER BY n.importance DESC, n.published_at DESC LIMIT 20
    """, (sub_id, threshold))
    if not rows:
        return 0

    title = f"【武大通知】{len(rows)} 条重要通知"
    html_body = build_html(title, [("需要关注", rows)])

    if dry_run:
        log.info("dry-run 待推送 %s 条", len(rows))
        return len(rows)

    if not mailer.is_configured():
        log.warning("SMTP 未配置，跳过推送（%s 条待推送）", len(rows))
        return 0

    mailer.send_email(title, html_body)
    for row in rows:
        conn.execute(
            """INSERT OR IGNORE INTO deliveries (notice_id, subscription_id, channel, kind, status, sent_at)
               VALUES (?,?, 'email','instant','sent', datetime('now','localtime'))""",
            (row["id"], sub_id),
        )
    conn.commit()
    log.info("即时推送完成：%s 条", len(rows))
    return len(rows)


# --------------------------------------------------------------------------
# 日报
# --------------------------------------------------------------------------
def digest_marker() -> Path:
    return DATA_DIR / "last_digest.txt"


def build_digest(conn: sqlite3.Connection) -> tuple[str, str]:
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    new_rows = _rows(conn, """
        SELECT n.*, s.name AS source_name
          FROM notices n LEFT JOIN sources s ON s.code = n.source_code
         WHERE coalesce(n.published_at, n.first_seen_at) >= ?
         ORDER BY n.importance DESC, n.published_at DESC LIMIT 30
    """, (since,))
    deadline_rows = _rows(conn, """
        SELECT n.*, s.name AS source_name
          FROM notices n LEFT JOIN sources s ON s.code = n.source_code
         WHERE n.deadline_date IS NOT NULL
           AND n.deadline_date >= date('now')
           AND n.deadline_date <= date('now','+7 day')
         ORDER BY n.deadline_date ASC LIMIT 20
    """)
    title = "武大通知日报"
    html_body = build_html(title, [("过去 24 小时新增", new_rows), ("未来 7 天截止", deadline_rows)])
    return title, html_body


def send_digest(conn: sqlite3.Connection, force: bool = False, dry_run: bool = False) -> bool:
    today = date.today().isoformat()
    marker = digest_marker()
    if not force and marker.exists() and marker.read_text().strip() == today:
        log.info("今日日报已发送，跳过")
        return False

    title, html_body = build_digest(conn)
    if dry_run:
        print(html_body)
        return True
    if not mailer.is_configured():
        log.warning("SMTP 未配置，日报未发送")
        return False

    mailer.send_email(title, html_body)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(today)
    log.info("日报已发送")
    return True

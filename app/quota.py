"""AI 问答用量限额：每人/每群/全站每日次数 + 最小间隔。"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import date

from . import db

# 进程内记录上次提问时间，用于最小间隔
_last_ask: dict[str, float] = {}


def limits() -> tuple[int, int, int, int]:
    """返回 (每人每日, 每群每日, 全站每日, 最小间隔秒)。"""
    return (
        int(os.getenv("AI_DAILY_LIMIT_PER_USER", "10")),
        int(os.getenv("AI_DAILY_LIMIT_PER_GROUP", "50")),
        int(os.getenv("AI_DAILY_LIMIT_TOTAL", "300")),
        int(os.getenv("AI_MIN_INTERVAL_SECONDS", "5")),
    )


def _get(conn: sqlite3.Connection, day: str, scope: str) -> int:
    row = conn.execute(
        "SELECT count FROM ai_usage WHERE day=? AND scope=?", (day, scope)
    ).fetchone()
    return int(row["count"]) if row else 0


def _inc(conn: sqlite3.Connection, day: str, scope: str) -> int:
    conn.execute(
        """INSERT INTO ai_usage (day, scope, count, updated_at)
           VALUES (?,?,1, datetime('now','localtime'))
           ON CONFLICT(day, scope) DO UPDATE SET
             count = count + 1, updated_at = datetime('now','localtime')""",
        (day, scope),
    )
    return _get(conn, day, scope)


def consume(user_id: str, group_id: str | None = None, day: str | None = None) -> tuple[bool, str]:
    """尝试消耗一次额度。返回 (是否允许, 拒绝原因)。"""
    day = day or date.today().isoformat()
    per_user, per_group, total, min_interval = limits()
    uid = user_id or "unknown"

    # 最小间隔（防止连刷）
    now = time.monotonic()
    last = _last_ask.get(uid, 0.0)
    if min_interval > 0 and now - last < min_interval:
        wait = int(min_interval - (now - last)) + 1
        return False, f"别急，{wait} 秒后再问吧～"

    conn = db.connect()
    try:
        if _get(conn, day, f"user:{uid}") >= per_user:
            return False, (
                f"你今天已经问满 {per_user} 次啦，明天再来～\n"
                "发送「日报」仍然可以查看全部近期通知。"
            )
        if group_id and _get(conn, day, f"group:{group_id}") >= per_group:
            return False, f"本群今天的 AI 问答额度（{per_group} 次）用完了，明天恢复～"
        if _get(conn, day, "total") >= total:
            return False, "今天全站 AI 问答额度已用完，明天恢复～发送「日报」仍可查看通知。"

        _inc(conn, day, f"user:{uid}")
        if group_id:
            _inc(conn, day, f"group:{group_id}")
        _inc(conn, day, "total")
        conn.commit()
        _last_ask[uid] = now
        return True, ""
    finally:
        conn.close()


def remaining(user_id: str, day: str | None = None) -> tuple[int, int, int]:
    """返回 (个人剩余, 本群剩余, 全站剩余)；群剩余需另传 group_id，这里只给个人与全站。"""
    day = day or date.today().isoformat()
    per_user, _per_group, total, _ = limits()
    conn = db.connect()
    try:
        used_user = _get(conn, day, f"user:{user_id}")
        used_total = _get(conn, day, "total")
    finally:
        conn.close()
    return max(0, per_user - used_user), max(0, total - used_total), used_total


def usage_today(day: str | None = None) -> list[sqlite3.Row]:
    day = day or date.today().isoformat()
    conn = db.connect()
    try:
        return list(conn.execute(
            "SELECT day, scope, count, updated_at FROM ai_usage WHERE day=? ORDER BY count DESC",
            (day,),
        ))
    finally:
        conn.close()

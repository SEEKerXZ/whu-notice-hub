"""FastAPI 只读前端 + JSON API。"""
from __future__ import annotations

import base64
import json
import os
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from . import config  # noqa: F401  加载 .env
from . import db

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="WHU Notice Hub", version="0.1.0",
              description="武汉大学本科生通知聚合 · 公开只读服务")

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
_hits: dict[str, list[float]] = defaultdict(list)
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """轻量限流：每个 IP 每分钟最多 N 次，防止公开后被刷。"""
    if request.url.path in ("/healthz", "/rss.xml"):
        return await call_next(request)
    ip = request.client.host if request.client else "unknown"
    now_ts = time.time()
    if len(_hits) > 5000:  # 简单防内存膨胀
        _hits.clear()
    bucket = _hits[ip]
    while bucket and now_ts - bucket[0] > 60:
        bucket.pop(0)
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        return Response(status_code=429, content="请求过于频繁，请稍后再试")
    bucket.append(now_ts)
    return await call_next(request)


def _conn():
    return db.connect()


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """设置了 WEB_USER / WEB_PASSWORD 时启用 HTTP Basic 认证（/healthz 除外）。"""
    user = os.getenv("WEB_USER", "").strip()
    password = os.getenv("WEB_PASSWORD", "").strip()
    if not user or not password or request.url.path == "/healthz":
        return await call_next(request)

    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
        except Exception:  # noqa: BLE001
            decoded = ""
        got_user, _, got_password = decoded.partition(":")
        if got_user == user and got_password == password:
            return await call_next(request)
    return Response(
        status_code=401,
        content="需要登录",
        headers={"WWW-Authenticate": 'Basic realm="WHU Notice Hub"'},
    )


def _categories() -> list[str]:
    conn = _conn()
    rows = conn.execute("SELECT DISTINCT category FROM notices ORDER BY category").fetchall()
    conn.close()
    return [r["category"] for r in rows]


def _overview(conn) -> dict:
    """首页概览：今日新增、7 天内截止、来源分布、分类分布、重点通知。"""
    today = conn.execute(
        """SELECT COUNT(*) c FROM notices
            WHERE date(COALESCE(published_at, first_seen_at)) = date('now','localtime')"""
    ).fetchone()["c"]
    upcoming = conn.execute(
        """SELECT COUNT(*) c FROM notices
            WHERE deadline_date BETWEEN date('now','localtime')
                                    AND date('now','localtime','+7 day')"""
    ).fetchone()["c"]
    source_counts = [
        dict(r) for r in conn.execute(
            """SELECT s.code, s.name, COUNT(n.id) AS c
                 FROM sources s LEFT JOIN notices n ON n.source_code = s.code
                WHERE s.enabled = 1 GROUP BY s.code ORDER BY s.weight DESC"""
        )
    ]
    category_counts = [
        dict(r) for r in conn.execute(
            "SELECT category, COUNT(*) AS c FROM notices GROUP BY category ORDER BY c DESC"
        )
    ]
    important = [
        dict(r) for r in conn.execute(
            """SELECT n.id, n.title, n.importance, n.category, n.published_at,
                      n.deadline_date, s.name AS source_name
                 FROM notices n LEFT JOIN sources s ON s.code = n.source_code
                WHERE n.importance >= 55
                ORDER BY n.importance DESC, COALESCE(n.published_at, n.first_seen_at) DESC
                LIMIT 3"""
        )
    ]
    return {"today_new": today, "upcoming": upcoming,
            "source_counts": source_counts, "category_counts": category_counts,
            "important": important}


def _rfc822(d: date) -> str:
    return (f"{_WEEKDAYS[d.weekday()]}, {d.day:02d} {_MONTHS[d.month - 1]} "
            f"{d.year} 09:00:00 +0800")


@app.get("/healthz")
def healthz() -> dict:
    conn = _conn()
    try:
        total = db.count_notices(conn)
        return {"ok": True, "notices": total}
    finally:
        conn.close()


@app.get("/api/notices")
def api_notices(source: str | None = None, category: str | None = None,
                q: str | None = None, min_score: int | None = None,
                deadline: int = 0, limit: int = 50, offset: int = 0) -> JSONResponse:
    conn = _conn()
    try:
        rows = db.query_notices(
            conn, source=source, category=category, q=q, min_score=min_score,
            has_deadline=bool(deadline), limit=min(limit, 200), offset=offset,
        )
        data = [dict(r) for r in rows]
        for item in data:
            for key in ("audience_json", "action_items_json"):
                try:
                    item[key] = json.loads(item.get(key) or "[]")
                except json.JSONDecodeError:
                    item[key] = []
        return JSONResponse({"count": len(data), "data": data})
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, source: str | None = None, category: str | None = None,
          q: str | None = None, min_score: int | None = None, deadline: int = 0,
          page: int = 1, size: int = 30):
    conn = _conn()
    try:
        rows = db.query_notices(
            conn, source=source, category=category, q=q, min_score=min_score,
            has_deadline=bool(deadline), limit=size, offset=(page - 1) * size,
        )
        items = [dict(r) for r in rows]
        for item in items:
            try:
                item["audience"] = json.loads(item.get("audience_json") or "[]")
            except json.JSONDecodeError:
                item["audience"] = []
        sources = list(conn.execute(
            "SELECT code, name FROM sources WHERE enabled=1 ORDER BY weight DESC"))
        total = db.count_notices(conn)
        overview = _overview(conn) if not any([source, category, q, min_score, deadline]) else None
    finally:
        conn.close()

    return templates.TemplateResponse(request, "index.html", {
        "items": items, "sources": sources,
        "categories": _categories(), "total": total, "overview": overview,
        "filters": {"source": source or "", "category": category or "",
                    "q": q or "", "min_score": min_score or "", "deadline": deadline},
        "page": page, "size": size,
        "has_next": len(items) == size,
    })


@app.get("/rss.xml")
def rss(limit: int = 50) -> Response:
    """最新通知的 RSS 订阅源，方便用阅读器跟进。"""
    conn = _conn()
    try:
        rows = db.query_notices(conn, limit=min(limit, 200))
    finally:
        conn.close()

    entries = []
    for r in rows:
        pub = r["published_at"] or (r["first_seen_at"] or "")[:10]
        try:
            pub_date = _rfc822(datetime.strptime(pub[:10], "%Y-%m-%d").date())
        except ValueError:
            pub_date = ""
        entries.append(
            "<item>"
            f"<title>{escape(r['title'] or '')}</title>"
            f"<link>{escape(r['url'])}</link>"
            f"<guid isPermaLink=\"true\">{escape(r['url'])}</guid>"
            f"<pubDate>{pub_date}</pubDate>"
            f"<description>{escape(r['summary'] or '')}</description>"
            "</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>WHU Notice Hub · 本科生通知</title>"
        "<link>http://localhost/</link>"
        "<description>武汉大学本科生相关通知聚合</description>"
        "<language>zh-CN</language>"
        + "".join(entries) +
        "</channel></rss>"
    )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/notice/{notice_id}", response_class=HTMLResponse)
def notice_detail(request: Request, notice_id: int):
    conn = _conn()
    try:
        row = conn.execute(
            """SELECT n.*, s.name AS source_name FROM notices n
                 LEFT JOIN sources s ON s.code = n.source_code WHERE n.id=?""",
            (notice_id,),
        ).fetchone()
        if not row:
            return HTMLResponse("<h1>404</h1><p>通知不存在</p>", status_code=404)
        item = dict(row)
        item["audience"] = json.loads(item.get("audience_json") or "[]")
        item["action_items"] = json.loads(item.get("action_items_json") or "[]")
        attachments = [dict(a) for a in conn.execute(
            "SELECT name, url FROM attachments WHERE notice_id=?", (notice_id,))]
        versions = [dict(v) for v in conn.execute(
            "SELECT fetched_at, diff_summary FROM notice_versions WHERE notice_id=? ORDER BY id DESC LIMIT 5",
            (notice_id,))]
    finally:
        conn.close()
    return templates.TemplateResponse(request, "notice.html", {
        "n": item, "attachments": attachments, "versions": versions,
    })

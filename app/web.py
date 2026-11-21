"""FastAPI 前端（公开只读） + JSON API + RSS。"""
from __future__ import annotations

import base64
import json
import os
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config  # noqa: F401  加载 .env
from . import db

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 分类配色：用于标签小圆点/胶囊
CATEGORY_CLASS = {
    "招生": "c-blue", "考试": "c-red", "奖助": "c-amber", "教务": "c-violet",
    "公示": "c-slate", "生活服务": "c-green", "竞赛": "c-pink",
    "科研": "c-cyan", "人事": "c-gray", "招聘": "c-gray", "讲座": "c-indigo",
    "会议": "c-gray", "其他": "c-gray",
}


def _cat_class(value: object) -> str:
    return CATEGORY_CLASS.get(str(value), "c-gray")


def _days_left(value: object) -> int | None:
    """截止日期距今天数；已过期为负数。"""
    if not value:
        return None
    try:
        return (date.fromisoformat(str(value)[:10]) - date.today()).days
    except ValueError:
        return None


templates.env.filters["cat_class"] = _cat_class
templates.env.filters["days_left"] = _days_left

# 重要度只展示大类，不显示具体分数
LEVELS: list[tuple[int, str, str]] = [
    (60, "重要", "lv-hi"),
    (40, "一般", "lv-mid"),
    (0, "参考", "lv-low"),
]
LEVEL_TO_MIN_SCORE = {"high": 60, "mid": 40, "low": 0}


def _level_label(score: object) -> str:
    try:
        s = int(score or 0)
    except (TypeError, ValueError):
        s = 0
    for threshold, label, _cls in LEVELS:
        if s >= threshold:
            return label
    return "参考"


def _level_class(score: object) -> str:
    try:
        s = int(score or 0)
    except (TypeError, ValueError):
        s = 0
    for threshold, _label, cls in LEVELS:
        if s >= threshold:
            return cls
    return "lv-low"


templates.env.filters["level_label"] = _level_label
templates.env.filters["level_class"] = _level_class

app = FastAPI(title="WHU Notice Hub", version="0.1.0",
              description="武汉大学本科生通知聚合 · 公开只读服务")

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
_hits: dict[str, list[float]] = defaultdict(list)
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------
@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """轻量限流：每个 IP 每分钟最多 N 次，防止公开后被刷。"""
    if request.url.path in ("/healthz", "/rss.xml", "/sitemap.xml"):
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


# ---------------------------------------------------------------------------
# 通用查询
# ---------------------------------------------------------------------------
def _conn():
    return db.connect()


def _categories(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT category, COUNT(*) AS c FROM notices
            WHERE status <> 'archived' GROUP BY category ORDER BY c DESC""")]


def _sources(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT s.code, s.name, COUNT(n.id) AS c
             FROM sources s LEFT JOIN notices n ON n.source_code = s.code AND n.status <> 'archived'
            WHERE s.enabled = 1 GROUP BY s.code ORDER BY s.weight DESC""")]


def _overview(conn) -> dict:
    """首页概览：今日新增、7 天内截止、来源分布、分类分布、重点通知。"""
    today = conn.execute(
        """SELECT COUNT(*) c FROM notices
            WHERE status <> 'archived'
              AND date(COALESCE(published_at, first_seen_at)) = date('now','localtime')"""
    ).fetchone()["c"]
    upcoming = conn.execute(
        """SELECT COUNT(*) c FROM notices
            WHERE status <> 'archived'
              AND deadline_date BETWEEN date('now','localtime')
                                    AND date('now','localtime','+7 day')"""
    ).fetchone()["c"]
    important = [
        dict(r) for r in conn.execute(
            """SELECT n.id, n.title, n.importance, n.category, n.published_at,
                      n.deadline_date, s.name AS source_name
                 FROM notices n LEFT JOIN sources s ON s.code = n.source_code
                WHERE n.importance >= 55 AND n.status <> 'archived'
                ORDER BY n.importance DESC, COALESCE(n.published_at, n.first_seen_at) DESC
                LIMIT 3"""
        )
    ]
    return {"today_new": today, "upcoming": upcoming,
            "source_counts": _sources(conn), "category_counts": _categories(conn),
            "important": important}


def _decorate(items: list[dict]) -> list[dict]:
    for item in items:
        try:
            item["audience"] = json.loads(item.get("audience_json") or "[]")
        except json.JSONDecodeError:
            item["audience"] = []
    return items


def _rfc822(d: date) -> str:
    return (f"{_WEEKDAYS[d.weekday()]}, {d.day:02d} {_MONTHS[d.month - 1]} "
            f"{d.year} 09:00:00 +0800")


def _list_response(request: Request, *, page_title: str, base_path: str,
                   source: str | None = None, category: str | None = None,
                   q: str | None = None, min_score: int | None = None,
                   deadline: int = 0, month: str | None = None,
                   page: int = 1, size: int = 30, show_overview: bool = False,
                   level: str | None = None):
    page = max(1, page)
    conn = _conn()
    try:
        rows = db.query_notices(
            conn, source=source, category=category, q=q, min_score=min_score,
            has_deadline=bool(deadline), month=month,
            limit=size, offset=(page - 1) * size,
        )
        items = _decorate([dict(r) for r in rows])
        total = db.count_notices(conn)
        overview = _overview(conn) if show_overview else None
        sources = _sources(conn)
        categories = _categories(conn)
    finally:
        conn.close()

    filters = {"source": source or "", "category": category or "",
               "q": q or "", "min_score": min_score or "",
               "deadline": deadline, "month": month or "", "level": level or ""}
    return templates.TemplateResponse(request, "index.html", {
        "items": items, "sources": sources, "categories": categories,
        "total": total, "overview": overview, "filters": filters,
        "page": page, "size": size, "has_next": len(items) == size,
        "page_title": page_title, "base_path": base_path,
    })


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, source: str | None = None, category: str | None = None,
          q: str | None = None, level: str | None = None, min_score: int | None = None,
          deadline: int = 0, page: int = 1, size: int = 30):
    title = "全部通知"
    if q:
        title = f"搜索：{q}"
    min_score = LEVEL_TO_MIN_SCORE.get((level or "").lower(), min_score)
    return _list_response(
        request, page_title=title, base_path="/",
        source=source, category=category, q=q, min_score=min_score,
        deadline=deadline, page=page, size=size, level=level,
        show_overview=not any([source, category, q, min_score, deadline]),
    )


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    return RedirectResponse(f"/?q={quote(q)}", status_code=307)


@app.get("/category/{category}", response_class=HTMLResponse)
def category_page(request: Request, category: str, page: int = 1, size: int = 30):
    return _list_response(request, page_title=f"{category} · 分类",
                          base_path=f"/category/{quote(category)}",
                          category=category, page=page, size=size)


@app.get("/source/{code}", response_class=HTMLResponse)
def source_page(request: Request, code: str, page: int = 1, size: int = 30):
    return _list_response(request, page_title=f"{code} · 信源",
                          base_path=f"/source/{quote(code)}",
                          source=code, page=page, size=size)


@app.get("/archive", response_class=HTMLResponse)
def archive(request: Request):
    conn = _conn()
    try:
        months = [dict(r) for r in db.month_counts(conn)]
        total = db.count_notices(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "archive.html", {
        "months": months, "total": total,
    })


@app.get("/archive/{month}", response_class=HTMLResponse)
def archive_month(request: Request, month: str, page: int = 1, size: int = 30):
    return _list_response(request, page_title=f"{month} · 归档",
                          base_path=f"/archive/{quote(month)}",
                          month=month, page=page, size=size)


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    conn = _conn()
    try:
        total = db.count_notices(conn)
        sources = _sources(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "about.html", {
        "total": total, "sources": sources,
    })


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
            return templates.TemplateResponse(request, "404.html",
                                              {"path": request.url.path}, status_code=404)
        item = dict(row)
        item["audience"] = json.loads(item.get("audience_json") or "[]")
        item["action_items"] = json.loads(item.get("action_items_json") or "[]")
        attachments = [dict(a) for a in conn.execute(
            "SELECT name, url FROM attachments WHERE notice_id=?", (notice_id,))]
        versions = [dict(v) for v in conn.execute(
            "SELECT fetched_at, diff_summary FROM notice_versions WHERE notice_id=? ORDER BY id DESC LIMIT 5",
            (notice_id,))]

        cursor = "COALESCE(n.published_at, n.first_seen_at)"
        prev_row = conn.execute(
            f"""SELECT id, title FROM notices n WHERE {cursor} > ?
                 ORDER BY {cursor} ASC LIMIT 1""",
            (item["published_at"] or item["first_seen_at"],)).fetchone()
        next_row = conn.execute(
            f"""SELECT id, title FROM notices n WHERE {cursor} < ?
                 ORDER BY {cursor} DESC LIMIT 1""",
            (item["published_at"] or item["first_seen_at"],)).fetchone()
        related = _decorate([dict(r) for r in conn.execute(
            """SELECT n.id, n.title, n.importance, n.category, n.published_at
                 FROM notices n WHERE n.category=? AND n.id<>?
                ORDER BY COALESCE(n.published_at, n.first_seen_at) DESC LIMIT 5""",
            (item["category"], notice_id))])
    finally:
        conn.close()
    return templates.TemplateResponse(request, "notice.html", {
        "n": item, "attachments": attachments, "versions": versions,
        "prev": dict(prev_row) if prev_row else None,
        "next": dict(next_row) if next_row else None,
        "related": related,
    })


# ---------------------------------------------------------------------------
# 机器可读接口
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> dict:
    conn = _conn()
    try:
        return {"ok": True, "notices": db.count_notices(conn)}
    finally:
        conn.close()


@app.get("/api/notices")
def api_notices(source: str | None = None, category: str | None = None,
                q: str | None = None, min_score: int | None = None,
                deadline: int = 0, month: str | None = None,
                limit: int = 50, offset: int = 0) -> JSONResponse:
    conn = _conn()
    try:
        rows = db.query_notices(
            conn, source=source, category=category, q=q, min_score=min_score,
            has_deadline=bool(deadline), month=month,
            limit=min(limit, 200), offset=offset,
        )
        data = [dict(r) for r in rows]
        for item in data:
            item["level"] = _level_label(item.get("importance"))
            for key in ("audience_json", "action_items_json"):
                try:
                    item[key] = json.loads(item.get(key) or "[]")
                except json.JSONDecodeError:
                    item[key] = []
        return JSONResponse({"count": len(data), "data": data})
    finally:
        conn.close()


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
            f'<guid isPermaLink="true">{escape(r["url"])}</guid>'
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


@app.get("/sitemap.xml")
def sitemap() -> Response:
    conn = _conn()
    try:
        rows = conn.execute("SELECT id FROM notices ORDER BY id DESC LIMIT 2000").fetchall()
    finally:
        conn.close()
    urls = "".join(f"<url><loc>/notice/{r['id']}</loc></url>" for r in rows)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{urls}</urlset>")
    return Response(content=xml, media_type="application/xml; charset=utf-8")


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(request, "404.html",
                                          {"path": request.url.path}, status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

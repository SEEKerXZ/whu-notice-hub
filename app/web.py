"""FastAPI 只读前端 + JSON API。"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from . import config  # noqa: F401  加载 .env
from . import db

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="WHU Notice Hub", version="0.1.0",
              description="武汉大学通知聚合 · W1 只读版本")


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
    finally:
        conn.close()

    return templates.TemplateResponse(request, "index.html", {
        "items": items, "sources": sources,
        "categories": _categories(), "total": total,
        "filters": {"source": source or "", "category": category or "",
                    "q": q or "", "min_score": min_score or "", "deadline": deadline},
        "page": page, "size": size,
        "has_next": len(items) == size,
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

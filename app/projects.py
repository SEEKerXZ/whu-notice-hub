"""项目分享：数据库存储 + 一键投稿。

投稿方式：
1. QQ 群 @通通 发「投稿 <GitHub 链接> [一句话介绍]」
2. 网页 /projects/new（需要 .env 里配置 PROJECT_SUBMIT_KEY）
3. CLI: python -m app.cli project-add <链接>
GitHub 链接会自动抓取仓库名与简介，失败则用链接兜底。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3

import httpx

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"'）)，。]+")
GITHUB_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s#?]+)")

SUBMIT_WORDS = ("投稿项目", "投项目", "加项目", "推荐项目", "投稿", "收录项目")


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS projects (
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               name        TEXT NOT NULL,
               url         TEXT NOT NULL UNIQUE,
               description TEXT,
               author      TEXT,
               status      TEXT NOT NULL DEFAULT 'active',
               created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
           )"""
    )
    conn.commit()


def normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("".join(["）", ")", "，", ",", "。", ".", "】", "]"]))
    if url.startswith("github.com/"):
        url = "https://" + url
    return url.rstrip("/")


def parse_github(url: str) -> tuple[str, str] | None:
    m = GITHUB_RE.match(normalize_url(url))
    if not m:
        return None
    return m.group(1), m.group(2)


def fetch_github_meta(url: str, timeout: float = 6.0) -> dict | None:
    """抓 GitHub 仓库信息；失败返回 None（不阻塞投稿）。"""
    if os.getenv("PROJECTS_NO_FETCH") == "1":
        return None
    repo = parse_github(url)
    if not repo:
        return None
    owner, name = repo
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(
                f"https://api.github.com/repos/{owner}/{name}",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "whu-notice-hub"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
        return {
            "name": data.get("name") or name,
            "description": (data.get("description") or "").strip(),
            "author": owner,
            "stars": data.get("stargazers_count"),
        }
    except Exception:  # noqa: BLE001
        log.info("GitHub 元信息抓取失败: %s", url)
        return None


def listing(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    ensure_table(conn)
    return list(conn.execute(
        "SELECT * FROM projects WHERE status='active' ORDER BY id DESC LIMIT ?",
        (limit,),
    ))


def add(conn: sqlite3.Connection, url: str, name: str | None = None,
        description: str | None = None, author: str | None = None,
        fetch_meta: bool = True) -> tuple[bool, str]:
    """返回 (是否新增, 提示语)。"""
    ensure_table(conn)
    url = normalize_url(url)
    if not url.startswith(("http://", "https://")):
        return False, "链接格式不对，需要以 http(s):// 开头"

    exists = conn.execute("SELECT id FROM projects WHERE url=?", (url,)).fetchone()
    if exists:
        return False, "这个项目已经在列表里了"

    meta = fetch_github_meta(url) if fetch_meta else None
    repo_name = None
    if meta:
        repo_name = meta["name"]
        name = name or repo_name
        description = description or meta.get("description")
        author = author or meta.get("author")
    if not name:
        name = url.rstrip("/").rsplit("/", 1)[-1] or url

    conn.execute(
        "INSERT INTO projects (name, url, description, author) VALUES (?,?,?,?)",
        (name[:120], url, (description or "")[:300], (author or "")[:60]),
    )
    conn.commit()
    return True, f"已收录：{name}"


def remove(conn: sqlite3.Connection, url_or_id: str) -> bool:
    ensure_table(conn)
    if url_or_id.isdigit():
        cur = conn.execute("DELETE FROM projects WHERE id=?", (int(url_or_id),))
    else:
        cur = conn.execute("DELETE FROM projects WHERE url=?", (normalize_url(url_or_id),))
    conn.commit()
    return cur.rowcount > 0


def parse_submission(text: str | None) -> tuple[str, str] | None:
    """从「投稿 <链接> [介绍]」里解析出 (url, 描述)。"""
    content = (text or "").strip()
    if not content:
        return None
    matched = False
    for word in SUBMIT_WORDS:
        if content.startswith(word):
            content = content[len(word):].strip(" ：:，,")
            matched = True
            break
    if not matched:
        return None
    m = URL_RE.search(content)
    if not m:
        return None
    url = m.group(0)
    desc = (content[: m.start()] + " " + content[m.end():]).strip(" ：:，,")
    return normalize_url(url), desc[:200]

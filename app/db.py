"""SQLite 数据访问层。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / "db" / "schema.sql"
DEFAULT_DB = ROOT / "data" / "app.db"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or os.getenv("DB_PATH") or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ai_usage (
               day        TEXT NOT NULL,
               scope      TEXT NOT NULL,
               count      INTEGER NOT NULL DEFAULT 0,
               updated_at TEXT,
               PRIMARY KEY (day, scope)
           )"""
    )
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：给老库补新列。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(notices)")}
    if "restricted" not in cols:
        conn.execute("ALTER TABLE notices ADD COLUMN restricted INTEGER NOT NULL DEFAULT 0")
    if "fallback_url" not in cols:
        conn.execute("ALTER TABLE notices ADD COLUMN fallback_url TEXT")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------
def upsert_source(conn: sqlite3.Connection, code: str, name: str, level: str,
                  list_url: str, weight: int, enabled: bool, interval: int,
                  config: dict | None = None) -> None:
    conn.execute(
        """INSERT INTO sources (code, name, level, list_url, weight, enabled, interval_minutes, config_json)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(code) DO UPDATE SET
             name=excluded.name, level=excluded.level, list_url=excluded.list_url,
             weight=excluded.weight, enabled=excluded.enabled,
             interval_minutes=excluded.interval_minutes, config_json=excluded.config_json""",
        (code, name, level, list_url, weight, int(enabled), interval,
         json.dumps(config or {}, ensure_ascii=False)),
    )
    conn.commit()


def mark_source_result(conn: sqlite3.Connection, code: str, ok: bool, error: str | None = None) -> None:
    if ok:
        conn.execute(
            "UPDATE sources SET last_ok_at=?, consecutive_failures=0, status='ok' WHERE code=?",
            (now(), code),
        )
    else:
        conn.execute(
            """UPDATE sources SET last_error_at=?,
                 consecutive_failures=consecutive_failures+1,
                 status=CASE WHEN consecutive_failures+1>=3 THEN 'broken' ELSE 'degraded' END
               WHERE code=?""",
            (now(), code),
        )
    conn.commit()


# --------------------------------------------------------------------------
# crawl_runs
# --------------------------------------------------------------------------
def start_run(conn: sqlite3.Connection, source_code: str, mode: str = "incremental") -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs (source_code, mode, status) VALUES (?,?,'running')",
        (source_code, mode),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, **stats) -> None:
    conn.execute(
        """UPDATE crawl_runs SET finished_at=?, status=?, pages_fetched=?, items_seen=?,
             items_new=?, items_updated=?, http_errors=?, parse_errors=?, error=?
           WHERE id=?""",
        (
            now(),
            stats.get("status", "ok"),
            stats.get("pages", 0),
            stats.get("seen", 0),
            stats.get("new", 0),
            stats.get("updated", 0),
            stats.get("http_errors", 0),
            stats.get("parse_errors", 0),
            stats.get("error"),
            run_id,
        ),
    )
    conn.commit()


# --------------------------------------------------------------------------
# notices
# --------------------------------------------------------------------------
def known_hashes(conn: sqlite3.Connection, source_code: str, days: int = 180) -> set[str]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT url_hash FROM notices WHERE source_code=? AND (published_at IS NULL OR published_at>=?)",
        (source_code, since),
    )
    return {r["url_hash"] for r in rows}


def get_notice(conn: sqlite3.Connection, url_hash: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM notices WHERE url_hash=?", (url_hash,)).fetchone()


def save_notice(conn: sqlite3.Connection, payload: dict) -> str:
    """插入或更新通知，返回 new / updated / unchanged / duplicate。"""
    existing = get_notice(conn, payload["url_hash"])
    if existing is None:
        # 同一通知常被发布在多个栏目（如"通知公告"和"党建"），按标题+发布日期去重
        dup = conn.execute(
            """SELECT id FROM notices
                WHERE title_norm = ?
                  AND url_hash <> ?
                  AND COALESCE(published_at, '') = COALESCE(?, '')
                LIMIT 1""",
            (payload.get("title_norm", ""), payload["url_hash"], payload.get("published_at")),
        ).fetchone()
        if dup is not None:
            return "duplicate"

        status = payload.get("status", "new")
        conn.execute(
            """INSERT INTO notices
                 (source_code, url, url_hash, title, title_norm, publisher, published_at,
                  date_inferred, category, summary, content_md, content_hash, audience_json,
                  action_items_json, deadline_date, importance, status, restricted, fallback_url,
                  first_seen_at, last_seen_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload["source_code"], payload["url"], payload["url_hash"],
                payload["title"], payload["title_norm"], payload.get("publisher"),
                payload.get("published_at"), int(payload.get("date_inferred", 0)),
                payload.get("category", "其他"), payload.get("summary"),
                payload.get("content_md"), payload.get("content_hash"),
                json.dumps(payload.get("audience", []), ensure_ascii=False),
                json.dumps(payload.get("action_items", []), ensure_ascii=False),
                payload.get("deadline_date"),
                int(payload.get("importance", 50)), status,
                int(payload.get("restricted", 0)), payload.get("fallback_url"),
                now(), now(), now(),
            ),
        )
        conn.commit()
        return "new"

    if payload.get("content_hash") and payload["content_hash"] != existing["content_hash"]:
        conn.execute(
            """UPDATE notices SET title=?, title_norm=?, publisher=?, published_at=?,
                 category=?, summary=?, content_md=?, content_hash=?, audience_json=?,
                 action_items_json=?, deadline_date=?, importance=?, status='updated',
                 last_seen_at=?, updated_at=?
               WHERE id=?""",
            (
                payload["title"], payload["title_norm"], payload.get("publisher"),
                payload.get("published_at"), payload.get("category", "其他"),
                payload.get("summary"), payload.get("content_md"), payload["content_hash"],
                json.dumps(payload.get("audience", []), ensure_ascii=False),
                json.dumps(payload.get("action_items", []), ensure_ascii=False),
                payload.get("deadline_date"),
                int(payload.get("importance", 50)), now(), now(), existing["id"],
            ),
        )
        conn.execute(
            """INSERT OR IGNORE INTO notice_versions (notice_id, content_hash, title, diff_summary)
               VALUES (?,?,?,?)""",
            (existing["id"], payload["content_hash"], payload["title"], "正文有更新"),
        )
        conn.commit()
        return "updated"

    conn.execute("UPDATE notices SET last_seen_at=? WHERE id=?", (now(), existing["id"]))
    conn.commit()
    return "unchanged"


def save_attachments(conn: sqlite3.Connection, url_hash: str, attachments: list[dict]) -> int:
    row = get_notice(conn, url_hash)
    if not row or not attachments:
        return 0
    count = 0
    for att in attachments:
        h = text_hash(att["url"])
        cur = conn.execute(
            """INSERT OR IGNORE INTO attachments (notice_id, name, url, url_hash)
               VALUES (?,?,?,?)""",
            (row["id"], att.get("name"), att["url"], h),
        )
        count += cur.rowcount
    conn.commit()
    return count


def text_hash(value: str) -> str:
    import hashlib
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# 查询（Web 层用）
# --------------------------------------------------------------------------
def query_notices(conn: sqlite3.Connection, *, source: str | None = None,
                  category: str | None = None, q: str | None = None,
                  min_score: int | None = None, has_deadline: bool = False,
                  month: str | None = None,
                  limit: int = 50, offset: int = 0) -> list[sqlite3.Row]:
    sql = ["SELECT n.*, s.name AS source_name FROM notices n LEFT JOIN sources s ON s.code=n.source_code "
           "WHERE n.status <> 'archived'"]
    args: list = []
    if source:
        sql.append("AND n.source_code=?")
        args.append(source)
    if category:
        sql.append("AND n.category=?")
        args.append(category)
    if q:
        sql.append("AND (n.title LIKE ? OR n.content_md LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    if min_score:
        sql.append("AND n.importance>=?")
        args.append(min_score)
    if has_deadline:
        sql.append("AND n.deadline_date IS NOT NULL")
    if month:
        sql.append("AND substr(COALESCE(n.published_at, n.first_seen_at),1,7)=?")
        args.append(month)
    sql.append("ORDER BY COALESCE(n.published_at, n.first_seen_at) DESC, n.importance DESC")
    sql.append("LIMIT ? OFFSET ?")
    args += [limit, offset]
    return list(conn.execute(" ".join(sql), args))


def count_notices(conn: sqlite3.Connection) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) c FROM notices WHERE status <> 'archived'").fetchone()["c"])


def month_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """按月统计，用于归档页。"""
    return list(conn.execute(
        """SELECT substr(COALESCE(published_at, first_seen_at),1,7) AS month,
                  COUNT(*) AS c
             FROM notices
            WHERE status <> 'archived'
            GROUP BY month ORDER BY month DESC"""
    ))


def archived_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) c FROM notices WHERE status = 'archived'").fetchone()["c"])


def stats(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT s.code, s.name, s.status, s.last_ok_at,
                  COUNT(n.id) AS total,
                  MAX(n.published_at) AS latest
             FROM sources s LEFT JOIN notices n ON n.source_code=s.code
            GROUP BY s.code ORDER BY s.weight DESC"""
    ))

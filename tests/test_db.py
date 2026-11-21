"""数据层测试：受限通知（archived）不应出现在公开查询里。"""
import pytest

from app import db


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.upsert_source(c, "whu_main", "官网", "university",
                     "https://www.whu.edu.cn/tzgg.htm", 70, True, 20)
    yield c
    c.close()


def _payload(url: str, status: str = "new") -> dict:
    return {
        "source_code": "whu_main",
        "url": url,
        "url_hash": __import__("hashlib").sha1(url.encode()).hexdigest(),
        "title": "测试通知",
        "title_norm": "测试通知",
        "published_at": "2026-11-20",
        "category": "教务",
        "summary": None,
        "content_md": "",
        "content_hash": status,
        "audience": [],
        "action_items": [],
        "deadline_date": None,
        "importance": 0,
        "status": status,
    }


def test_archived_hidden_from_queries(conn):
    db.save_notice(conn, _payload("https://x/visible"))
    db.save_notice(conn, _payload("https://x/restricted", status="archived"))

    assert db.count_notices(conn) == 1
    assert db.archived_count(conn) == 1

    rows = db.query_notices(conn)
    assert [r["url"] for r in rows] == ["https://x/visible"]

    months = db.month_counts(conn)
    assert months[0]["c"] == 1


def test_archived_still_blocks_duplicate_fetch(conn):
    db.save_notice(conn, _payload("https://x/restricted", status="archived"))
    known = db.known_hashes(conn, "whu_main")
    import hashlib
    assert hashlib.sha1(b"https://x/restricted").hexdigest() in known

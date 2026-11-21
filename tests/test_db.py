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


def _payload(url: str, status: str = "new", title: str = "测试通知") -> dict:
    return {
        "source_code": "whu_main",
        "url": url,
        "url_hash": __import__("hashlib").sha1(url.encode()).hexdigest(),
        "title": title,
        "title_norm": title,
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
    db.save_notice(conn, _payload("https://x/visible", title="可见通知"))
    db.save_notice(conn, _payload("https://x/restricted", status="archived", title="隐藏通知"))

    assert db.count_notices(conn) == 1
    assert db.archived_count(conn) == 1

    rows = db.query_notices(conn)
    assert [r["url"] for r in rows] == ["https://x/visible"]

    months = db.month_counts(conn)
    assert months[0]["c"] == 1


def test_duplicate_title_same_day_rejected(conn):
    first = _payload("https://x/a1")
    second = _payload("https://x/a2")   # 不同 URL，但标题+日期相同
    assert db.save_notice(conn, first) == "new"
    assert db.save_notice(conn, second) == "duplicate"
    assert db.count_notices(conn) == 1


def test_restricted_notice_saved_with_fallback(conn):
    payload = _payload("https://x/locked", status="new")
    payload.update({
        "restricted": 1,
        "fallback_url": "https://x/list.htm",
        "summary": "该通知需校内权限查看",
        "content_md": "",
        "importance": 30,
    })
    db.save_notice(conn, payload)
    row = db.query_notices(conn)[0]
    assert row["restricted"] == 1
    assert row["fallback_url"] == "https://x/list.htm"

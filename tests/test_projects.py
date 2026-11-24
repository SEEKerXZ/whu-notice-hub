"""项目分享：投稿解析、入库、去重。"""
import pytest

from app import db, projects


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("PROJECTS_NO_FETCH", "1")
    c = db.connect()
    db.init_db(c)
    c.execute("DELETE FROM projects")   # 清掉种子数据，便于断言
    c.commit()
    yield c
    c.close()


def test_parse_submission():
    assert projects.parse_submission("投稿 https://github.com/a/b 一个工具") == (
        "https://github.com/a/b", "一个工具")
    assert projects.parse_submission("投稿项目 https://gitee.com/x/y") == (
        "https://gitee.com/x/y", "")
    assert projects.parse_submission("你好呀") is None
    assert projects.parse_submission("投稿 没有链接") is None
    assert projects.parse_submission(None) is None


def test_add_and_dedupe(conn):
    ok, msg = projects.add(conn, "https://github.com/a/b", description="工具", author="张三")
    assert ok is True
    assert "已收录" in msg
    again, msg2 = projects.add(conn, "https://github.com/a/b")
    assert again is False
    assert "已经在列表" in msg2
    rows = projects.listing(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == "b"          # 无元信息时用路径末段
    assert rows[0]["author"] == "张三"


def test_add_rejects_bad_url(conn):
    ok, msg = projects.add(conn, "not-a-url")
    assert ok is False
    assert "http" in msg


def test_normalize_and_github_parse():
    assert projects.normalize_url("https://github.com/a/b/") == "https://github.com/a/b"
    assert projects.parse_github("https://github.com/a/b") == ("a", "b")
    assert projects.parse_github("https://gitee.com/a/b") is None


def test_remove(conn):
    projects.add(conn, "https://github.com/a/b")
    row = projects.listing(conn)[0]
    assert projects.remove(conn, str(row["id"])) is True
    assert projects.listing(conn) == []

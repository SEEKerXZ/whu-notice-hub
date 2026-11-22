"""QQ 官方机器人测试：指令解析与回复文本生成。"""
import pytest

from app import db, qq_bot


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    c = db.connect()
    db.init_db(c)
    db.upsert_source(c, "cs_whu", "计算机学院·通知公告", "college",
                     "https://cs.whu.edu.cn/xwdt/tzgg.htm", 85, True, 60)
    db.save_notice(c, {
        "source_code": "cs_whu",
        "url": "https://cs.whu.edu.cn/info/1055/1.htm",
        "url_hash": "h1",
        "title": "关于2027届推免工作的通知",
        "title_norm": "关于2027届推免工作的通知",
        "published_at": "2026-11-21",
        "category": "招生",
        "summary": None,
        "content_md": "",
        "content_hash": "list-only",
        "audience": [],
        "action_items": [],
        "deadline_date": "2026-11-30",
        "importance": 70,
    })
    yield c
    c.close()


def test_parse_command():
    assert qq_bot.parse_command("日报") == "daily"
    assert qq_bot.parse_command("/日报") == "daily"
    assert qq_bot.parse_command("  今日摘要 ") == "daily"
    assert qq_bot.parse_command("重要") == "important"
    assert qq_bot.parse_command("你好") is None
    assert qq_bot.parse_command("") is None
    assert qq_bot.parse_command(None) is None


def test_is_configured(monkeypatch):
    monkeypatch.delenv("QQ_APPID", raising=False)
    monkeypatch.delenv("QQ_APPSECRET", raising=False)
    assert qq_bot.is_configured() is False
    monkeypatch.setenv("QQ_APPID", "102000000")
    monkeypatch.setenv("QQ_APPSECRET", "secret")
    assert qq_bot.is_configured() is True


def test_build_text_contains_notice(conn):
    text = qq_bot.build_text("daily")
    assert "武大通知" in text
    assert "推免" in text
    assert "https://cs.whu.edu.cn/info/1055/1.htm" in text
    assert len(text) <= qq_bot.MAX_TEXT


def test_build_text_important(conn):
    text = qq_bot.build_text("important")
    assert "重要通知" in text
    assert "推免" in text


def test_build_text_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "empty.db"))
    c = db.connect()
    db.init_db(c)
    c.close()
    text = qq_bot.build_text("daily")
    assert "暂无新通知" in text

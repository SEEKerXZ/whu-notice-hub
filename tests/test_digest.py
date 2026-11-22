"""邮件日报与即时推送测试。"""
import pytest

from app import db, digest


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.upsert_source(c, "whu_main", "官网通知公告", "university",
                     "https://www.whu.edu.cn/tzgg.htm", 70, True, 20)
    yield c
    c.close()


def _add(conn, title, importance, url, published="2026-11-20", deadline=None):
    return db.save_notice(conn, {
        "source_code": "whu_main",
        "url": url,
        "url_hash": __import__("hashlib").sha1(url.encode()).hexdigest(),
        "title": title,
        "title_norm": title,
        "published_at": published,
        "category": "招生",
        "summary": "摘要",
        "content_md": "正文",
        "content_hash": "h" + url[-4:],
        "audience": [],
        "action_items": [],
        "deadline_date": deadline,
        "importance": importance,
    })


def test_push_dry_run_counts_only_high(conn, monkeypatch):
    monkeypatch.setenv("PUSH_MIN_IMPORTANCE", "75")
    _add(conn, "高优：推免细则", 90, "https://x/1")
    _add(conn, "低优：讲座预告", 40, "https://x/2")
    assert digest.push_high_importance(conn, dry_run=True) == 1


def test_push_skips_when_smtp_missing(conn, monkeypatch):
    monkeypatch.setenv("PUSH_MIN_IMPORTANCE", "50")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("WECOM_WEBHOOK", raising=False)
    _add(conn, "高优通知", 90, "https://x/3")
    assert digest.push_high_importance(conn) == 0


def test_build_markdown_for_wecom(conn):
    _add(conn, "奖学金评选通知", 80, "https://x/9", "2099-01-01")
    rows = list(conn.execute("SELECT n.*, s.name AS source_name FROM notices n "
                             "LEFT JOIN sources s ON s.code=n.source_code"))
    text = digest.build_markdown("武大通知日报", [("过去 24 小时新增", rows)])
    assert text.startswith("## 武大通知日报")
    assert "奖学金评选通知" in text
    assert "https://x/9" in text


def test_build_digest_html(conn):
    _add(conn, "奖学金评选通知", 80, "https://x/4", "2099-01-01")
    title, html_body = digest.build_digest(conn)
    assert title == "武大通知日报"
    assert "奖学金评选通知" in html_body
    assert "<html>" in html_body


def test_send_digest_once_per_day(conn, monkeypatch, tmp_path):
    marker = tmp_path / "last_digest.txt"
    monkeypatch.setattr(digest, "digest_marker", lambda: marker)
    monkeypatch.setattr(digest.mailer, "is_configured", lambda: True)
    sent = []
    monkeypatch.setattr(digest.mailer, "send_email", lambda s, h: sent.append((s, h)) or True)

    assert digest.send_digest(conn) is True
    assert marker.exists()
    assert digest.send_digest(conn) is False
    assert len(sent) == 1

    assert digest.send_digest(conn, force=True) is True
    assert len(sent) == 2


def test_default_subscription_is_idempotent(conn):
    a = digest.default_subscription(conn)
    b = digest.default_subscription(conn)
    assert a == b

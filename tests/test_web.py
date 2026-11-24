"""Web 层测试：页面路由、导航、RSS、API、限流与认证。"""
import base64
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from app import db

    conn = db.connect()
    db.init_db(conn)
    db.upsert_source(conn, "whu_main", "官网通知公告", "university",
                     "https://www.whu.edu.cn/tzgg.htm", 70, True, 20)
    db.save_notice(conn, {
        "source_code": "whu_main",
        "url": "https://www.whu.edu.cn/info/1/2.htm",
        "url_hash": "abc123",
        "title": "关于本科生选课的通知",
        "title_norm": "关于本科生选课的通知",
        "published_at": "2026-11-20",
        "category": "教务",
        "summary": "请在规定时间内完成选课",
        "content_md": "正文内容",
        "content_hash": "h1",
        "audience": ["本科生"],
        "action_items": ["按时选课"],
        "deadline_date": "2026-12-01",
        "importance": 80,
    })
    db.save_notice(conn, {
        "source_code": "whu_main",
        "url": "https://www.whu.edu.cn/info/1/3.htm",
        "url_hash": "def456",
        "title": "关于奖学金评选的通知",
        "title_norm": "关于奖学金评选的通知",
        "published_at": "2026-10-15",
        "category": "奖助",
        "summary": "奖学金开始评选",
        "content_md": "正文",
        "content_hash": "h2",
        "audience": [],
        "action_items": [],
        "deadline_date": None,
        "importance": 60,
    })
    conn.close()

    from app.web import app

    return TestClient(app)


def test_portal_home(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "今天想看" in resp.text
    for name in ("通知聚合", "视频推荐", "项目分享", "便捷工具"):
        assert name in resp.text


def test_portal_subpages(client):
    assert client.get("/videos").status_code == 200
    assert client.get("/projects").status_code == 200
    tools = client.get("/tools")
    assert tools.status_code == 200
    assert "便捷工具" in tools.text


def test_projects_submit_closed_by_default(client):
    resp = client.get("/projects/new")
    assert resp.status_code == 200
    assert "暂未开放" in resp.text


def test_projects_submit_with_key(client, monkeypatch):
    monkeypatch.setenv("PROJECT_SUBMIT_KEY", "lemon")
    monkeypatch.setenv("PROJECTS_NO_FETCH", "1")

    bad = client.post("/projects/new", data={"key": "wrong", "url": "https://github.com/a/b"})
    assert bad.status_code == 403

    ok = client.post(
        "/projects/new",
        data={"key": "lemon", "url": "https://github.com/a/notice-tool",
              "name": "通知小工具", "desc": "帮同学查通知", "author": "同学"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    page = client.get("/projects")
    assert "通知小工具" in page.text


def test_index_renders(client):
    resp = client.get("/notices")
    assert resp.status_code == 200
    assert "WHU Notice Hub" in resp.text
    assert "今日新增" in resp.text
    assert "重点通知" in resp.text


def test_index_filter(client):
    assert client.get("/notices?category=教务").status_code == 200
    assert client.get("/notices?q=选课").status_code == 200
    assert "仅看有截止日期" in client.get("/notices").text


def test_importance_levels_not_numbers(client):
    html = client.get("/notices").text
    assert "level" in html
    assert "重要" in html
    assert 'type="number"' not in html


def test_level_filter(client):
    for level in ("high", "mid", "low"):
        assert client.get(f"/notices?level={level}").status_code == 200


def test_category_page(client):
    resp = client.get("/category/" + quote("教务"))
    assert resp.status_code == 200
    assert "教务 · 分类" in resp.text
    assert "关于本科生选课的通知" in resp.text


def test_source_page(client):
    resp = client.get("/source/whu_main")
    assert resp.status_code == 200
    assert "whu_main · 信源" in resp.text


def test_archive_pages(client):
    resp = client.get("/archive")
    assert resp.status_code == 200
    assert "2026-11" in resp.text
    resp2 = client.get("/archive/2026-11")
    assert resp2.status_code == 200
    assert "关于本科生选课的通知" in resp2.text


def test_about_page(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert "关于这个站点" in resp.text
    assert "免责声明" in resp.text


def test_changelog_page(client):
    resp = client.get("/changelog")
    assert resp.status_code == 200
    assert "更新日志" in resp.text
    assert "v1.0.0" in resp.text


def test_search_redirect(client):
    resp = client.get("/search?q=" + quote("选课"), follow_redirects=False)
    assert resp.status_code in (302, 307)


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True


def test_api_notices(client):
    payload = client.get("/api/notices").json()
    assert payload["count"] == 2
    assert payload["data"][0]["title"] == "关于本科生选课的通知"


def test_rss(client):
    resp = client.get("/rss.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    assert "关于本科生选课的通知" in resp.text


def test_sitemap(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/notice/" in resp.text and "<urlset" in resp.text


def test_notice_detail_navigation(client):
    resp = client.get("/notice/1")
    assert resp.status_code == 200
    assert "同分类通知" in resp.text or "上一条" in resp.text
    assert "查看原文" in resp.text


def test_404_page(client):
    resp = client.get("/notice/99999")
    assert resp.status_code == 404
    assert "404" in resp.text

    resp2 = client.get("/no-such-page")
    assert resp2.status_code == 404


def test_rate_limit(client, monkeypatch):
    import app.web as web

    monkeypatch.setattr(web, "RATE_LIMIT_PER_MINUTE", 2)
    web._hits.clear()
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 429
    web._hits.clear()


def test_basic_auth(client, monkeypatch):
    monkeypatch.setenv("WEB_USER", "u")
    monkeypatch.setenv("WEB_PASSWORD", "p")
    assert client.get("/").status_code == 401

    token = base64.b64encode(b"u:p").decode()
    assert client.get("/", headers={"Authorization": f"Basic {token}"}).status_code == 200
    assert client.get("/healthz").status_code == 200


def test_no_auth_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("WEB_USER", raising=False)
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    assert client.get("/").status_code == 200

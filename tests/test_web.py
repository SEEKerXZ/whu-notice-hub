"""Web 层冒烟测试：模板渲染、健康检查、JSON API、RSS、限流与认证。"""
import base64

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
    conn.close()

    from app.web import app

    return TestClient(app)


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "WHU Notice Hub" in resp.text
    assert "今日新增" in resp.text          # 概览统计
    assert "重点通知" in resp.text          # 重点区块（重要度 80）


def test_index_filter(client):
    assert client.get("/?category=教务").status_code == 200
    assert client.get("/?q=选课").status_code == 200


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_api_notices(client):
    resp = client.get("/api/notices")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 1
    assert payload["data"][0]["title"] == "关于本科生选课的通知"


def test_rss(client):
    resp = client.get("/rss.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    assert "<rss" in resp.text
    assert "关于本科生选课的通知" in resp.text


def test_notice_detail(client):
    assert client.get("/notice/1").status_code == 200
    assert client.get("/notice/99999").status_code == 404


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
    ok = client.get("/", headers={"Authorization": f"Basic {token}"})
    assert ok.status_code == 200

    # 健康检查不要求认证，便于监控
    assert client.get("/healthz").status_code == 200


def test_no_auth_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("WEB_USER", raising=False)
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    assert client.get("/").status_code == 200

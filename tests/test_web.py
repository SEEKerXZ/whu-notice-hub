"""Web 层冒烟测试：模板渲染、健康检查、JSON API。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from app import db

    conn = db.connect()
    db.init_db(conn)
    conn.close()

    from app.web import app

    return TestClient(app)


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "WHU Notice Hub" in resp.text


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_api_notices_empty(client):
    resp = client.get("/api/notices")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 0
    assert payload["data"] == []


def test_notice_404(client):
    assert client.get("/notice/99999").status_code == 404


def test_basic_auth(client, monkeypatch):
    import base64

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

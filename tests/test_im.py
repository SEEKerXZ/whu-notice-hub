"""企业微信群机器人推送测试（不真连服务）。"""
import pytest

from app import im


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeClient:
    last: tuple = ()

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None):
        _FakeClient.last = (url, json)
        return _FakeResp({"errcode": 0, "errmsg": "ok"})


def test_not_configured_raises(monkeypatch):
    monkeypatch.delenv("WECOM_WEBHOOK", raising=False)
    assert im.is_configured() is False
    with pytest.raises(RuntimeError):
        im.send_markdown("x")


def test_send_markdown_payload(monkeypatch):
    monkeypatch.setenv("WECOM_WEBHOOK", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
    monkeypatch.setattr(im.httpx, "Client", _FakeClient)
    assert im.send_markdown("## 标题\n- 条目") is True
    url, payload = _FakeClient.last
    assert "webhook" in url
    assert payload["msgtype"] == "markdown"
    assert payload["markdown"]["content"].startswith("## 标题")


def test_long_content_truncated_by_bytes(monkeypatch):
    monkeypatch.setenv("WECOM_WEBHOOK", "https://example.com/hook")
    monkeypatch.setattr(im.httpx, "Client", _FakeClient)
    im.send_markdown("长" * 3000)
    _, payload = _FakeClient.last
    assert len(payload["markdown"]["content"].encode("utf-8")) <= 4096
    assert payload["markdown"]["content"].endswith("（内容过长已截断）")


def test_send_text(monkeypatch):
    monkeypatch.setenv("WECOM_WEBHOOK", "https://example.com/hook")
    monkeypatch.setattr(im.httpx, "Client", _FakeClient)
    assert im.send_text("hello") is True
    assert _FakeClient.last[1]["msgtype"] == "text"

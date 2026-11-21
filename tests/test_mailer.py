"""SMTP 发送测试（不真连服务器）。"""
import pytest

from app import mailer


class FakeSMTP:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def _configure(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "me@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "authcode")
    monkeypatch.setenv("MAIL_TO", "me@example.com")


def test_not_configured_raises(monkeypatch):
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    assert mailer.is_configured() is False
    with pytest.raises(RuntimeError):
        mailer.send_email("x", "<p>x</p>")


def test_send_email_builds_message(monkeypatch):
    _configure(monkeypatch)
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    assert mailer.send_email("测试标题", "<p>正文</p>") is True
    msg = FakeSMTP.sent[-1]
    assert msg["Subject"] == "测试标题"
    assert msg["To"] == "me@example.com"
    assert "正文" in msg.get_body(preferencelist=("html",)).get_content()

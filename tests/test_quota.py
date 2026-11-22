"""AI 问答限额测试。"""
import pytest

from app import db, quota


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    c = db.connect()
    db.init_db(c)
    c.close()
    quota._last_ask.clear()
    yield
    quota._last_ask.clear()


def test_per_user_limit(monkeypatch, conn):
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "2")
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_GROUP", "100")
    monkeypatch.setenv("AI_DAILY_LIMIT_TOTAL", "100")
    monkeypatch.setenv("AI_MIN_INTERVAL_SECONDS", "0")

    assert quota.consume("u1", "g1")[0] is True
    assert quota.consume("u1", "g1")[0] is True
    ok, reason = quota.consume("u1", "g1")
    assert ok is False
    assert "问满" in reason


def test_per_group_limit(monkeypatch, conn):
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "100")
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_GROUP", "2")
    monkeypatch.setenv("AI_DAILY_LIMIT_TOTAL", "100")
    monkeypatch.setenv("AI_MIN_INTERVAL_SECONDS", "0")

    assert quota.consume("u1", "g1")[0] is True
    assert quota.consume("u2", "g1")[0] is True
    ok, reason = quota.consume("u3", "g1")
    assert ok is False
    assert "本群" in reason


def test_total_limit(monkeypatch, conn):
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "100")
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_GROUP", "100")
    monkeypatch.setenv("AI_DAILY_LIMIT_TOTAL", "1")
    monkeypatch.setenv("AI_MIN_INTERVAL_SECONDS", "0")

    assert quota.consume("u1", "g1")[0] is True
    ok, reason = quota.consume("u2", "g2")
    assert ok is False
    assert "全站" in reason


def test_min_interval(monkeypatch, conn):
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "100")
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_GROUP", "100")
    monkeypatch.setenv("AI_DAILY_LIMIT_TOTAL", "100")
    monkeypatch.setenv("AI_MIN_INTERVAL_SECONDS", "60")

    assert quota.consume("u1", "g1")[0] is True
    ok, reason = quota.consume("u1", "g1")
    assert ok is False
    assert "别急" in reason


def test_remaining_and_usage(monkeypatch, conn):
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "5")
    monkeypatch.setenv("AI_DAILY_LIMIT_TOTAL", "20")
    monkeypatch.setenv("AI_MIN_INTERVAL_SECONDS", "0")
    quota.consume("u1", "g1")
    left_user, left_total, used_total = quota.remaining("u1")
    assert left_user == 4
    assert left_total == 19
    assert used_total == 1
    scopes = {r["scope"] for r in quota.usage_today()}
    assert "user:u1" in scopes and "group:g1" in scopes and "total" in scopes


def test_fixed_commands_not_counted(monkeypatch, conn):
    """日报/重要走固定指令，不应消耗 AI 额度。"""
    monkeypatch.setenv("AI_DAILY_LIMIT_PER_USER", "1")
    monkeypatch.setenv("AI_MIN_INTERVAL_SECONDS", "0")
    assert quota.remaining("u1")[2] == 0

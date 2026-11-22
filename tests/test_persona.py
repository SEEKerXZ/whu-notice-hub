"""猫娘人设测试：只包装、不改事实，可一键回退。"""
import pytest

from app import persona


def test_default_is_catgirl_l2(monkeypatch):
    monkeypatch.delenv("PERSONA", raising=False)
    monkeypatch.delenv("PERSONA_LEVEL", raising=False)
    assert persona.enabled() is True
    assert persona.level() == 2


def test_can_turn_off(monkeypatch):
    monkeypatch.setenv("PERSONA", "default")
    text = "近期有 2 条通知"
    assert persona.decorate(text) == text


def test_notice_decoration_keeps_body_intact():
    text = "1. 雷军奖学金，11-30 截止"
    out = persona.decorate(text, mode="notice")
    assert text in out
    assert any(opener.strip("：:") in out for opener in persona.OPENERS)
    assert any(closer in out for closer in persona.CLOSERS)


def test_chat_decoration_has_no_notice_opener():
    out = persona.decorate("在的，有什么可以帮你？", mode="chat")
    assert "在的" in out
    assert not any(opener in out for opener in persona.OPENERS)


def test_limit_meow_caps_count():
    out = persona.limit_meow("喵" * 20, max_count=3)
    assert out.count("喵") == 3


def test_level_1_no_decoration(monkeypatch):
    monkeypatch.setenv("PERSONA_LEVEL", "1")
    text = "近期有 2 条通知"
    assert persona.decorate(text) == text

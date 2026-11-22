"""人物介绍彩蛋测试。"""
from app import intro


def test_strong_aliases_match():
    for text in ("北郊HH", "bjhh", "BJHH", "hygg", "hhy", "胡豪宇", "豪宇", "介绍下胡豪宇"):
        assert intro.matches(text) is True, text


def test_weak_alias_needs_question():
    assert intro.matches("老大") is False
    assert intro.matches("老大是谁") is True
    assert intro.matches("介绍一下老大") is True
    assert intro.matches("老大今天来吗") is False


def test_unrelated_text_not_matched():
    for text in ("", "你好", "最近有什么奖学金", "日报", "hhyy", "xbjhhx"):
        assert intro.matches(text) is False, text


def test_reply_contains_profile_facts(monkeypatch):
    monkeypatch.delenv("PERSONA", raising=False)
    text = intro.build_reply()
    for fact in ("胡豪宇", "中共预备党员", "gpa3.95", "23项奖项", "240小时", "织金县", "国家奖学金"):
        assert fact in text
    assert text.startswith("喵～介绍来啦")


def test_reply_without_persona(monkeypatch):
    monkeypatch.setenv("PERSONA", "default")
    text = intro.build_reply()
    assert text.startswith("胡豪宇")
    assert "喵" not in text

"""AI 问答测试：检索、降级、LLM 调用（mock）。"""
import pytest

from app import ai, db


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    c = db.connect()
    db.init_db(c)
    db.upsert_source(c, "cs_whu", "计算机学院·通知公告", "college",
                     "https://cs.whu.edu.cn/xwdt/tzgg.htm", 85, True, 60)
    for idx, (title, cat, imp) in enumerate([
        ("关于2025—2026学年度雷军计算机本科生奖学金评选的通知", "奖助", 70),
        ("计算机学院2027年推荐免试研究生拟录取名单公示", "招生", 65),
        ("关于2026年冬季作息时间调整的通知", "其他", 40),
    ], start=1):
        db.save_notice(c, {
            "source_code": "cs_whu",
            "url": f"https://cs.whu.edu.cn/info/1055/{idx}.htm",
            "url_hash": f"h{idx}",
            "title": title,
            "title_norm": title,
            "published_at": "2026-11-21",
            "category": cat,
            "summary": None,
            "content_md": "",
            "content_hash": "list-only",
            "audience": [],
            "action_items": [],
            "deadline_date": None,
            "importance": imp,
        })
    yield c
    c.close()


def test_bigrams_basic():
    grams = ai._bigrams("奖学金")
    assert "奖学" in grams and "学金" in grams
    assert ai._bigrams("") == set()


def test_search_finds_scholarship(conn):
    rows = ai.search(conn, "最近有什么奖学金的通知")
    assert rows
    assert any("奖学金" in r["title"] for r in rows)


def test_search_no_match(conn):
    assert ai.search(conn, "天文望远镜观测") == []


def test_answer_no_match(conn):
    text = ai.answer("天文望远镜观测")
    assert "没有找到相关通知" in text


def test_answer_no_match_chats_when_enabled(conn, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("AI_CHAT_MODE", "1")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "在的在的，今天有什么想了解的？"}}]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(ai.httpx, "Client", _Client)
    text = ai.answer("在吗")
    assert "在的" in text


def test_answer_chat_disabled_returns_not_found(conn, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("AI_CHAT_MODE", "0")
    text = ai.answer("在吗")
    assert "没有找到相关通知" in text


def test_mixed_mode_answers_general_question(conn, monkeypatch):
    """闲聊模式下，即使检索到不相关通知（如"规划"命中职业规划大赛），也应正常回答一般问题。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("AI_CHAT_MODE", "1")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "动态规划是把大问题拆成重叠子问题…"}}]}

    class _Client:
        payload = {}

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            _Client.payload = json
            return _Resp()

    monkeypatch.setattr(ai.httpx, "Client", _Client)
    text = ai.answer("解释一下什么是动态规划")
    assert "动态规划" in text
    # 混合模式使用宽松提示词
    assert "也可以和大家闲聊" in _Client.payload["messages"][0]["content"]


def test_answer_without_llm_falls_back(conn, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    text = ai.answer("奖学金")
    assert "找到这几条相关通知" in text
    assert "奖学金" in text


def test_answer_with_llm(conn, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "最近有雷军计算机本科生奖学金评选，11-30 截止。"}}]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            _Client.payload = json
            return _Resp()

    monkeypatch.setattr(ai.httpx, "Client", _Client)
    text = ai.answer("最近有什么奖学金")
    assert "雷军" in text
    # 提示词里应带上检索到的通知上下文
    assert "通知列表" in _Client.payload["messages"][1]["content"]


def test_answer_llm_error_falls_back(conn, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(ai.httpx, "Client", _Client)
    text = ai.answer("奖学金")
    assert "找到这几条相关通知" in text

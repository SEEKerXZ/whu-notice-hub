"""基于站内通知库的 AI 问答（OpenAI 兼容接口，默认 DeepSeek）。

流程：问题 → 关键词/二元组检索本地通知 → 把候选通知交给模型总结 → 返回简短回答。
模型只允许基于候选通知作答，避免编造。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3

import httpx

from . import db

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"

STOPWORDS = {
    "请问", "有没有", "有什么", "哪些", "最近", "关于", "通知", "可以", "一下",
    "帮我", "看看", "什么", "怎么", "如何", "吗", "呢", "的", "了", "我", "想",
}

SYSTEM_PROMPT = (
    "你是武汉大学本科生通知助理。只能根据用户提供的「通知列表」回答，绝对不要编造。"
    "回答用中文、简洁（不超过 120 字），优先给出最关键的一两条，并附上链接。"
    "如果列表中找不到相关信息，就直接说没找到，并提示用户可以发送「日报」查看全部近期通知。"
)


def is_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY", "").strip())


def _bigrams(text: str) -> set[str]:
    """中文按二元组切分，英文按词；用于无分词器时的粗粒度匹配。"""
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", (text or "").lower())
    words = [w for w in text.split() if w and w not in STOPWORDS]
    grams: set[str] = set()
    for word in words:
        if re.fullmatch(r"[a-z0-9_]+", word):
            if len(word) >= 2:
                grams.add(word)
            continue
        for i in range(len(word) - 1):
            grams.add(word[i:i + 2])
        if len(word) == 1:
            grams.add(word)
    return grams


def search(conn: sqlite3.Connection, question: str, limit: int = 8) -> list[sqlite3.Row]:
    """按二元组重合度给通知打分，返回最相关的若干条。"""
    grams = _bigrams(question)
    if not grams:
        return []
    rows = list(conn.execute(
        """SELECT n.*, s.name AS source_name
             FROM notices n LEFT JOIN sources s ON s.code = n.source_code
            WHERE n.status <> 'archived'
            ORDER BY COALESCE(n.published_at, n.first_seen_at) DESC
            LIMIT 600"""
    ))
    scored = []
    for row in rows:
        text = f"{row['title']} {row['summary'] or ''} {row['category'] or ''}"
        score = len(grams & _bigrams(text))
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: (x[0], x[1]["importance"] or 0), reverse=True)
    return [row for _, row in scored[:limit]]


def _link_of(row: sqlite3.Row) -> str:
    url = row["url"] or ""
    if ("content.jsp" in url or "tzggnr.jsp" in url) and row["fallback_url"]:
        return row["fallback_url"]
    return url


def _context(rows: list[sqlite3.Row]) -> str:
    lines = []
    for i, row in enumerate(rows, 1):
        date = row["published_at"] or (row["first_seen_at"] or "")[:10]
        deadline = f"，截止 {row['deadline_date']}" if row["deadline_date"] else ""
        lines.append(
            f"[{i}] {row['title']}｜{row['source_name'] or row['source_code']}｜{date}{deadline}"
            f"｜{row['summary'] or ''}｜{_link_of(row)}"
        )
    return "\n".join(lines)


def _fallback(rows: list[sqlite3.Row]) -> str:
    lines = ["找到这几条相关通知："]
    for row in rows[:5]:
        lines.append(f"· {row['title']}")
        lines.append(f"  {_link_of(row)}")
    return "\n".join(lines)


def _call_llm(question: str, context: str) -> str:
    url = os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    api_key = os.getenv("LLM_API_KEY", "").strip()
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"通知列表：\n{context}\n\n用户问题：{question}"},
        ],
    }
    with httpx.Client(timeout=25) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def answer(question: str, limit: int = 1400) -> str:
    """返回给 QQ 群的回答文本。检索不到或调用失败时退化为列表。"""
    question = (question or "").strip()
    if not question:
        return "发送「日报」查看近期通知，发送「重要」查看重点通知。"

    conn = db.connect()
    try:
        rows = search(conn, question)
    finally:
        conn.close()

    if not rows:
        return (
            "没有找到相关通知。\n"
            "可以发送「日报」查看近期通知，或换个关键词试试（如「奖学金」「推免」「选课」）。"
        )

    if not is_configured():
        return _fallback(rows)

    try:
        text = _call_llm(question, _context(rows))
        return text[:limit] if text else _fallback(rows)
    except Exception:  # noqa: BLE001
        log.exception("LLM 调用失败，退化为列表")
        return _fallback(rows)

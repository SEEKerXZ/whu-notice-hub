"""猫娘人设（L2）：只做包装，不改事实。

- 通知类回答：开头加一句随机开场白、结尾加一句收尾，正文原样不动
- 闲聊/代码：人设由提示词控制，代码本身不加口癖
- 护栏：控制「喵」的密度；`PERSONA=default` 可一键回退正常人设
"""
from __future__ import annotations

import os
import random

OPENERS = [
    "喵～本喵帮你翻到啦：",
    "找到啦喵：",
    "本喵查了一下，是这样的喵：",
    "喵呜，情报在这里：",
    "帮你整理好啦喵：",
]

CLOSERS = [
    "还有问题随时叫我喵 🐾",
    "需要的话本喵再翻翻～",
    "就这些啦喵 🐾",
]

CHAT_CLOSERS = [
    "喵～",
    "有问题随时找本喵 🐾",
]


def enabled() -> bool:
    return os.getenv("PERSONA", "catgirl").strip().lower() != "default"


def level() -> int:
    try:
        return int(os.getenv("PERSONA_LEVEL", "2"))
    except ValueError:
        return 2


def _pick(pool: list[str]) -> str:
    return random.choice(pool)


def limit_meow(text: str, max_count: int = 6) -> str:
    """护栏：整条消息里「喵」过多时删掉多余的，避免刷屏式卖萌。"""
    if text.count("喵") <= max_count:
        return text
    out = text
    while out.count("喵") > max_count:
        idx = out.rfind("喵")
        if idx < 0:
            break
        out = out[:idx] + out[idx + 1:]
    return out


def decorate(text: str, mode: str = "notice") -> str:
    """给人设加外壳。mode: notice（加开场+收尾）/ chat（只加收尾）。"""
    text = (text or "").strip()
    if not text or not enabled() or level() < 2:
        return text

    parts: list[str] = []
    if mode == "notice":
        parts.append(_pick(OPENERS))
    parts.append(text)
    if mode == "notice":
        parts.append(_pick(CLOSERS))
    elif mode == "chat" and random.random() < 0.6:
        parts.append(_pick(CHAT_CLOSERS))

    return limit_meow("\n".join(parts))

"""加载 .env（systemd 之外的场景：手动跑 CLI、本地开发）。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str | Path | None = None) -> dict[str, str]:
    """把 .env 读进 os.environ（不覆盖已存在的变量）。"""
    p = Path(path or os.getenv("ENV_FILE") or ROOT / ".env")
    loaded: dict[str, str] = {}
    if not p.exists():
        return loaded
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


load_env()

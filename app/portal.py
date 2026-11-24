"""首页门户数据：读取 config/portal.yaml 里的视频推荐 / 项目分享 / 便捷工具。"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PORTAL_FILE = ROOT / "config" / "portal.yaml"


def load() -> dict:
    if not PORTAL_FILE.exists():
        return {"videos": [], "projects": [], "tools": []}
    data = yaml.safe_load(PORTAL_FILE.read_text(encoding="utf-8")) or {}
    return {
        "videos": data.get("videos") or [],
        "projects": data.get("projects") or [],
        "tools": data.get("tools") or [],
    }

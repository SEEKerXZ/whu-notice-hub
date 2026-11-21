"""快照保留策略测试。"""
import os
import time
from pathlib import Path

from app.fetch import cleanup_snapshots


def _make_day_dir(root: Path, name: str, age_days: float) -> Path:
    d = root / name
    d.mkdir()
    (d / "x.html").write_text("<html></html>", encoding="utf-8")
    ts = time.time() - age_days * 86400
    os.utime(d, (ts, ts))
    return d


def test_cleanup_removes_old_keeps_recent(tmp_path):
    _make_day_dir(tmp_path, "2026-11-01", 20)
    _make_day_dir(tmp_path, "2026-11-20", 1)
    removed = cleanup_snapshots(days=7, root=tmp_path)
    assert removed == 1
    assert (tmp_path / "2026-11-20").exists()
    assert not (tmp_path / "2026-11-01").exists()


def test_cleanup_missing_root(tmp_path):
    assert cleanup_snapshots(days=7, root=tmp_path / "nope") == 0

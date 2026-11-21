"""HTTP 抓取：限速、重试、UA、原始快照。"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# 站点的 WAF 会拦截非浏览器 UA，因此使用浏览器 UA；
# 如需表明身份，可在 .env 设置 CONTACT_EMAIL，会通过标准 From 头带上。
CONTACT = os.getenv("CONTACT_EMAIL", "").strip()

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"


class Fetcher:
    """串行抓取器：每个 host 1 req/s，失败重试 3 次，支持原始快照落盘。"""

    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 3,
        min_interval: float = 1.0,
        snapshot: bool = True,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.min_interval = min_interval
        self.snapshot = snapshot
        self._last_hit: dict[str, float] = {}
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if CONTACT:
            headers["From"] = CONTACT
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host, 0.0)
        wait = self.min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str) -> httpx.Response:
        host = httpx.URL(url).host or ""
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle(host)
            try:
                resp = self._client.get(url)
                resp.raise_for_status()
                resp.encoding = resp.encoding or "utf-8"
                if self.snapshot:
                    self._save_snapshot(url, resp.text)
                return resp
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("fetch failed (%s/%s) %s: %s", attempt, self.retries, url, exc)
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"fetch failed after {self.retries} retries: {url}") from last_err

    def get_text(self, url: str) -> str:
        return self.get(url).text

    def _save_snapshot(self, url: str, text: str) -> None:
        try:
            key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
            d = SNAPSHOT_DIR / time.strftime("%Y-%m-%d")
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{key}.html").write_text(text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.debug("snapshot skipped: %s", exc)


def cleanup_snapshots(days: int = 7, root: Path | None = None) -> int:
    """删除超过 N 天快照，避免磁盘无限增长。返回删除的目录数。"""
    root = root or SNAPSHOT_DIR
    if not root.exists():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for child in root.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed

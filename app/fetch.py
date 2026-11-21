"""HTTP 抓取：限速、抖动、WAF 识别与熔断。

站点对高频访问会返回图片验证码页（"用户验证 / 访问太过频繁"）。
我们不做验证码识别，策略是：低频 + 随机抖动 + 命中即熔断该 host，
等冷却结束再继续，避免越抓越封。
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import shutil
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# 站点的 WAF 可能拦截非浏览器 UA，因此使用浏览器 UA；
# 如需表明身份，可在 .env 设置 CONTACT_EMAIL，会通过标准 From 头带上。
CONTACT = os.getenv("CONTACT_EMAIL", "").strip()

WAF_MARKERS = ("用户验证", "访问太过频繁", "请输入验证码")

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"


class RateLimited(RuntimeError):
    """被站点 WAF 限流（验证码拦截），需要冷却后再试。"""

    def __init__(self, url: str, host: str):
        super().__init__(f"WAF 限流: {url}")
        self.url = url
        self.host = host


def is_waf_page(text: str) -> bool:
    return any(marker in text for marker in WAF_MARKERS)


class Fetcher:
    """串行抓取器：默认每 host 3 秒 1 次（带抖动），失败重试，命中 WAF 熔断。"""

    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 2,
        min_interval: float | None = None,
        snapshot: bool = True,
        waf_cooldown: float | None = None,
        max_requests: int | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.min_interval = float(
            min_interval if min_interval is not None else os.getenv("FETCH_MIN_INTERVAL", "3.0")
        )
        self.snapshot = snapshot
        self.waf_cooldown = float(
            waf_cooldown if waf_cooldown is not None else os.getenv("WAF_COOLDOWN_SECONDS", "1800")
        )
        self.max_requests = int(
            max_requests if max_requests is not None else os.getenv("MAX_REQUESTS_PER_RUN", "120")
        )
        self._last_hit: dict[str, float] = {}
        self._blocked_until: dict[str, float] = {}
        self.request_count = 0
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if CONTACT:
            headers["From"] = CONTACT
        self._client = httpx.Client(follow_redirects=True, timeout=timeout, headers=headers)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _host_blocked(self, host: str) -> bool:
        until = self._blocked_until.get(host, 0.0)
        if until > time.monotonic():
            return True
        self._blocked_until.pop(host, None)
        return False

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host, 0.0)
        wait = self.min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        # 抖动：避免固定节奏被识别为机器人
        time.sleep(random.uniform(0, min(1.0, self.min_interval * 0.4)))
        self._last_hit[host] = time.monotonic()

    # ------------------------------------------------------------------
    def get(self, url: str) -> httpx.Response:
        host = httpx.URL(url).host or ""
        if self._host_blocked(host):
            raise RateLimited(url, host)
        if self.request_count >= self.max_requests:
            raise RuntimeError(f"本轮请求数已达上限 {self.max_requests}，提前停止")

        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle(host)
            self.request_count += 1
            try:
                resp = self._client.get(url)
                resp.encoding = resp.encoding or "utf-8"
                if is_waf_page(resp.text):
                    self._blocked_until[host] = time.monotonic() + self.waf_cooldown
                    log.warning(
                        "命中 WAF 验证码，熔断 %s %.0f 分钟: %s",
                        host, self.waf_cooldown / 60, url,
                    )
                    raise RateLimited(url, host)
                resp.raise_for_status()
                if self.snapshot:
                    self._save_snapshot(url, resp.text)
                return resp
            except RateLimited:
                raise
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("fetch failed (%s/%s) %s: %s", attempt, self.retries, url, exc)
                time.sleep(min(3 * attempt, 10))
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

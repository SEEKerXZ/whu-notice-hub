"""抓取限速与 WAF 识别测试。"""
import pytest

from app import fetch


def test_is_waf_page_detects_challenge():
    page = "<title>用户验证</title>您的IP是：1.2.3.4，由于您访问太过频繁，请输入验证码后访问。"
    assert fetch.is_waf_page(page) is True
    assert fetch.is_waf_page("<html>正常通知页面</html>") is False


def test_rate_limited_is_runtime_error():
    exc = fetch.RateLimited("https://x/y", "x")
    assert isinstance(exc, RuntimeError)
    assert exc.host == "x"


def test_fetcher_respects_cooldown(monkeypatch):
    """命中熔断后，同一 host 的请求应立刻抛 RateLimited 而不是继续打。"""
    f = fetch.Fetcher(min_interval=0, retries=1, waf_cooldown=60, max_requests=10)
    try:
        f._blocked_until["example.com"] = __import__("time").monotonic() + 60
        with pytest.raises(fetch.RateLimited):
            f.get("https://example.com/a.htm")
    finally:
        f.close()


def test_fetcher_request_cap(monkeypatch):
    f = fetch.Fetcher(min_interval=0, retries=1, max_requests=0)
    try:
        with pytest.raises(RuntimeError):
            f.get("https://example.com/a.htm")
    finally:
        f.close()

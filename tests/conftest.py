"""测试环境隔离：服务器上的 .env 会被 app.config 读进环境变量，测试里统一清空。"""
import pytest

ISOLATED_VARS = (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "AI_CHAT_MODE",
    "AI_DAILY_LIMIT_PER_USER",
    "AI_DAILY_LIMIT_PER_GROUP",
    "AI_DAILY_LIMIT_TOTAL",
    "AI_MIN_INTERVAL_SECONDS",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "MAIL_TO",
    "WECOM_WEBHOOK",
    "QQ_APPID",
    "QQ_APPSECRET",
    "WEB_USER",
    "WEB_PASSWORD",
    "DETAIL_ENABLED",
    "AUDIENCE",
    "PERSONA",
    "PERSONA_LEVEL",
)


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    for name in ISOLATED_VARS:
        monkeypatch.delenv(name, raising=False)
    yield

"""dotenv 加载测试。"""
import os

from app import config


def test_load_env_sets_missing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n# comment\nBAZ=qux\n", encoding="utf-8")
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)
    loaded = config.load_env(env_file)
    assert loaded["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"


def test_load_env_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=from_file\n", encoding="utf-8")
    monkeypatch.setenv("FOO", "from_env")
    config.load_env(env_file)
    assert os.environ["FOO"] == "from_env"


def test_load_env_missing_file(tmp_path):
    assert config.load_env(tmp_path / "nope") == {}

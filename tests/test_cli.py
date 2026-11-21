"""CLI 参数解析测试（只解析，不执行）。"""
from app.cli import build_parser


def test_all_subcommands_parse():
    parser = build_parser()
    assert parser.parse_args(["init-db"]).cmd == "init-db"
    assert parser.parse_args(["crawl", "--pages", "2"]).pages == 2
    assert parser.parse_args(["crawl", "--source", "cs_whu"]).source == ["cs_whu"]
    assert parser.parse_args(["list", "--limit", "5"]).limit == 5
    assert parser.parse_args(["stats"]).cmd == "stats"
    assert parser.parse_args(["push", "--dry-run"]).dry_run is True
    assert parser.parse_args(["digest", "--force"]).force is True
    assert parser.parse_args(["mail-test"]).cmd == "mail-test"
    assert parser.parse_args(["serve", "--port", "9000"]).port == 9000

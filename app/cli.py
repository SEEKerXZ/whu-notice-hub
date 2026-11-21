"""命令行入口：init-db / crawl / list / stats / serve。"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime

from . import config  # noqa: F401  加载 .env
from . import crawl, db, digest
from .sources import Source, load_sources

log = logging.getLogger("cli")


def setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _conn():
    conn = db.connect()
    db.init_db(conn)
    return conn


def _sync_sources(conn) -> list[Source]:
    sources = load_sources(include_disabled=True)
    for s in sources:
        db.upsert_source(
            conn, s.code, s.name, s.level, s.list_url,
            s.weight, s.enabled, s.interval_minutes,
            {"items_xpath": s.items_xpath, "pagination": s.pagination.mode},
        )
    return [s for s in sources if s.enabled]


def cmd_init_db(_args) -> int:
    conn = _conn()
    sources = _sync_sources(conn)
    print(f"数据库已初始化：{db.DEFAULT_DB}")
    print(f"已注册信源 {len(sources)} 个：" + ", ".join(s.code for s in sources))
    return 0


def cmd_crawl(args) -> int:
    conn = _conn()
    enabled = _sync_sources(conn)
    if args.source:
        wanted = set(args.source)
        selected = [s for s in enabled if s.code in wanted]
        missing = wanted - {s.code for s in selected}
        if missing:
            print(f"未找到或未启用的信源：{', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    else:
        selected = enabled
    if not selected:
        print("没有可抓取的信源（检查 config/sources.yaml 的 enabled）", file=sys.stderr)
        return 2

    def progress(msg: str) -> None:
        print(msg)

    results = crawl.crawl_all(conn, selected, progress=progress)
    print("\n抓取结果：")
    print(f"{'source':<18}{'pages':>6}{'seen':>6}{'new':>6}{'updated':>8}{'skip':>6}{'limited':>8}{'dup':>5}{'err':>5}  status")
    for r in results:
        print(f"{r.code:<18}{r.pages:>6}{r.seen:>6}{r.new:>6}{r.updated:>8}"
              f"{r.skipped:>6}{r.limited:>8}{r.duplicate:>5}{r.errors:>5}  {r.status}"
              + (f" ({r.error})" if r.error else ""))
    total_new = sum(r.new for r in results)
    total_skipped = sum(r.skipped for r in results)
    total_limited = sum(r.limited for r in results)
    total_dup = sum(r.duplicate for r in results)
    print(f"\n新增 {total_new} 条（受众过滤 {total_skipped}，标题级 {total_limited}，跨栏目重复 {total_dup}），"
          f"当前库内共 {db.count_notices(conn)} 条。")
    return 0


def cmd_list(args) -> int:
    conn = _conn()
    rows = db.query_notices(conn, source=args.source, limit=args.limit)
    for r in rows:
        deadline = f" ⏰{r['deadline_date']}" if r["deadline_date"] else ""
        print(f"[{r['importance']:>3}] {r['published_at'] or r['first_seen_at'][:10]}  "
              f"{r['source_code']:<14}{r['category']:<6}{deadline}  {r['title']}")
    print(f"\n共 {len(rows)} 条（上限 {args.limit}）")
    return 0


def cmd_stats(_args) -> int:
    conn = _conn()
    print(f"{'source':<18}{'status':<10}{'total':>7}  latest")
    for r in db.stats(conn):
        print(f"{r['code']:<18}{r['status']:<10}{r['total']:>7}  {r['latest'] or '-'}")
    print(f"\n库内通知总数：{db.count_notices(conn)}")
    return 0


def _maybe_send_digest(conn) -> None:
    """到达设定时间且今天未发过，就发日报。"""
    now = datetime.now()
    hour = int(os.getenv("DIGEST_HOUR", "8"))
    minute = int(os.getenv("DIGEST_MINUTE", "30"))
    if (now.hour, now.minute) >= (hour, minute):
        digest.send_digest(conn)


def _scheduler_loop(interval_minutes: int) -> None:
    while True:
        try:
            conn = db.connect()
            db.init_db(conn)
            sources = [s for s in load_sources() if s.enabled]
            log.info("定时抓取开始：%s", ", ".join(s.code for s in sources))
            results = crawl.crawl_all(conn, sources)
            log.info("定时抓取完成：新增 %s 条", sum(r.new for r in results))
            try:
                digest.push_high_importance(conn)
            except Exception:  # noqa: BLE001
                log.exception("即时推送失败")
            try:
                _maybe_send_digest(conn)
            except Exception:  # noqa: BLE001
                log.exception("日报发送失败")
            conn.close()
        except Exception:  # noqa: BLE001
            log.exception("定时抓取失败")
        time.sleep(max(60, interval_minutes * 60))


def cmd_digest(args) -> int:
    conn = _conn()
    _sync_sources(conn)
    ok = digest.send_digest(conn, force=args.force, dry_run=args.dry_run)
    if args.dry_run:
        return 0
    print("日报已发送" if ok else "日报未发送（已发过或 SMTP 未配置）")
    return 0


def cmd_push(args) -> int:
    conn = _conn()
    n = digest.push_high_importance(conn, dry_run=args.dry_run)
    print(f"{'待推送' if args.dry_run else '已推送'} {n} 条高重要度通知")
    return 0


def cmd_mail_test(_args) -> int:
    from . import mailer

    if not mailer.is_configured():
        print("SMTP 未配置：请在 .env 设置 SMTP_HOST / SMTP_USER / SMTP_PASSWORD", file=sys.stderr)
        return 2
    mailer.send_email(
        "【武大通知聚合】测试邮件",
        "<p>如果你收到这封邮件，说明 SMTP 配置正确 ✅</p>",
    )
    print("测试邮件已发送，请查收")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    if os.getenv("SCHEDULER_ENABLED", "0") == "1":
        interval = int(os.getenv("CRAWL_INTERVAL_MINUTES", "20"))
        threading.Thread(target=_scheduler_loop, args=(interval,), daemon=True).start()
        log.info("内置调度已开启，每 %s 分钟抓取一次", interval)

    print(f"启动 Web：http://{args.host}:{args.port}")
    uvicorn.run("app.web:app", host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whu-notice-hub", description="武大通知聚合")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="初始化数据库并注册信源")

    c = sub.add_parser("crawl", help="抓取通知")
    c.add_argument("--source", action="append", help="只抓指定信源，可重复")
    c.add_argument("--pages", type=int, default=None, help="每源抓取页数（默认增量）")
    c.add_argument("--dry-run", action="store_true", help="只解析不入库")

    l = sub.add_parser("list", help="列出最近通知")
    l.add_argument("--source")
    l.add_argument("--limit", type=int, default=20)

    sub.add_parser("stats", help="各信源状态统计")

    d = sub.add_parser("digest", help="发送/预览日报")
    d.add_argument("--dry-run", action="store_true", help="只在终端打印 HTML")
    d.add_argument("--force", action="store_true", help="忽略今日已发标记")

    push_parser = sub.add_parser("push", help="推送高重要度通知")
    push_parser.add_argument("--dry-run", action="store_true", help="只统计不发送")

    sub.add_parser("mail-test", help="发送一封测试邮件")

    s = sub.add_parser("serve", help="启动 Web 服务")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    handlers = {
        "init-db": cmd_init_db, "crawl": cmd_crawl, "list": cmd_list,
        "stats": cmd_stats, "serve": cmd_serve,
        "digest": cmd_digest, "push": cmd_push, "mail-test": cmd_mail_test,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

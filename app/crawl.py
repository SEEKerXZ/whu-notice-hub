"""抓取编排：列表 → 差集 → 详情 → 抽取 → 入库。"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable

import sqlite3

from . import db, parse, score, text
from .fetch import Fetcher
from .sources import Source

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    code: str
    pages: int = 0
    seen: int = 0
    new: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    status: str = "ok"
    error: str | None = None
    titles: list[str] = field(default_factory=list)


def crawl_source(conn: sqlite3.Connection, source: Source, fetcher: Fetcher,
                 pages: int | None = None, dry_run: bool = False,
                 progress: Callable[[str], None] = log.info) -> SourceResult:
    """抓取单个信源。默认增量：整页都已知就停止翻页。"""
    result = SourceResult(code=source.code)
    run_id = None if dry_run else db.start_run(conn, source.code, "incremental" if pages is None else "manual")
    known = db.known_hashes(conn, source.code)

    try:
        for page_url in source.page_urls(pages):
            progress(f"[{source.code}] 列表页 {page_url}")
            try:
                page_html = fetcher.get_text(page_url)
            except Exception as exc:  # noqa: BLE001
                result.errors += 1
                result.error = str(exc)
                result.status = "failed"
                log.warning("[%s] 列表页失败: %s", source.code, exc)
                break

            items = parse.parse_list(page_html, source, page_url)
            result.pages += 1
            result.seen += len(items)
            if not items:
                result.status = "partial"
                result.error = "列表页解析出 0 条，疑似改版"
                log.warning("[%s] %s", source.code, result.error)
                break

            new_items = [it for it in items if text.url_hash(it.url) not in known]
            progress(f"[{source.code}] 第 {result.pages} 页：{len(items)} 条，新增 {len(new_items)} 条")

            for item in new_items:
                url_hash = text.url_hash(item.url)
                detail = parse.Detail()
                try:
                    detail_html = fetcher.get_text(item.url)
                    detail = parse.parse_detail(detail_html, source, item.url, item.published_at)
                except Exception as exc:  # noqa: BLE001
                    result.errors += 1
                    log.warning("[%s] 详情失败 %s: %s", source.code, item.url, exc)

                title = parse.choose_title(item.title, detail.title)

                # 受限通知（"暂无权限"）：入库但标记 archived，避免站点展示无法打开的通知，
                # 同时防止每轮重复抓取该页面。
                if detail.restricted and not dry_run:
                    db.save_notice(conn, {
                        "source_code": source.code,
                        "url": item.url,
                        "url_hash": url_hash,
                        "title": title,
                        "title_norm": text.normalize_title(title),
                        "publisher": item.publisher,
                        "published_at": text.iso(text.parse_date(item.published_at)) if item.published_at else None,
                        "date_inferred": 0,
                        "category": "其他",
                        "summary": None,
                        "content_md": "",
                        "content_hash": "restricted",
                        "audience": [],
                        "action_items": [],
                        "deadline_date": None,
                        "importance": 0,
                        "status": "archived",
                    })
                    result.skipped += 1
                    known.add(url_hash)
                    continue

                body = detail.content_text
                published = detail.published_at or (
                    text.iso(text.parse_date(item.published_at)) if item.published_at else None
                )
                enriched = score.enrich(title, body, published, source.weight)

                # 只要本科生相关：不相关的直接跳过，不入库
                if os.getenv("AUDIENCE", "").lower() == "undergrad" and not score.is_undergraduate_relevant(
                    title, body, enriched["category"]
                ):
                    result.skipped += 1
                    known.add(url_hash)
                    continue

                if dry_run:
                    result.new += 1
                    result.titles.append(title)
                    continue

                payload = {
                    "source_code": source.code,
                    "url": item.url,
                    "url_hash": url_hash,
                    "title": title,
                    "title_norm": text.normalize_title(title),
                    "publisher": item.publisher,
                    "published_at": published,
                    "date_inferred": 0 if published else 1,
                    "category": enriched["category"],
                    "summary": enriched["summary"],
                    "content_md": body,
                    "content_hash": text.content_hash(f"{title}\n{body}"),
                    "audience": enriched["audience"],
                    "action_items": enriched["action_items"],
                    "deadline_date": text.iso(enriched["deadline"]),
                    "importance": enriched["importance"],
                }
                state = db.save_notice(conn, payload)
                if state == "new":
                    result.new += 1
                    db.save_attachments(conn, url_hash, detail.attachments)
                elif state == "updated":
                    result.updated += 1
                known.add(url_hash)

            # 增量模式：整页都已知 → 没有更新的历史，停止翻页
            if not new_items and pages is None:
                progress(f"[{source.code}] 整页均为已知条目，停止翻页")
                break

        if result.status == "ok" and result.errors:
            result.status = "partial"
    finally:
        if run_id is not None:
            db.finish_run(
                conn, run_id,
                status="ok" if result.errors == 0 else "partial",
                pages=result.pages, seen=result.seen, new=result.new,
                updated=result.updated, http_errors=result.errors,
                error=result.error,
            )
            db.mark_source_result(conn, source.code, ok=result.errors == 0 and result.status == "ok",
                                  error=result.error)
    return result


def crawl_all(conn: sqlite3.Connection, sources: list[Source],
              progress: Callable[[str], None] = log.info) -> list[SourceResult]:
    from .fetch import cleanup_snapshots

    removed = cleanup_snapshots(days=int(os.getenv("SNAPSHOT_KEEP_DAYS", "7")))
    if removed:
        log.info("清理过期快照目录 %s 个", removed)

    results = []
    with Fetcher() as fetcher:
        for source in sources:
            try:
                results.append(crawl_source(conn, source, fetcher, progress=progress))
            except Exception as exc:  # noqa: BLE001
                log.exception("crawl %s failed", source.code)
                results.append(SourceResult(code=source.code, status="failed", error=str(exc)))
    return results

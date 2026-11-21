"""信源配置：读取 YAML → Source 对象。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = ROOT / "config" / "sources.yaml"
FALLBACK_SOURCES = ROOT / "config" / "sources.example.yaml"


@dataclass
class Pagination:
    mode: str = "none"          # path_desc | query | none
    first_page_url: str | None = None
    page_url_template: str | None = None
    max_page: int = 50
    backfill_pages: int = 2


@dataclass
class Source:
    code: str
    name: str
    level: str
    list_url: str
    weight: int = 70
    enabled: bool = True
    interval_minutes: int = 30
    engine: str = "http"
    pagination: Pagination = field(default_factory=Pagination)
    items_xpath: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    detail_title: str = ""
    detail_date: str = ""
    detail_content: str = ""
    detail_attachments: str = ""

    def page_urls(self, pages: int | None = None) -> list[str]:
        """生成要抓取的列表页 URL（第 1 页 + 若干翻页）。

        path_desc 站点的页码是倒序的：第 1 页是 tzgg.htm，
        第 2 页是 tzgg/{max_page}.htm，第 3 页是 tzgg/{max_page-1}.htm …
        因此第 p 页（p≥2）对应 max_page + 1 - p。
        """
        n = pages or self.pagination.backfill_pages or 1
        urls = [self.pagination.first_page_url or self.list_url]
        if self.pagination.mode == "path_desc" and self.pagination.page_url_template:
            for p in range(2, n + 1):
                num = max(1, self.pagination.max_page + 1 - p)
                urls.append(self.pagination.page_url_template.format(n=num))
        elif self.pagination.mode == "query" and self.pagination.page_url_template:
            for p in range(2, n + 1):
                urls.append(self.pagination.page_url_template.format(n=p))
        return urls


def _pagination(raw: dict | None) -> Pagination:
    raw = raw or {}
    return Pagination(
        mode=raw.get("mode", "none"),
        first_page_url=raw.get("first_page_url"),
        page_url_template=raw.get("page_url_template"),
        max_page=int(raw.get("max_page", 50)),
        backfill_pages=int(raw.get("backfill_pages", 2)),
    )


def load_sources(path: str | Path | None = None, include_disabled: bool = False) -> list[Source]:
    p = Path(path) if path else DEFAULT_SOURCES
    if not p.exists():
        p = FALLBACK_SOURCES
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") or {}
    result: list[Source] = []
    for raw in data.get("sources") or []:
        if not include_disabled and not raw.get("enabled", True):
            continue
        lst = raw.get("list") or {}
        items = lst.get("items") or {}
        detail = raw.get("detail") or {}
        result.append(
            Source(
                code=raw["code"],
                name=raw.get("name", raw["code"]),
                level=raw.get("level", "university"),
                list_url=lst.get("url", ""),
                weight=int(raw.get("weight", 70)),
                enabled=bool(raw.get("enabled", True)),
                interval_minutes=int(raw.get("interval_minutes", defaults.get("interval_minutes", 30))),
                engine=raw.get("engine", defaults.get("engine", "http")),
                pagination=_pagination(lst.get("pagination")),
                items_xpath=items.get("xpath", ""),
                fields=items.get("fields") or {},
                detail_title=detail.get("title", ""),
                detail_date=detail.get("published_at", ""),
                detail_content=detail.get("content", ""),
                detail_attachments=detail.get("attachments", ""),
            )
        )
    return result


def get_source(code: str) -> Source:
    for s in load_sources(include_disabled=True):
        if s.code == code:
            return s
    raise KeyError(f"unknown source: {code}")

"""列表页 / 详情页解析：配置里的 XPath 只做定位，正文允许自动退化。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from lxml import html as lhtml

from . import text
from .sources import Source

log = logging.getLogger(__name__)

JUNK_TITLES = {
    "通知公告", "正文", "首页", "武汉大学", "新闻动态", "更多", "查看更多",
    "系统提示", "提示信息", "信息公开年报", "信息公开指南", "信息公开目录",
    "最新公开", "学校基本信息", "依申请公开流程",
}
ERROR_MARKERS = ("暂无权限", "页面不存在", "内容不存在", "您访问的页面", "404 Not Found")
DEFAULT_ATTACHMENT_XPATH = (
    "//a[contains(@href,'download.jsp') or contains(@href,'.pdf') "
    "or contains(@href,'.docx') or contains(@href,'.doc') "
    "or contains(@href,'.xlsx') or contains(@href,'.xls') or contains(@href,'.zip')]"
)


@dataclass
class RawItem:
    title: str
    url: str
    published_at: str | None = None
    publisher: str | None = None


@dataclass
class Detail:
    title: str = ""
    published_at: str | None = None
    content_text: str = ""
    attachments: list[dict] = field(default_factory=list)
    restricted: bool = False   # True = 该页返回"暂无权限/404"等错误页，对外不可访问


def _extract(node, expr: str) -> str:
    """执行 XPath：属性返回字符串值，元素返回文本内容。"""
    if not expr:
        return ""
    try:
        res = node.xpath(expr)
    except Exception as exc:  # noqa: BLE001
        log.debug("xpath error %r: %s", expr, exc)
        return ""
    if not res:
        return ""
    value = res[0]
    if isinstance(value, str):
        return value.strip()
    try:
        return value.text_content().strip()
    except Exception:  # noqa: BLE001
        return str(value).strip()


def _first(doc, expr: str | None) -> str:
    """expr 支持 'a | b' 多个候选，返回第一个非空且非垃圾的值。"""
    if not expr:
        return ""
    for part in [p.strip() for p in expr.split("|") if p.strip()]:
        value = _extract(doc, part)
        if value and value not in JUNK_TITLES and 2 <= len(value) <= 200:
            return value
    return ""


def choose_title(list_title: str, detail_title: str) -> str:
    """列表标题更可靠（详情页常把栏目标题当 h1，如"短期项目"）。

    只有列表标题缺失、过短或被省略号截断时，才采用详情页标题。
    """
    list_title = (list_title or "").strip()
    detail_title = (detail_title or "").strip()
    if not detail_title:
        return list_title
    if not list_title:
        return detail_title
    if list_title.endswith(("…", "...")):
        return detail_title if len(detail_title) > len(list_title) else list_title
    if len(list_title) >= 6:
        return list_title
    return detail_title if len(detail_title) > len(list_title) else list_title


BOILERPLATE_TAILS = ("分享到：", "分享到:", "上一条：", "下一条：", "打印本页", "关闭窗口", "【打印", "（编辑：", "点击量：")


def clean_body(body: str) -> str:
    """去掉正文里的面包屑/分享/上下篇等模板文本。"""
    t = (body or "").strip()
    if not t:
        return t
    # 面包屑："当前位置:本站首页>>短期项目>>正文"
    idx = t.find("正文")
    if 0 <= idx <= 160:
        t = t[idx + 2:].lstrip(" ：:>»/")
    cut = min([t.find(m) for m in BOILERPLATE_TAILS if t.find(m) > 200] or [len(t)])
    return t[:cut].strip()


def parse_list(page_html: str, source: Source, base_url: str) -> list[RawItem]:
    """解析列表页，返回去重后的条目列表。"""
    if not page_html:
        return []
    try:
        doc = lhtml.fromstring(page_html)
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_list failed for %s: %s", source.code, exc)
        return []

    items: list[RawItem] = []
    seen: set[str] = set()
    for node in doc.xpath(source.items_xpath):
        title = _extract(node, source.fields.get("title", ""))
        url = _extract(node, source.fields.get("url", ""))
        if not title or not url:
            continue
        title = text.strip_html(title)
        # 过滤导航/提示类伪条目
        if title in JUNK_TITLES or len(title) < 4:
            continue
        url = urljoin(base_url, url)
        if not url.lower().startswith("http"):
            continue
        published = _extract(node, source.fields.get("published_at", "")) or None
        if published and text.parse_date(published) is None:
            published = None
        key = text.url_hash(url)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            RawItem(
                title=title,
                url=url,
                published_at=published,
                publisher=_extract(node, source.fields.get("publisher", "")) or None,
            )
        )
    return items


def parse_detail(page_html: str, source: Source, url: str, list_date: str | None = None) -> Detail:
    """解析详情页：标题、发布时间、正文、附件。"""
    detail = Detail()
    if not page_html:
        return detail
    try:
        doc = lhtml.fromstring(page_html)
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_detail failed for %s: %s", source.code, exc)
        return detail

    detail.title = _first(doc, source.detail_title)
    if not detail.title:
        raw_title = _extract(doc, "//title")
        if raw_title:
            detail.title = re.split(r"[-_|—]", text.strip_html(raw_title))[0].strip()
    if detail.title in JUNK_TITLES:
        detail.title = ""

    # 发布时间：先按配置节点，再全文正则兜底
    date_text = _extract(doc, source.detail_date) if source.detail_date else ""
    published = text.parse_date(date_text) if date_text else None
    if not published:
        page_text = doc.xpath("string(//body)")
        m = re.search(r"(?:发布时间|发布日期|时间)\s*[：:]\s*([0-9]{4}[-年/.][0-9]{1,2}[-月/.][0-9]{1,2})", page_text)
        if m:
            published = text.parse_date(m.group(1))
    if not published:
        m = re.search(r"(?:发布时间|发布日期)\s*[：:]\s*([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})", page_html)
        if m:
            published = text.parse_date(m.group(1))
    if not published and list_date:
        published = text.parse_date(list_date)
    detail.published_at = text.iso(published)

    # 正文：配置节点优先，长度不足则自动挑选最长文本块
    body = ""
    for expr in [p.strip() for p in (source.detail_content or "").split("|") if p.strip()]:
        body = _extract(doc, expr)
        if len(body) >= 40:
            break
    if len(body) < 40:
        body = _auto_body(doc)
    detail.content_text = clean_body(text.strip_html(body))

    # 错误页（如"暂无权限/404"）：不要污染标题和正文，交给调用方按"受限通知"处理。
    # 注意：错误提示文字可能不在正文块里，必须检查整页文本。
    full_text = doc.xpath("string(//body)")
    page_title = _extract(doc, "//title")
    if (
        any(marker in full_text for marker in ERROR_MARKERS)
        or any(marker in page_title for marker in (*ERROR_MARKERS, "系统提示", "404错误提示"))
        or "系统提示" in detail.title
        or "可能是由下列问题导致" in full_text
        or (not detail.title and len(detail.content_text) < 10)
    ):
        log.info("受限/错误页，跳过: %s", url)
        detail.restricted = True
        detail.title = ""
        detail.content_text = ""
        detail.attachments = []
        return detail

    # 附件
    att_xpath = source.detail_attachments or DEFAULT_ATTACHMENT_XPATH
    for a in doc.xpath(att_xpath):
        href = a.get("href") or ""
        name = (a.text_content() or "").strip() or href.rsplit("/", 1)[-1]
        if not href:
            continue
        detail.attachments.append({"name": text.strip_html(name), "url": urljoin(url, href)})

    return detail


def _auto_body(doc) -> str:
    """正文自动抽取：取包含最多中文文本的 div（排除导航/页脚）。"""
    best, best_len = "", 0
    for div in doc.xpath("//div|//article|//section"):
        classes = " ".join(div.get("class", "").split()).lower()
        if any(k in classes for k in ("nav", "header", "footer", "menu", "crumb", "banner", "sidebar")):
            continue
        value = div.text_content()
        length = len(re.findall(r"[\u4e00-\u9fff]", value))
        if length > best_len:
            best, best_len = value, length
    return best


def looks_like_drift(items: list[RawItem]) -> bool:
    """列表页解析出 0 条 → 可能改版或页面异常。"""
    return len(items) == 0

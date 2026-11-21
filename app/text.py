"""文本与 URL 规范化工具。"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 抓取 URL 时需要剔除的跟踪参数
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "from", "spm", "share_token", "poc_token",
}

_PUNCT_RE = re.compile(r"[\s\u3000·•,，。、；;：:！!？?（）()\[\]【】《》<>\"'“”‘’\-—_/\\|]+")
_DATE_PATTERNS = [
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})"),
]
_SHORT_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)")


def strip_html(text: str | None) -> str:
    """去标签 + 反转义 + 压缩空白。"""
    if not text:
        return ""
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(url: str) -> str:
    """规范化 URL：统一 scheme/host、去 fragment、去跟踪参数。

    content.jsp?wbtreeid=X&wbnewsid=Y 与 /info/X/Y.htm 指向同一篇，
    这里统一映射成 /info/X/Y.htm 以便跨入口去重（仅用于生成哈希）。
    """
    url = (url or "").strip()
    parts = urlsplit(url)
    scheme = "https" if parts.scheme in ("http", "https", "HTTPS", "HTTP") else parts.scheme
    netloc = parts.netloc.lower()
    for suffix in (":80", ":443"):
        if netloc.endswith(suffix):
            netloc = netloc[: -len(suffix)]
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    qs = dict(query_pairs)
    if "wbnewsid" in qs and "wbtreeid" in qs:
        return urlunsplit((scheme, netloc, f"/info/{qs['wbtreeid']}/{qs['wbnewsid']}.htm", "", ""))
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query_pairs, doseq=True), ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    """标题归一：全角转半角、去标点空白，用于跨源近似匹配。"""
    t = unicodedata.normalize("NFKC", title or "")
    return _PUNCT_RE.sub("", t).lower()


def parse_date(text: str | None, default_year: int | None = None) -> date | None:
    """从文本中解析日期；支持 2026-11-20 / 2026年11月20日 / 2026/11/20 / 11-20。"""
    if not text:
        return None
    text = unicodedata.normalize("NFKC", str(text))
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                return date(y, mo, d)
            except ValueError:
                continue
    m = _SHORT_DATE_RE.search(text)
    if m and default_year:
        try:
            return date(default_year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def iso(d: date | datetime | None) -> str | None:
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def snippet(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def guess_category(title: str, body: str = "") -> str:
    """规则分类：按顺序命中，先具体后宽泛。"""
    text = (title or "") + " " + (body or "")[:400]
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("会议", ("会议", "大会", "座谈会", "工作会", "培训")),
        ("讲座", ("珞珈讲坛", "讲座", "论坛", "报告会", "学术交流", "沙龙")),
        ("招聘", ("招聘", "博士后", "人才引进", "岗位", "应聘", "编制")),
        ("公示", ("公示", "名单", "拟推荐", "拟录取", "异议", "征求意见")),
        ("奖助", ("奖学金", "助学金", "资助", "评优", "困难补助", "助学")),
        ("招生", ("招生", "推免", "免试", "复试", "调剂", "博士", "硕士", "报考", "录取")),
        ("考试", ("考试", "缓考", "补考", "四六级", "考场", "监考")),
        ("教务", ("选课", "课程", "教学", "培养方案", "学分", "重修", "辅修", "转专业", "学籍", "毕业")),
        ("竞赛", ("竞赛", "大赛", "比赛", "挑战杯", "创新创业", "数学建模")),
        ("科研", ("项目申报", "基金", "课题", "科研", "论文", "成果")),
        ("生活服务", ("停水", "停电", "维修", "食堂", "宿舍", "校车", "门禁", "交通", "医疗", "医保")),
        ("人事", ("任免", "干部", "职称", "考核", "聘用", "调动")),
    ]
    for category, words in rules:
        if any(w in text for w in words):
            return category
    return "其他"


def guess_audience(text: str) -> list[str]:
    text = text or ""
    audience = []
    mapping = [
        ("本科生", ("本科生", "本科", "大四", "应届本科")),
        ("研究生", ("研究生", "硕士", "博士", "硕博")),
        ("博士生", ("博士",)),
        ("教师", ("教师", "教职工", "老师")),
        ("党员", ("党员", "党支部", "党委")),
        ("新生", ("新生", "入学", "迎新")),
    ]
    for name, words in mapping:
        if any(w in text for w in words):
            audience.append(name)
    return audience


DEADLINE_PATTERNS = [
    re.compile(r"(?:截止|截至|不迟于|之前|前)[^。；;]{0,24}?(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}日?)"),
    re.compile(r"(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}日?)\s*(?:前|之前|截止)"),
    re.compile(r"请于\s*(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}日?)"),
]


def extract_deadline(title: str, body: str) -> date | None:
    text = f"{title} {body[:1500]}"
    for pat in DEADLINE_PATTERNS:
        m = pat.search(text)
        if m:
            d = parse_date(m.group(1))
            if d:
                return d
    return None

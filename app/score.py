"""规则打分与结构化字段抽取（W1 不依赖 LLM）。"""
from __future__ import annotations

import re
from datetime import date, datetime

from . import text

CATEGORY_WEIGHT = {
    "招生": 0.95, "考试": 0.95, "奖助": 0.9, "教务": 0.85,
    "竞赛": 0.7, "科研": 0.6, "生活服务": 0.65, "公示": 0.55,
    "人事": 0.5, "招聘": 0.45, "讲座": 0.35, "会议": 0.3, "其他": 0.4,
}

URGENT_WORDS = ("紧急", "重要", "务必", "逾期", "截止", "最后一次", "补录", "临时")
ACTION_WORDS = ("请", "于", "提交", "报名", "报送", "填写", "参加", "携带", "缴纳", "打印")

# ---------------------------------------------------------------------------
# 本科生相关性过滤（AUDIENCE=undergrad 时生效）
# ---------------------------------------------------------------------------
UNDERGRAD_POSITIVE = (
    "本科", "本科生", "大四", "大三", "推免", "免试研究生", "保研", "选课", "撤课",
    "缓考", "补考", "四六级", "转专业", "辅修", "学分", "学籍", "毕业", "学位",
    "实习", "竞赛", "大创", "奖学金", "助学金", "评优", "学风", "军训", "迎新",
    "宿舍", "培养方案", "专业分流", "实验班", "毕业论文", "毕业设计", "大学生",
)
# 标题里出现这些词，基本可以确定只针对本科生
UNDERGRAD_STRONG = (
    "本科", "本科生", "大四", "大三", "推免", "推荐免试", "免试", "保研",
    "转专业", "辅修", "选课", "缓考", "补考", "四六级", "实验班",
    "专业分流", "毕业设计", "毕业论文",
)
# 明确与本科生无关的表述（优先级最高，避免"本科生工作办公室"这类误判）
HARD_NEGATIVE_PHRASES = ("民主推荐", "副主任", "选拔任用", "拟任", "任前公示")
GRAD_STAFF_ONLY = (
    "博士", "硕士", "研究生", "硕博", "博士后", "导师", "学位论文", "开题", "答辩",
    "教师", "教职工", "教工", "职称", "人事", "干部", "任免", "人才引进",
    "基金", "课题", "项目申报", "招标", "采购", "科研项目", "评审专家", "考察",
)
# 这类栏目整体与本科生关系弱
DROP_CATEGORIES = {"人事", "招聘", "科研", "会议", "讲座"}


def is_undergraduate_relevant(title: str, body: str = "", category: str = "其他") -> bool:
    """判断是否与本科生相关。

    优先级：标题里的"强本科词" > 标题里的"研究生/教师专属词" > 弱栏目 > 正文判断。
    """
    title = title or ""
    body = body or ""

    if any(phrase in title for phrase in HARD_NEGATIVE_PHRASES):
        return False
    if any(word in title for word in GRAD_STAFF_ONLY) and not any(
        word in title for word in UNDERGRAD_STRONG
    ):
        return False
    if any(word in title for word in UNDERGRAD_STRONG):
        return True
    if any(word in title for word in UNDERGRAD_POSITIVE):
        return True
    if category in DROP_CATEGORIES:
        return False

    text = f"{title} {body[:600]}"
    if any(word in text for word in UNDERGRAD_STRONG):
        return True
    if any(word in text for word in GRAD_STAFF_ONLY):
        return False
    # 中性通知（放假、停水停电、校门管理等）保留
    return True


def importance(source_weight: int, category: str, deadline: date | None,
               published: date | None, title: str, body: str = "") -> int:
    score = 0.35 * source_weight
    score += 30 * CATEGORY_WEIGHT.get(category, 0.4)

    today = date.today()
    if deadline:
        days = (deadline - today).days
        if days < 0:
            score += 0
        elif days <= 3:
            score += 20
        elif days <= 7:
            score += 15
        elif days <= 30:
            score += 10
        else:
            score += 5
    else:
        score += 5

    head = f"{title} {body[:300]}"
    if any(w in head for w in URGENT_WORDS):
        score += 8
    if published:
        age = (today - published).days
        if age <= 1:
            score += 7
        elif age <= 3:
            score += 5
        elif age <= 7:
            score += 2

    return max(0, min(100, int(round(score))))


def summarize(title: str, body: str, limit: int = 90) -> str:
    """一句话摘要：优先取正文前几句，去掉来源/附件等样板。"""
    body = re.sub(r"\s+", "", body or "")
    body = re.sub(r"^(来源|编辑|审核|通讯员)[：:].*?$", "", body)
    body = body.replace("附件【", " 附件：")
    if not body:
        return title[:limit]
    sentences = re.split(r"(?<=[。！？；])", body)
    buf = ""
    for sentence in sentences:
        if len(buf) >= limit:
            break
        buf += sentence
        if len(buf) >= 30:
            break
    summary = buf or body[:limit]
    return summary[:limit] + ("…" if len(summary) > limit else "")


def action_items(title: str, body: str, deadline: date | None) -> list[str]:
    """粗糙但有用的行动项：找出带"请/于/提交/报名"的句子。"""
    items: list[str] = []
    for sentence in re.split(r"(?<=[。；])", body or ""):
        s = sentence.strip()
        if 8 <= len(s) <= 80 and any(w in s for w in ACTION_WORDS):
            items.append(s.rstrip("。；"))
        if len(items) >= 3:
            break
    if deadline and not items:
        items.append(f"截止日期：{deadline.isoformat()}")
    return items


def enrich(title: str, body: str, published_at: str | None, source_weight: int) -> dict:
    published = text.parse_date(published_at) if published_at else None
    category = text.guess_category(title, body)
    deadline = text.extract_deadline(title, body)
    return {
        "category": category,
        "summary": summarize(title, body),
        "audience": text.guess_audience(f"{title} {body[:600]}"),
        "action_items": action_items(title, body, deadline),
        "deadline": deadline,
        "importance": importance(source_weight, category, deadline, published, title, body),
    }


def parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None

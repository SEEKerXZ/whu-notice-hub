"""人物介绍（彩蛋）：群里有人让介绍「胡豪宇」时回复固定简介。

触发别名：北郊HH / bjhh / hygg / hhy / 胡豪宇 / 豪宇 / 老大
其中「老大」太常用，必须带「介绍/是谁/哪位/资料/简介/谁」等词才触发。
"""
from __future__ import annotations

import os
import re

PROFILE = (
    "胡豪宇，男，中共预备党员，2023级本科生。自大二上学期起担任计算机学院荣誉课程助教、"
    "「珞青学海领航团」讲师。在学业与科研竞赛方面，始终保持精益求精的态度，gpa3.95，"
    "55门课程成绩达90分以上；积极参与各类学科竞赛，累计斩获包括5项省部级及以上荣誉在内的23项奖项，"
    "在高强度挑战中不断提升解决复杂问题的能力。"
    "作为荣誉课程助教与学海领航团讲师，热心朋辈互助与学业辅导，潜心钻研教学方法，"
    "将枯燥算法与复杂数学转化为易懂案例；主动组织「期末冲刺」集中答疑活动，"
    "积极参与学业指导与经验分享活动，并利用课余时间录制多部网课视频，助力学校优质课程资源建设，"
    "因教学效果显著获评「优秀助教」与「优秀讲师」。"
    "在社会实践方面，积极践行「尚德」精神，累计志愿时长约240小时，"
    "曾赴贵州省毕节市织金县开展支教活动，将个人所学转化为服务社会的能量。"
    "曾获国家奖学金、学校甲等奖学金，获评校级「三好学生」「优秀共青团员」"
    "「武汉大学2024年优秀青年志愿者」称号，用实际行动诠释了新时代青年有理想、敢担当、能吃苦、肯奋斗的先锋本色。"
)

# 强别名：出现即触发
STRONG_ALIASES = ("北郊hh", "bjhh", "hygg", "hhy", "胡豪宇", "豪宇")
# 弱别名：需要配合「介绍类」问句
WEAK_ALIASES = ("老大",)
QUESTION_HINTS = ("介绍", "是谁", "哪位", "资料", "简介", "是谁呀", "谁啊", "什么人", "了解一下")


def _hit(content: str, alias: str) -> bool:
    """英文别名要求词边界，避免 hhy 命中 hhyy 这类误判；中文直接子串匹配。"""
    if alias.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", content) is not None
    return alias in content


def matches(text: str | None) -> bool:
    content = (text or "").strip().lower()
    if not content:
        return False
    if any(_hit(content, alias) for alias in STRONG_ALIASES):
        return True
    if any(_hit(content, alias) for alias in WEAK_ALIASES):
        return any(hint in content for hint in QUESTION_HINTS)
    return False


def build_reply() -> str:
    prefix = "喵～介绍来啦：\n" if os.getenv("PERSONA", "catgirl") != "default" else ""
    return f"{prefix}{PROFILE}"

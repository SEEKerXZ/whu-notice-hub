"""打分与摘要测试。"""
from datetime import date, timedelta

from app import score


def test_importance_urgent_higher_than_distant():
    today = date.today()
    urgent = score.importance(85, "招生", today + timedelta(days=2), today, "推免报名")
    distant = score.importance(85, "招生", today + timedelta(days=60), today, "推免报名")
    none = score.importance(85, "招生", None, today, "推免报名")
    assert urgent > distant
    assert urgent > none


def test_importance_category_matters():
    today = date.today()
    exam = score.importance(70, "考试", None, today, "期末考试安排")
    lecture = score.importance(70, "讲座", None, today, "珞珈讲坛预告")
    assert exam > lecture


def test_importance_bounded():
    assert 0 <= score.importance(0, "其他", None, None, "") <= 100
    assert 0 <= score.importance(100, "招生", date.today(), date.today(), "紧急 推免") <= 100


def test_summary_length():
    body = "根据《武汉大学2026年招收攻读博士学位研究生章程》文件精神，现将我院综合考核相关事项通知如下：" * 3
    s = score.summarize("综合考核通知", body, limit=80)
    assert 0 < len(s) <= 81


def test_enrich_fields():
    out = score.enrich(
        "计算机学院2026年第三批次博士入学综合考核工作通知",
        "请于2026年12月1日前提交纸质材料，逾期不再受理。",
        "2026-11-20", 85,
    )
    assert out["category"] == "招生"
    assert out["deadline"] == date(2026, 12, 1)
    assert out["importance"] > 70
    assert isinstance(out["audience"], list)


def test_action_items_extracted():
    items = score.action_items("通知", "请于6月1日前提交纸质材料。逾期不再受理。", date(2026, 6, 1))
    assert any("提交" in i for i in items)


def test_undergrad_filter_keeps_relevant():
    assert score.is_undergraduate_relevant("关于2027届推荐免试研究生工作的通知", "", "招生")
    assert score.is_undergraduate_relevant("关于本科生选课的通知", "", "教务")
    assert score.is_undergraduate_relevant("2026年国庆节放假安排", "", "其他")
    assert score.is_undergraduate_relevant("文理学部分区域临时停电通知", "", "生活服务")
    assert score.is_undergraduate_relevant("计算机学院本科生专项奖学金评选通知", "", "奖助")


def test_undergrad_filter_drops_graduate_and_staff():
    assert not score.is_undergraduate_relevant("2026年第三批次博士入学综合考核通知", "", "招生")
    assert not score.is_undergraduate_relevant("计算机学院硕博连读生选拔考核实施细则", "", "招生")
    assert not score.is_undergraduate_relevant("2025-2026学年优秀学业奖学金推荐研究生名单公示", "", "公示")
    assert not score.is_undergraduate_relevant("关于开展博士后招聘的通知", "", "招聘")
    assert not score.is_undergraduate_relevant("关于申报国家自然科学基金项目的通知", "", "科研")
    assert not score.is_undergraduate_relevant("关于召开全院教职工大会的通知", "", "会议")
    assert not score.is_undergraduate_relevant("关于某某同志任免的通知", "", "人事")
    assert not score.is_undergraduate_relevant("考察公告", "", "其他")
    assert not score.is_undergraduate_relevant("珞珈讲坛第552讲预告", "", "讲座")
    assert not score.is_undergraduate_relevant(
        "关于以民主推荐方式选拔计算机学院本科生工作办公室副主任的公告", "", "其他")


def test_undergrad_filter_positive_overrides_category():
    # 明确提到本科生时，即使分类是讲座/会议也保留
    assert score.is_undergraduate_relevant("本科生学业指导讲座", "", "讲座")
    assert score.is_undergraduate_relevant("本科生毕业设计动员会", "", "会议")

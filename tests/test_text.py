"""文本规范化、日期解析、分类规则测试。"""
from datetime import date

from app import text


def test_canonical_url_maps_vsb_content_jsp_to_info_path():
    a = text.canonical_url("https://cs.whu.edu.cn/content.jsp?urltype=news.NewsContentUrl&wbtreeid=1055&wbnewsid=61071")
    b = text.canonical_url("https://cs.whu.edu.cn/info/1055/61071.htm")
    assert a == b == "https://cs.whu.edu.cn/info/1055/61071.htm"
    assert text.url_hash(a) == text.url_hash(b)


def test_canonical_url_strips_tracking_and_fragment():
    url = "http://www.whu.edu.cn/tzgg.htm?utm_source=x&from=wx#top"
    assert text.canonical_url(url) == "https://www.whu.edu.cn/tzgg.htm"


def test_normalize_title_removes_punct_and_width():
    assert text.normalize_title("关于做好２０２６年 推免工作的通知！") == \
        text.normalize_title("关于做好2026年推免工作的通知")


def test_parse_date_variants():
    assert text.parse_date("2026-11-20") == date(2026, 11, 20)
    assert text.parse_date("2026年11月20日") == date(2026, 11, 20)
    assert text.parse_date("2026/11/20") == date(2026, 11, 20)
    assert text.parse_date("发布时间：2026-11-20 10:30") == date(2026, 11, 20)
    assert text.parse_date("11-20", default_year=2026) == date(2026, 11, 20)
    assert text.parse_date("没有日期") is None


def test_guess_category():
    assert text.guess_category("计算机学院2027届推荐免试研究生工作实施细则") == "招生"
    assert text.guess_category("关于2026年二次供水泵站清洗消毒及部分区域停水的通知") == "生活服务"
    assert text.guess_category("珞珈讲坛第552讲预告") == "讲座"
    assert text.guess_category("关于评选2025-2026学年度奖学金的通知") == "奖助"


def test_extract_deadline():
    body = "请于2026年6月1日前提交纸质材料，逾期不再受理。"
    assert text.extract_deadline("某通知", body) == date(2026, 6, 1)


def test_snippet_truncates():
    assert text.snippet("字" * 200, limit=50).endswith("…")
    assert len(text.snippet("字" * 200, limit=50)) == 51

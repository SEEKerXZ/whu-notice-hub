"""列表页 / 详情页解析测试（用最小 HTML 复现真实结构）。"""
from app import parse
from app.sources import Pagination, Source

MAIN_TABLE_HTML = """
<html><body>
<table>
  <tr><th>标题</th><th>发布单位</th><th>发布日期</th><th>浏览次数</th></tr>
  <tr>
    <td><a href="info/5231/278674.htm">会议通知</a></td>
    <td>党政办公室 党委宣传部</td>
    <td>2026-11-20</td>
    <td></td>
  </tr>
  <tr>
    <td><a href="info/5231/277904.htm">珞珈讲坛第552讲预告</a></td>
    <td>科学技术发展研究院</td>
    <td>2026-11-07</td>
    <td></td>
  </tr>
</table>
</body></html>
"""

CS_LIST_HTML = """
<html><body><ul>
  <li><a href="../info/1055/68401.htm" title="武汉大学计算机学院">
      <p>计算机学院2026-2027学年硕博连读生选拔考核实施细则</p><span>2026-11-18</span></a></li>
  <li><a href="../content.jsp?urltype=news.NewsContentUrl&wbtreeid=1055&wbnewsid=68171">
      <p>考察公告</p><span>2026-11-17</span></a></li>
</ul></body></html>
"""

DETAIL_HTML = """
<html><head><title>会议通知-武汉大学</title></head><body>
<div class="ar_tit"><h1>会议通知</h1><p>发布时间：2026-11-20</p></div>
<div id="vsb_content_6"><p>各单位：</p><p>学校定于2026年11月25日召开工作会议，请于11月22日前报送参会名单。</p></div>
</body></html>
"""


def _main_source() -> Source:
    return Source(
        code="whu_main", name="官网", level="university",
        list_url="https://www.whu.edu.cn/tzgg.htm",
        items_xpath="//table//tr[td]",
        fields={"title": "./td[1]//a", "url": "./td[1]//a/@href",
                "publisher": "./td[2]", "published_at": "./td[3]"},
        detail_title="//div[contains(@class,'ar_tit')]//h1 | //h2",
        detail_content="//div[@id='vsb_content_6']",
        pagination=Pagination(mode="path_desc", max_page=261,
                              page_url_template="https://www.whu.edu.cn/tzgg/{n}.htm",
                              backfill_pages=3),
    )


def _cs_source() -> Source:
    return Source(
        code="cs_whu", name="计院", level="college",
        list_url="https://cs.whu.edu.cn/xwdt/tzgg.htm",
        items_xpath="//li[a[contains(@href,'/info/') or contains(@href,'content.jsp')]]",
        fields={"title": "./a/p", "url": "./a/@href", "published_at": "./a/span"},
        detail_title="//h2 | //h1",
        detail_content="//div[@id='vsb_content'] | //div[contains(@class,'article-content')]",
    )


def test_parse_main_table():
    items = parse.parse_list(MAIN_TABLE_HTML, _main_source(), "https://www.whu.edu.cn/tzgg.htm")
    assert len(items) == 2
    assert items[0].title == "会议通知"
    assert items[0].url == "https://www.whu.edu.cn/info/5231/278674.htm"
    assert items[0].publisher == "党政办公室 党委宣传部"
    assert items[0].published_at == "2026-11-20"


def test_parse_college_list_and_relative_urls():
    items = parse.parse_list(CS_LIST_HTML, _cs_source(), "https://cs.whu.edu.cn/xwdt/tzgg.htm")
    assert len(items) == 2
    assert items[0].url == "https://cs.whu.edu.cn/info/1055/68401.htm"
    assert items[1].title == "考察公告"


def test_parse_detail_title_date_content():
    detail = parse.parse_detail(DETAIL_HTML, _main_source(), "https://www.whu.edu.cn/info/5231/278674.htm")
    assert detail.title == "会议通知"
    assert detail.published_at == "2026-11-20"
    assert "报送参会名单" in detail.content_text


def test_parse_detail_falls_back_to_title_tag():
    html = "<html><head><title>某通知-武汉大学</title></head><body><div>正文内容足够长" + "啊" * 60 + "</div></body></html>"
    detail = parse.parse_detail(html, _main_source(), "https://www.whu.edu.cn/info/1/2.htm")
    assert detail.title == "某通知"


def test_page_urls_generation():
    """第 1 页是列表首页，第 2 页对应 max_page，页码递减（博达 CMS 倒序）。"""
    source = _main_source()
    urls = source.page_urls(pages=3)
    assert urls[0].endswith("/tzgg.htm")
    assert urls[1].endswith("/tzgg/260.htm")
    assert urls[2].endswith("/tzgg/259.htm")


JUNK_LIST_HTML = """
<html><body><ul>
  <li><a href="../content.jsp?wbtreeid=1055&wbnewsid=1"><p>查看更多</p><span>2026-11-01</span></a></li>
  <li><a href="../content.jsp?wbtreeid=1055&wbnewsid=2"><p>系统提示</p><span>2026-11-01</span></a></li>
  <li><a href="../info/1055/3.htm"><p>关于开展奖学金评选工作的通知</p><span>2026-11-02</span></a></li>
</ul></body></html>
"""


def test_parse_list_skips_junk_titles():
    items = parse.parse_list(JUNK_LIST_HTML, _cs_source(), "https://cs.whu.edu.cn/xwdt/tzgg.htm")
    assert [i.title for i in items] == ["关于开展奖学金评选工作的通知"]


def test_parse_detail_error_page_returns_empty():
    html = "<html><head><title>系统提示</title></head><body>系统提示 抱歉 暂无权限，请咨询管理员。</body></html>"
    detail = parse.parse_detail(html, _main_source(), "https://www.whu.edu.cn/new2024/tzggnr.jsp?wbnewsid=1")
    assert detail.title == ""
    assert detail.content_text == ""
    assert detail.restricted is True


def test_parse_detail_404_page_is_restricted():
    html = "<html><head><title>404错误提示</title></head><body>页面不存在</body></html>"
    detail = parse.parse_detail(html, _main_source(), "https://www.whu.edu.cn/info/1/9.htm")
    assert detail.restricted is True


def test_parse_detail_permission_page_detected_from_full_body():
    """权限提示文字在 <li> 里、正文块只抽到一句"可能是由下列问题导致的"，也要识别为受限。"""
    html = """
    <html><head><title>系统提示</title></head><body>
      <h1>系统提示</h1>
      <p>抱歉</p>
      <p>可能是由下列问题导致的：</p>
      <ul><li>暂无权限，请咨询管理员。</li></ul>
    </body></html>
    """
    detail = parse.parse_detail(html, _main_source(), "https://cs.whu.edu.cn/content.jsp?wbnewsid=1")
    assert detail.restricted is True
    assert detail.content_text == ""


INFO_LIST_HTML = """
<html><body><div class="list"><ul>
  <li><a href="http://oir.whu.edu.cn/info/1198/46111.htm" title="[学生交流合作项目]通知">
    <p>关于申请2027年加拿大英属哥伦比亚大学VSP暑期项目的通知</p><span>2026-11-16</span></a></li>
  <li><a href="../info/1501/1275.htm"><p>武汉大学章程（中文版，2022年11月修正）</p><span>2014-10-15</span></a></li>
</ul></div></body></html>
"""


def test_choose_title_prefers_list_title():
    # 详情页 h1 常是栏目标题，列表标题才准确
    assert parse.choose_title("关于申请2027年VSP暑期项目的通知", "短期项目") == "关于申请2027年VSP暑期项目的通知"
    # 列表标题被截断时用详情页标题
    assert parse.choose_title("关于申请2027年VSP暑期…", "关于申请2027年VSP暑期项目的通知") == \
        "关于申请2027年VSP暑期项目的通知"
    # 列表标题过短时用详情页标题
    assert parse.choose_title("通知", "关于做好期末教学工作的通知") == "关于做好期末教学工作的通知"


def test_clean_body_removes_breadcrumb():
    body = "当前位置:本站首页>>短期项目>>正文 海外学习项目总览 关于申请项目的通知正文内容"
    cleaned = parse.clean_body(body)
    assert cleaned.startswith("海外学习项目总览")
    assert "当前位置" not in cleaned


def test_parse_info_list():
    source = Source(
        code="whu_info_public", name="信息公开", level="university",
        list_url="https://info.whu.edu.cn/gz/zxgk.htm",
        items_xpath="//div[contains(@class,'list')]//li[a[p][span]]",
        fields={"title": "./a/p", "url": "./a/@href", "published_at": "./a/span"},
    )
    items = parse.parse_list(INFO_LIST_HTML, source, "https://info.whu.edu.cn/gz/zxgk.htm")
    assert len(items) == 2
    assert items[0].title.startswith("关于申请2027年")
    assert items[0].url == "http://oir.whu.edu.cn/info/1198/46111.htm"
    assert items[0].published_at == "2026-11-16"

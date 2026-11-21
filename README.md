# WHU Notice Hub · 武大通知聚合

把武汉大学官网、学院等公开栏目里分散的通知公告，聚合成一个**不漏、降噪、可执行**的入口：自动抓取 → 去重 → 抽取截止日期与适用对象 → 按重要度排序 → 网页/邮件查看。

> 非官方、非商业的校内信息聚合实验项目。只抓取公开页面，不涉及登录内容，不采集个人隐私数据。

## 想试用？

线上实例部署在私有服务器上，访问地址不对外公开。如果你想试用这个通知聚合，给我发一封邮件说明来意即可，我会把访问方式回复给你：

**邮箱：githubseeker@163.com**（标题建议写 `WHU Notice Hub 试用`，顺带说一句你的身份/用途，方便我判断）

> 目前只收录本科生相关通知；后续会按反馈补充信源和推送渠道。

## 功能

- **多信源、配置化**：新增站点只改 `config/sources.example.yaml`，不用写新爬虫
- **增量抓取**：按 URL 差集判断新增，整页已知即停止翻页；列表页倒序页码自动换算
- **正文与附件**：详情页正文抽取、附件链接收集、错误页自动识别并回退到列表标题
- **结构化理解**：规则分类（招生/考试/奖助/教务/公示/生活服务…）、受众识别、截止日期抽取、0–100 重要度
- **本科生定向**：`AUDIENCE=undergrad` 时自动剔除非本科相关通知（研究生/教师/干部/讲座/会议/科研类）
- **变更追踪**：正文哈希变化记为"已更新"，保留版本历史
- **Web 时间线**：首页概览（今日新增 / 7 天内截止 / 来源分布）、重点通知卡片、分类快捷筛选、关键词搜索、分页
- **RSS**：`/rss.xml` 可直接用阅读器订阅
- **JSON API**：`/api/notices`、`/healthz`
- **轻量限流**：按 IP 每分钟请求上限，公开部署时防刷
- **邮件推送**：每日日报 + 高重要度通知即时提醒（配置 SMTP 后启用）

## 信源

| 层级 | 信源 | 列表入口 | 结构 |
|---|---|---|---|
| 校级 | 武汉大学官网 · 通知公告 | `www.whu.edu.cn/tzgg.htm` | 表格，10 条/页，页码倒序 |
| 院系 | 计算机学院 · 通知公告 | `cs.whu.edu.cn/xwdt/tzgg.htm` | 列表项含标题 + 日期，15 条/页 |

新增信源：复制 YAML 模板段 → 用真实页面校准 XPath → `python -m app.cli crawl --dry-run --source <code>` 验证。

## 架构

```
采集 Collector ──▶ 处理 Pipeline ──▶ 理解 Enrich ──▶ 分发 Deliver
 · 配置化适配器      · URL 规范化        · 分类 / 受众      · Web 时间线
 · 限速 / 重试       · 差集水位 / 去重    · 截止日期抽取     · 邮件日报
 · 结构漂移检测      · 正文 / 附件解析    · 重要度打分       · 即时推送
        │                 │                  │                 │
        └────────────┬────┴────────┬─────────┴─────────────────┘
                     ▼             ▼
              SQLite         日志 / 快照
```

设计文档：[`docs/总体设计.md`](docs/总体设计.md)

## 快速开始

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest

cp .env.example .env        # 按需修改（SMTP、受众过滤等）
python -m app.cli init-db   # 建库 + 注册信源
python -m app.cli crawl --pages 2   # 首次回填两页；之后不加 --pages 即增量
python -m app.cli list --limit 20
python -m app.cli serve --port 8000 # 打开 http://127.0.0.1:8000
```

其他命令：

```bash
python -m app.cli stats             # 各信源状态
python -m app.cli digest --dry-run  # 终端预览日报 HTML
python -m app.cli push --dry-run    # 查看待推送的高重要度通知
```

## 配置

`.env` 主要项：

| 变量 | 说明 |
|---|---|
| `AUDIENCE` | 设为 `undergrad` 只保留本科生相关通知；留空不过滤 |
| `DB_PATH` | SQLite 路径 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `MAIL_TO` | 邮件推送；邮箱服务商一般需用「授权码」而非登录密码 |
| `PUSH_MIN_IMPORTANCE` | 即时推送的重要度阈值（默认 65） |
| `DIGEST_HOUR` / `DIGEST_MINUTE` | 日报发送时间（默认 08:30） |
| `SNAPSHOT_KEEP_DAYS` | 原始 HTML 快照保留天数（默认 7） |
| `WEB_USER` / `WEB_PASSWORD` | 可选，开启网页 HTTP Basic 认证 |

## 项目结构

```
app/
├─ cli.py          # init-db / crawl / list / stats / digest / push / serve
├─ sources.py      # YAML → Source（含分页规则）
├─ fetch.py        # 限速、重试、快照、保留策略
├─ parse.py        # 列表/详情解析、错误页识别、标题择优、正文清洗
├─ text.py         # URL 规范化、日期解析、分类与受众词典
├─ score.py        # 分类/受众/截止日期/重要度，本科生相关性过滤
├─ crawl.py        # 抓取编排与增量水位
├─ db.py           # SQLite 访问（幂等入库 + 变更追踪）
├─ digest.py       # 日报与即时推送
├─ mailer.py       # SMTP 发送
├─ web.py          # FastAPI 页面 + JSON API
└─ templates/      # Jinja2 模板
```

## 测试

```bash
python -m pytest -q
```

覆盖解析、URL 规范化、分类打分、本科生过滤、去重、邮件渲染、Web 路由与认证、快照保留策略。

## 路线图

- [x] 公开信源抓取（官网 / 学院）
- [x] 增量水位、去重、变更追踪
- [x] 分类 / 受众 / 截止日期 / 重要度
- [x] 本科生定向过滤
- [x] Web 时间线 + API
- [x] 邮件日报与即时推送
- [ ] 更多信源（学工、体育、图书馆等）
- [ ] 事件聚类（跨源转载合并）
- [ ] 附件文本抽取与全文检索

## 合规说明

- 仅抓取**公开页面**，不绕过登录、验证码或权限控制；
- 单 host 串行、限速 1 请求/秒，夜间低峰抓取，尊重站点负载；
- 站内展示摘要并链接原文，不镜像全文；通知版权归各发布单位所有；
- 公示类名单不做个人信息抽取与索引；
- **所有信息以官网原文为准**，本项目不代表武汉大学任何官方立场。

## License

[MIT](LICENSE)

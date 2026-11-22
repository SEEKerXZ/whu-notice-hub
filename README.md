# WHU Notice Hub · 武大通知聚合

把武汉大学官网、学院等公开栏目里分散的通知公告，聚合成一个**不漏、降噪、可执行**的入口：自动抓取 → 去重 → 抽取截止日期与适用对象 → 按重要度排序 → 网页/邮件查看。

> 非官方、非商业的校内信息聚合实验项目。只抓取公开页面，不涉及登录内容，不采集个人隐私数据。

## 想试用？

线上实例部署在私有服务器上，访问地址不对外公开。如果你想试用这个通知聚合，给我发一封邮件说明来意即可，我会把访问方式回复给你：

**邮箱：githubseeker@163.com**（标题建议写 `WHU Notice Hub 试用`，顺带说一句你的身份/用途，方便我判断）

> 目前只收录本科生相关通知；后续会按反馈补充信源和推送渠道。

## 功能

- **只做标题 + 概览 + 原文链接**：不转载正文与附件，降低版权/隐私风险，正文一律跳转原文
- **多信源、配置化**：新增站点只改 `config/sources.example.yaml`，不用写新爬虫
- **低频抓取**：只取列表页，默认每 host 4 秒 1 次 + 随机抖动，命中验证码即熔断该站点
- **正文与附件**：详情页正文抽取、附件链接收集、错误页自动识别并回退到列表标题
- **结构化理解**：规则分类（招生/考试/奖助/教务/公示/生活服务…）、受众识别、截止日期抽取、0–100 重要度
- **本科生定向**：`AUDIENCE=undergrad` 时自动剔除非本科相关通知（研究生/教师/干部/讲座/会议/科研类）
- **受限通知处理**：详情页返回"暂无权限/404"的通知会自动标记隐藏，不在站内展示，避免用户点到错误页
- **变更追踪**：正文哈希变化记为"已更新"，保留版本历史
- **Web 站点**：首页概览、重点通知、分类页 `/category/<分类>`、信源页 `/source/<code>`、按月归档 `/archive`、详情页（含上一条/下一条、同分类推荐）、更新日志 `/changelog`、关于页、404 页
- **搜索与筛选**：关键词全文搜索、来源/分类/重要度/截止日期组合筛选
- **RSS / Sitemap**：`/rss.xml`、`/sitemap.xml`
- **JSON API**：`/api/notices`、`/healthz`
- **轻量限流**：按 IP 每分钟请求上限，公开部署时防刷
- **邮件推送**：每日日报 + 高重要度通知即时提醒（配置 SMTP 后启用）

## 信源

| 层级 | 信源 | 列表入口 | 结构 |
|---|---|---|---|
| 校级 | 武汉大学官网 · 通知公告 | `www.whu.edu.cn/tzgg.htm` | 表格，10 条/页，页码倒序 |
| 校级 | 信息公开网 · 最新公开 | `info.whu.edu.cn/gz/zxgk.htm` | 列表项含标题 + 日期 |
| 院系 | 计算机学院 · 通知公告 | `cs.whu.edu.cn/xwdt/tzgg.htm` | 列表项含标题 + 日期，15 条/页 |
| 院系 | 计算机学院 · 本科生教育 | `cs.whu.edu.cn/rcpy/bksjy.htm` | 同上模板 |
| 院系 | 计算机学院 · 共青团 | `cs.whu.edu.cn/dqgz/gqtgz.htm` | 同上模板 |
| 院系 | 计算机学院 · 党建 | `cs.whu.edu.cn/dqgz/djgz.htm` | 同上模板 |

> 信息公开网的「学生/教工通知」栏目需要 CAS 统一认证（未登录会 302 到登录页），本项目只接入公开可访问的「最新公开」。

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
| `WECOM_WEBHOOK` | 企业微信群机器人地址；配置后日报/即时推送同时发到群里 |

## 企业微信推送

在**企业微信群**里：`群设置 → 群机器人 → 添加`，复制 Webhook 地址填到 `.env`：

```bash
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
```

然后 `python -m app.cli wecom-test` 发一条测试消息；之后每天 08:30 的日报、
以及高重要度即时提醒都会以 markdown 卡片推到群里。

注意：群机器人**只能发到它所在的群**，不能私聊、不能发给外部联系人；单机器人限制
20 条/分钟。要「给很多人发」，就让同学加入同一个群；如果真要按人私发，需要用
企业微信自建应用（要求对方是你企业的成员）。

## QQ 官方机器人（指令式）

QQ 官方平台**不允许群机器人主动推送**，群消息必须被动回复。因此做成指令式：

1. [QQ 开放平台](https://q.qq.com/) 注册开发者（个人需实名）→ 创建机器人，拿到 `AppID` / `AppSecret`
2. 填入 `.env` 的 `QQ_APPID` / `QQ_APPSECRET`
3. 用**最新版手机 QQ** 把机器人加进你当群主/管理员的群
4. `sudo systemctl enable --now whu-qq-bot`
5. 群里 `@机器人 日报` 或 `@机器人 重要`，它被动回复当天摘要

```bash
python -m app.cli qq-preview            # 本地预览机器人会回复的文本
python -m app.cli qq-preview --important
python -m app.cli qq-run                # 前台启动（调试用）
```

限制：个人主体机器人不能公开使用、只能加入自己管理的群；被动回复需在触发消息的有效窗口内。

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
├─ changelog.py    # 更新日志数据（站内 /changelog）
├─ web.py          # FastAPI 页面 + JSON API
└─ templates/      # Jinja2 模板
```

## 更新日志

- 站内页面：`/changelog`
- 仓库文件：[`CHANGELOG.md`](CHANGELOG.md)

当前版本 v1.0.0（标题 + 概览模式）。

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
- 单 host 串行、每 host 4 秒 1 次并带随机抖动，命中站点验证码立即熔断该站点；
- 站内只展示**标题与概览**并链接原文，不转载正文与附件；通知版权归各发布单位所有；
- 公示类名单不做个人信息抽取与索引；
- **所有信息以官网原文为准**，本项目不代表武汉大学任何官方立场。

## 作者

**SEEKers** · 武汉大学在校本科生 · 独立开发与维护

- 站点：关于页 `/about`
- 反馈：githubseeker@163.com

## License

[MIT](LICENSE)

-- ============================================================================
-- 武大通知聚合 · 数据模型（SQLite 版；Postgres 迁移说明见文件末尾）
-- ============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. 信源
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT    NOT NULL UNIQUE,          -- whu_main / cs_whu / gs_whu
    name             TEXT    NOT NULL,
    level            TEXT    NOT NULL CHECK (level IN ('university','college','department','media')),
    base_url         TEXT,
    list_url         TEXT    NOT NULL,
    engine           TEXT    NOT NULL DEFAULT 'http' CHECK (engine IN ('http','browser','json')),
    config_json      TEXT    NOT NULL DEFAULT '{}',    -- 该源的 selector / 分页配置
    weight           INTEGER NOT NULL DEFAULT 70,      -- 源基线权重 0-100
    enabled          INTEGER NOT NULL DEFAULT 1,
    interval_minutes INTEGER NOT NULL DEFAULT 30,
    last_ok_at       TEXT,
    last_error_at    TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    status           TEXT    NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','degraded','broken','disabled')),
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- 2. 通知主表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code      TEXT    NOT NULL REFERENCES sources(code),
    url              TEXT    NOT NULL,
    url_hash         TEXT    NOT NULL UNIQUE,          -- sha1(规范化 URL)，去重第一道闸
    title            TEXT    NOT NULL,
    title_norm       TEXT    NOT NULL,                 -- 去标点/空格/全半角归一，用于跨源比对
    publisher        TEXT,                             -- 发布单位
    published_at     TEXT,                             -- ISO8601，北京时间
    date_inferred    INTEGER NOT NULL DEFAULT 0,       -- 1 = 列表无日期，用 first_seen 兜底
    category         TEXT DEFAULT '其他',
    summary          TEXT,                             -- LLM/规则生成，≤80 字
    content_md       TEXT,                             -- 正文 Markdown（仅用于检索/摘要）
    content_hash     TEXT,                             -- 正文哈希，用于变更检测
    simhash          INTEGER,                          -- 64bit 正文指纹，用于跨源近似去重
    deadline_date    TEXT,                             -- 抽取出的截止日期
    deadline_time    TEXT,
    deadline_kind    TEXT,                             -- 报名/材料提交/异议/活动
    audience_json    TEXT DEFAULT '[]',                -- ["本科生","研究生","2027届"]
    action_items_json TEXT DEFAULT '[]',               -- ["6/1 前提交材料", ...]
    importance       INTEGER NOT NULL DEFAULT 50,      -- 0-100
    llm_confidence   REAL,
    sensitive        INTEGER NOT NULL DEFAULT 0,       -- 1 = 含名单等个人信息，不索引/不推送细节
    status           TEXT    NOT NULL DEFAULT 'new' CHECK (status IN ('new','updated','archived')),
    cluster_id       INTEGER,                          -- 指向 clusters.id（跨源转载合并）
    first_seen_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notices_published ON notices(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_notices_source    ON notices(source_code, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_notices_deadline  ON notices(deadline_date) WHERE deadline_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notices_importance ON notices(importance DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_notices_cluster   ON notices(cluster_id);
CREATE INDEX IF NOT EXISTS idx_notices_simhash   ON notices(simhash);

-- ---------------------------------------------------------------------------
-- 3. 变更历史（公告被修改：延期、补充、名单更正）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notice_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id     INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    content_hash  TEXT    NOT NULL,
    title         TEXT,
    diff_summary  TEXT,                                -- 人可读的变更摘要
    fetched_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (notice_id, content_hash)
);

-- ---------------------------------------------------------------------------
-- 4. 附件
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id    INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    name         TEXT,
    url          TEXT    NOT NULL,
    url_hash     TEXT    NOT NULL,
    mime         TEXT,
    size_bytes   INTEGER,
    sha256       TEXT,
    local_path   TEXT,                                 -- data/attachments/...
    text_excerpt TEXT,                                 -- 文本抽取片段；sensitive 通知不填
    parsed_at    TEXT,
    UNIQUE (notice_id, url_hash)
);

-- ---------------------------------------------------------------------------
-- 5. 事件聚类（转载 / 同一事件的系列公告）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clusters (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_notice_id INTEGER REFERENCES notices(id),
    title              TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    notice_id  INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    similarity REAL,
    PRIMARY KEY (cluster_id, notice_id)
);

-- ---------------------------------------------------------------------------
-- 6. 抓取审计
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code   TEXT    NOT NULL REFERENCES sources(code),
    mode          TEXT    NOT NULL DEFAULT 'incremental' CHECK (mode IN ('incremental','full','manual')),
    started_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at   TEXT,
    status        TEXT    NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','partial','failed')),
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    items_seen    INTEGER NOT NULL DEFAULT 0,
    items_new     INTEGER NOT NULL DEFAULT 0,
    items_updated INTEGER NOT NULL DEFAULT 0,
    http_errors   INTEGER NOT NULL DEFAULT 0,
    parse_errors  INTEGER NOT NULL DEFAULT 0,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_source ON crawl_runs(source_code, started_at DESC);

-- ---------------------------------------------------------------------------
-- 7. 订阅与推送
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    channel     TEXT    NOT NULL,                      -- email / feishu / wecom / tg / bark
    target      TEXT    NOT NULL,                      -- 邮箱或 webhook 地址
    rules_json  TEXT    NOT NULL DEFAULT '{}',         -- 关键词/来源/类别/受众/min_score
    quiet_hours TEXT    DEFAULT '23:00-07:30',
    daily_limit INTEGER NOT NULL DEFAULT 10,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id       INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    channel         TEXT    NOT NULL,
    kind            TEXT    NOT NULL DEFAULT 'instant' CHECK (kind IN ('instant','digest')),
    status          TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','skipped')),
    error           TEXT,
    sent_at         TEXT,
    -- 幂等：同一通知对同一订阅只会推一次
    UNIQUE (notice_id, subscription_id)
);

CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(status, sent_at);

-- ---------------------------------------------------------------------------
-- 8. 用户行为（MVP 单用户也保留，方便以后多用户）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notice_actions (
    notice_id  INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    action     TEXT    NOT NULL CHECK (action IN ('read','star','ignore','forward')),
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (notice_id, action)
);

-- ---------------------------------------------------------------------------
-- 10. 项目分享（投稿收录）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    description TEXT,
    author      TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------------------------------------------------------------------------
-- 11. AI 问答用量（每人/每群/全站每日次数）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_usage (
    day        TEXT NOT NULL,           -- YYYY-MM-DD
    scope      TEXT NOT NULL,           -- user:<openid> / group:<openid> / total
    count      INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (day, scope)
);

-- ---------------------------------------------------------------------------
-- 9. 全文检索（可选，P1 开启；敏感通知不进入索引）
-- ---------------------------------------------------------------------------
-- CREATE VIRTUAL TABLE notices_fts USING fts5(
--     title, summary, content_md,
--     content='notices', content_rowid='id',
--     tokenize='unicode61'
-- );

-- ============================================================================
-- Postgres 迁移要点：
--   · INTEGER PRIMARY KEY AUTOINCREMENT  → BIGSERIAL PRIMARY KEY
--   · TEXT 时间字段                      → TIMESTAMPTZ（统一存 UTC，展示转 Asia/Shanghai）
--   · *_json TEXT                        → JSONB（audience/action_items 可建 GIN 索引）
--   · simhash INTEGER（SQLite 有符号 64bit）→ BIGINT 或 BIT(64)
--   · 定时清理：crawl_runs / notice_versions 保留 180 天
-- ============================================================================

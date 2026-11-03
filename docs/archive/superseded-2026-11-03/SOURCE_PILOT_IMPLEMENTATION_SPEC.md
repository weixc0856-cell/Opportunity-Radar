# 第一批信息源试点实施规格

版本：0.1（规格稿，等待确认，不是开发授权）
日期：2026-11-02
基线：`main@1c45b9b`；N0–N5 冻结在 Batch 16
范围：GDELT、Federal Register、BLS 三个影子试点
性质：规格与改造范围。未修改生产代码、数据库、配置、调度任务；未接入真实 API。

依据：

- [SOURCE_FIRST_BATCH_DECISION_REVIEW.md](SOURCE_FIRST_BATCH_DECISION_REVIEW.md)
- [SOURCE_INTELLIGENCE_RESEARCH.md](SOURCE_INTELLIGENCE_RESEARCH.md)
- [SOURCE_INTELLIGENCE_ROADMAP.md](SOURCE_INTELLIGENCE_ROADMAP.md)
- [source-catalog.csv](source-catalog.csv)
- 当前代码：[ingest/http.py](../opportunity_radar/ingest/http.py)、[ingest/store.py](../opportunity_radar/ingest/store.py)、[ingest/config.py](../opportunity_radar/ingest/config.py)、[unified.py](../opportunity_radar/unified.py)、[linking.py](../opportunity_radar/linking.py)、[store.py](../opportunity_radar/store.py)、[source_policy.py](../opportunity_radar/source_policy.py)、[datasets.py](../opportunity_radar/datasets.py)、[page_monitor.py](../opportunity_radar/page_monitor.py)

---

## 1. 规格边界

### 1.1 本阶段做什么

三个来源进入 **4 周影子运行 + 2 周评审**：

| 来源 | 写入数据域 | 用途 |
|---|---|---|
| GDELT | `discovery_candidates` | 发现 RSS 外事件/原始链接；不生成 evidence/claim |
| Federal Register | `policy_documents` | 政策/法规/公告元数据与原文链接 |
| BLS | `macro_observations` | 就业/通胀/工资等官方序列 |

### 1.2 本阶段不做什么

- 不写生产 `articles`、`events`、`evidences`、`claims`、`analyses`。
- 不写生产 `event_links`；只写 pilot `link_candidates`。
- 不进入日报、评分、R0 门禁、R1 事件视图、N0–N5、verify。
- 不改 SEC/EIA 独立库/入口/边界。
- 不接 FRED、SEC 扩展、Form D、full-text search、社交、商业数据。
- 不新增调度框架、消息队列、微服务、向量数据库。
- 不新增运行期依赖；只用 Python 标准库。
- 不做来源数量/采集数量作为成功指标。

### 1.3 当前真实结构约束

| 现状 | 影响 |
|---|---|
| `articles` 只有 `source_name`，没有 `source_id` | pilot 不依赖生产文章来源绑定；新增来源不写入 `articles` |
| `events` / `event_articles` / `evidences` / `claims` 是 RSS/R1 契约 | pilot 只读匹配，不写这些表 |
| `ingest` 库有 `raw_snapshots` / `ingest_runs` / `sec_facts` / `eia_*` | schema 是 SEC/EIA 专用；pilot 不复用 `IngestStore`，只复用 HTTP/错误分类模式 |
| `datasets.py` 只探测最新期 | 不能用于 BLS 历史序列/修订；pilot 新建 observation 存储 |
| `source_policy.Source` / `is_approved()` 面向 RSS，要求 `feed_url` + `freshrss_feed_id` | pilot 使用独立 `config/pilot_sources.csv`，不改生产来源登记 |
| `pipeline_store.py` 是 N0–N5 节点留存 | pilot 不复用；避免混淆 Claim 流水线 |
| `page_monitor.py` 只存链接/标题 | 不用于政策文档/宏观序列 |
| `unified.UnifiedStore(read_only=True)` 可只读打开生产库 | pilot 用它做 URL/事件匹配，不写生产库 |
| `unified.canonical_url` / `canonical_title` 已存在 | 直接复用，避免重复实现 |
| `ingest.http` 已有重试/限流/9 类失败分类 | 直接复用，不改动 |
| `ingest.config.assert_isolated_db` 已防止生产库被当摄取库 | 复用于 pilot DB 隔离检查 |

---

## 2. 公共设计

### 2.1 新增 package 与入口

新增 `opportunity_radar/pilot/`：

```
opportunity_radar/pilot/__init__.py
opportunity_radar/pilot/__main__.py      # python -m opportunity_radar.pilot
opportunity_radar/pilot/cli.py           # gdelt | federal-register | bls | report | health
opportunity_radar/pilot/config.py        # PilotSettings, env, DB 隔离
opportunity_radar/pilot/store.py         # PilotStore + schema
opportunity_radar/pilot/rights.py        # pilot 来源权利门禁
opportunity_radar/pilot/gdelt.py         # client / normalize / query
opportunity_radar/pilot/federal_register.py
opportunity_radar/pilot/bls.py
opportunity_radar/pilot/report.py        # summary/metrics
```

命令示例（实现后）：

```
python -m opportunity_radar.pilot health
python -m opportunity_radar.pilot gdelt --dry-run
python -m opportunity_radar.pilot federal-register --since 2026-11-01
python -m opportunity_radar.pilot bls --start-year 2016 --end-year 2026
python -m opportunity_radar.pilot report --source gdelt
```

建议所有命令默认 dry-run；dry-run **不发起网络请求**，只校验配置和 DB；真实运行必须显式 `--live`（BLS 还需要 key）。建议：

- `--dry-run`：不请求网络、不写 DB，打印将执行的查询/数量上限。
- 真实运行：GDELT/Federal Register 无 key；BLS 必须 `OR_PILOT_BLS_API_KEY`。
- 不自动调度；4 周内手动/计划任务外部触发，不改现有 scheduler。

### 2.2 新增配置

| 文件 | 用途 |
|---|---|
| `config/pilot_sources.csv` | pilot 来源、访问方式、权利、留存、enabled、cadence |
| `config/pilot_gdelt_queries.csv` | GDELT 查询组、时间窗、max_records、language/country |
| `config/pilot_federal_register_watchlist.csv` | FR 机构/主题/文档类型 watchlist |
| `config/pilot_bls_series.csv` | BLS 首批 series 清单与单位/频率/季调元数据 |

`pilot_sources.csv` 字段建议：

`source_id,name,source_type,access_method,base_url,terms_url,license_url,commercial_use,local_cache,long_term_storage,analysis_use,subscriber_display,redistribution,attribution_required,retention_limit,enabled,cadence,notes`

首批值（pilot 运行时限制，不等于最终产品授权）：

| source_id | commercial_use | local_cache | long_term_storage | analysis_use | subscriber_display | redistribution | pilot 附加限制 |
|---|---|---|---|---|---|---|---|
| `gdelt` | ALLOWED | ALLOWED | CONDITIONAL | ALLOWED | PROHIBITED | PROHIBITED | 只存发现元数据；不存正文；不对外展示 |
| `federal-register` | ALLOWED | ALLOWED | ALLOWED | ALLOWED | PROHIBITED | PROHIBITED | pilot 只内部使用；法律文本回 govinfo |
| `bls` | ALLOWED | ALLOWED | ALLOWED | ALLOWED | PROHIBITED | PROHIBITED | pilot 只内部使用；署名 BLS |

> `subscriber_display=PROHIBITED` / `redistribution=PROHIBITED` 是**试点运行边界**，即使 BLS/FR 的通用权利允许，也不在 4 周内开放外部展示。后续变更需单独批准。

### 2.3 新增数据库

`data/pilot/source_pilot.sqlite3`，`PRAGMA user_version=1`，只追加式迁移。

公共表：

```
pilot_runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,              -- running/success/partial_failed/failed
  requests INTEGER NOT NULL DEFAULT 0,
  records INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  exit_code INTEGER,
  config_hash TEXT NOT NULL,
  query_hash TEXT NOT NULL
)

pilot_failures(
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  source_id TEXT NOT NULL,
  stage TEXT NOT NULL,               -- fetch/normalize/store/rights
  error_class TEXT NOT NULL,         -- ingest.http 的 9 类
  detail TEXT NOT NULL,
  external_ref TEXT,
  occurred_at TEXT NOT NULL
)

pilot_raw_snapshots(
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  request_key TEXT NOT NULL,
  status INTEGER,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  content_type TEXT,
  etag TEXT,
  last_modified TEXT,
  path TEXT NOT NULL,                -- 相对 data/pilot/snapshots/
  retrieved_at TEXT NOT NULL,
  UNIQUE(source_id, request_key, sha256)
)

pilot_watermarks(
  source_id TEXT NOT NULL,
  query_id TEXT NOT NULL,
  last_success_at TEXT,
  last_seendate TEXT,
  last_run_id INTEGER,
  PRIMARY KEY(source_id, query_id)
)

link_candidates(
  link_id TEXT PRIMARY KEY,
  left_kind TEXT NOT NULL,           -- discovery_candidate/policy_document/macro_observation
  left_key TEXT NOT NULL,
  right_kind TEXT NOT NULL,          -- event/entity/article
  right_key TEXT NOT NULL,
  relation TEXT NOT NULL,            -- mention/topic/date/url_match
  basis TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(left_kind,left_key,right_kind,right_key,relation,basis)
)
```

**隔离规则**：

- `PilotStore` 使用 `assert_isolated_db` 拒绝生产库路径。
- 生产库只以 `UnifiedStore(read_only=True)` 打开；只读查询，不写。
- pilot DB 与 ingest DB、RSS DB、node_runs 物理分离。
- 不使用 `INSERT OR REPLACE` 覆盖历史；状态/版本追加。

### 2.4 复用与不重复建设

复用（不改动）：

- `opportunity_radar.ingest.http`：`UrllibTransport`、`RateLimiter`、`get_json`、`IngestError`、9 类错误。
- `opportunity_radar.ingest.config.assert_isolated_db`：pilot DB 隔离检查。
- `opportunity_radar.unified.canonical_url` / `canonical_title`：URL/标题规范化。
- `opportunity_radar.unified.UnifiedStore(path, read_only=True)`：生产库只读匹配。

不复用：

- `IngestStore` 的 schema（SEC/EIA 专用）。
- `datasets.py` 的“只探最新期”。
- `pipeline_store.py`（N0–N5 节点留存）。
- `source_policy.py` 的 RSS 审批路径（pilot 用独立 registry）。
- `page_monitor.py`（只存链接/标题，不适合政策/序列）。

### 2.5 报告

`reports/pilot/<source_id>/<run_id>/summary.json` + `summary.md`（运行摘要，不是产品文档）：

- source_id、run_id、started/finished、status、requests、records、errors。
- 每源 metrics（见各节）。
- 配置/查询哈希、snapshot 目录、失败分类计数。
- 不写日报、不评分、不发送邮件。

---

## 3. GDELT 规格

### 3.1 目标

只做发现：`discovery_candidates` + 元数据；不存正文、不写 Article/evidence/claim、不进入日报。

### 3.2 API 与查询

- Base：`https://api.gdeltproject.org/api/v2/doc/doc`
- 方式：`GET`，JSON；无 key。
- 关键参数：`query`、`mode=artlist`、`format=json`、`maxrecords=250`、`startdatetime`/`enddatetime`、`sort=datedesc`。
- 官方未公布固定配额；实践约 1 请求/5 秒、单次最多 250 条、无 cursor/分页。`[官方/第三方]`
- 时间窗：首次 `timespan=7d`；后续按 watermark 从 `last_success_at - 1h` 到当前；不回溯超过 3 个月（DOC 滚动窗口）。

查询配置 `config/pilot_gdelt_queries.csv`：

`query_id,query,timespan,max_records,language,country,enabled,notes`

首批建议 5 组（可按用户调整）：

| query_id | query | 目的 |
|---|---|---|
| `ai-infra` | `("artificial intelligence" OR "data center" OR semiconductor OR chip)` | AI/算力/半导体 |
| `energy-industry` | `("critical minerals" OR battery OR "electric vehicle" OR "power grid")` | 能源/电池/电网 |
| `manufacturing-supply` | `(factory OR manufacturing OR "supply chain" OR robotics)` | 制造/供应链/机器人 |
| `policy-trade` | `(tariff OR "export control" OR "industrial policy" OR sanctions)` | 贸易/产业政策 |
| `capital-markets` | `(merger OR acquisition OR "private equity" OR "venture capital")` | 资本/并购/融资 |

- 不限制语言（GDELT 支持 65 语言）；`language/country` 留空表示全部。
- 命中 250 条上限时：缩小时间窗或 query 范围；不做假分页。

### 3.3 `discovery_candidates` 表

```
discovery_candidates(
  candidate_id TEXT PRIMARY KEY,          -- sha256('gdelt|'+canonical_url)
  source_id TEXT NOT NULL DEFAULT 'gdelt',
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  domain TEXT NOT NULL,
  title TEXT,                             -- 仅发现/审核用；不对外展示
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  seen_count INTEGER NOT NULL DEFAULT 1,
  matched_article_key TEXT,               -- 生产 articles 匹配
  matched_event_id TEXT,                  -- 通过 event_articles 只读匹配
  approved_source_id TEXT,                -- 已批准来源域名匹配
  resolution_status TEXT NOT NULL,        -- new/duplicate_article/approved_source/unapproved_domain/unknown_domain/invalid_url
  lineage_role TEXT NOT NULL DEFAULT 'aggregator',
  evidence_role TEXT NOT NULL DEFAULT 'discovery',
  UNIQUE(source_id, canonical_url)
)

discovery_candidate_observations(
  observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id TEXT NOT NULL,
  query_id TEXT NOT NULL,
  seendate TEXT NOT NULL,
  title TEXT,
  language TEXT,
  source_country TEXT,
  raw_snapshot_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  UNIQUE(candidate_id, query_id, seendate)
)
```

### 3.4 字段映射

GDELT `artlist` 返回字段（以实际响应为准）：

| GDELT 字段 | pilot 字段 |
|---|---|
| `url` | `url`；用 `canonical_url()` 得 `canonical_url` |
| `domain` | `domain`（小写；去 `www.`） |
| `title` | `title`（仅内部审核） |
| `seendate` | `seendate`（保留 `YYYYMMDDTHHMMSSZ`） |
| `language` | `language` |
| `sourcecountry` | `source_country` |

缺失字段：保留 NULL；不推断标题/语言/国家。无效/非 http(s) URL → `resolution_status=invalid_url`，不请求。

### 3.5 去重与来源溯源

1. **URL 规范化**：复用 `unified.canonical_url`；去掉 utm/ref/fbclid/gclid、fragment、末尾斜杠；host 小写、去 `www.`。
2. **候选去重**：`candidate_id = sha256('gdelt|' + canonical_url)`；同一 URL 多次出现只保留一个 candidate，`seen_count` 增加，每次出现写 `discovery_candidate_observations`。
3. **与生产文章匹配**：只读查询 `articles`：
   - 先 `Store.key(url)` 精确匹配；
   - 再按 `canonical_url` 扫描（当前 126 篇，成本可接受）；
   - 命中 → `matched_article_key`，`resolution_status=duplicate_article`。
4. **与生产事件匹配**：通过 `event_articles` 由 `matched_article_key` 得 `matched_event_id`；仅用于统计/候选，不写事件。
5. **域名审批**：读取 pilot 来源 registry（及生产 `sources.local.csv` 的 canonical_domain，只读）：
   - 已批准来源域名 → `approved_source_id`，`resolution_status=approved_source`；
   - 已登记但未批准 → `unapproved_domain`；
   - 未登记 → `unknown_domain`。
   - **不自动批准、不自动抓正文。**
6. **同事件多 URL**：第一版不做事件聚类；只按 URL 去重。标题相似度/域名传播链留到后续。
7. **聚合器角色**：所有 GDELT candidate 固定 `lineage_role=aggregator`、`evidence_role=discovery`；不得进入 `evidences`/`claims`，不得算独立来源。
8. **上游正文**：不存正文；只存 GDELT 返回的 title/URL/元数据。原始文章正文需原来源授权后才能另取。

### 3.6 运行指标

- requests、candidates、unique URLs、new URLs vs RSS、duplicate_article、approved_source/unapproved/unknown、invalid_url。
- 429/失败率、平均响应时间、时间窗回退次数、250 条截断次数。
- 抽样 50 条/周人工相关性（按 query 分层）。
- 不把 GDELT 条目数当“新增情报数”。

---

## 4. Federal Register 规格

### 4.1 目标

建立独立 `policy_documents` 数据域：法规、拟议规则、公告、征求意见的元数据 + 官方链接；不转 Article、不进入评分/日报。

### 4.2 API 与范围

- Base：`https://www.federalregister.gov/api/v1`
- 文档列表：`GET /documents.json`
- 文档详情（可选）：`GET /documents/{document_number}.json`
- 无 key；结果上限约 2,000；API 是原型，不是官方法律版；法律文本回 govinfo。`[官方]`
- 首批文档类型：`RULE`、`PRORULE`、`NOTICE`；`PRESDOC` 暂不启用。
- 首批机构 watchlist（slug 需在实现时用 `/agencies.json` 核验）：

| watch_id | agency_slug | term | document_types |
|---|---|---|---|
| `commerce-ai` | `commerce-department` | artificial intelligence | RULE,PRORULE |
| `commerce-chip` | `commerce-department` | semiconductor | RULE,PRORULE,NOTICE |
| `energy-minerals` | `energy-department` | critical minerals | RULE,PRORULE,NOTICE |
| `treasury-tariff` | `treasury-department` | tariff | RULE,NOTICE |
| `ustr-trade` | `united-states-trade-representative` | tariff | NOTICE |
| `ftc-ai` | `federal-trade-commission` | artificial intelligence | NOTICE |
| `fcc-datacenter` | `federal-communications-commission` | data center | RULE,PRORULE |
| `epa-ev` | `environmental-protection-agency` | electric vehicle | RULE,PRORULE |

- 配置 `config/pilot_federal_register_watchlist.csv`：
  `watch_id,agency_slug,term,document_types,enabled,max_documents,notes`
- 查询参数（以官方文档为准）：`conditions[agencies][]=...`、`conditions[type][]=...`、`conditions[term]=...`、`conditions[publication_date][gte]=...`、`per_page=100`、`page=N`、`order=newest`。
- 每个 watch row 一个查询；按 `document_number` 去重；每 run 上限 200 文档；分页最多 5 页；超限记录 `truncated=true`。

### 4.3 `policy_documents` 表

```
policy_documents(
  document_id TEXT PRIMARY KEY,          -- 'fr:' + document_number
  source_id TEXT NOT NULL DEFAULT 'federal-register',
  document_number TEXT NOT NULL,
  document_type TEXT NOT NULL,           -- RULE/PRORULE/NOTICE/PRESDOC
  title TEXT NOT NULL,
  abstract TEXT,
  agencies_json TEXT NOT NULL DEFAULT '[]',
  agency_slugs TEXT NOT NULL DEFAULT '', -- comma-separated
  published_at TEXT NOT NULL,            -- publication_date
  effective_on TEXT,
  comments_close_on TEXT,
  docket_ids_json TEXT NOT NULL DEFAULT '[]',
  citation TEXT,
  html_url TEXT,
  pdf_url TEXT,
  raw_text_url TEXT,
  related_document_numbers_json TEXT NOT NULL DEFAULT '[]', -- 仅显式 correction/related 字段
  content_hash TEXT NOT NULL,
  latest_snapshot_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(source_id, document_number)
)

policy_document_versions(
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  change_kind TEXT NOT NULL,             -- initial/content_changed
  fields_json TEXT NOT NULL DEFAULT '{}',-- selected normalized fields
  UNIQUE(document_id, content_hash)
)
```

### 4.4 字段映射与版本

- `document_number` → `document_id='fr:'+document_number`；稳定唯一键。
- `type` → `document_type`；只接受 RULE/PRORULE/NOTICE/PRESDOC；其他值记录 `schema` 失败，不猜测。
- `agencies[]` → `agencies_json`；`agency_slugs` 从 `slug` 拼接；保留原始 JSON。
- `publication_date` → `published_at`；`effective_on`、`comments_close_on`、`docket_ids`、`citation`、`html_url`、`pdf_url`、`raw_text_url` 按 API 原字段保留。
- `content_hash = sha256(canonical selected fields + raw JSON)`。
- **版本**：同一 `document_number` 再次出现且 `content_hash` 变化 → 新 `policy_document_versions` 行，`change_kind=content_changed`；更新 latest 表。
- **更正/修订**：Federal Register 的 correction 通常是另一份文档；只有在 API 明确给出 correction/related 字段时写入 `related_document_numbers_json`；**不推断修订链**，不覆盖历史。
- 分页/重复：同一文档跨 watch row 只存一次；`watch_id` 不进入主表，可在版本 `fields_json`/运行指标记录。

### 4.5 与现有层的关系

- 不写 `articles`；不进入 `analyses`/日报。
- 不写 `events`/`evidences`/`claims`。
- 后续如要关联事件：在 `link_candidates` 里按 `policy_document ↔ event`、`basis=topic_date_agency` 生成 candidate；第一版可不做自动关联，只保留字段。
- 机构/术语可做后续实体映射；第一版不做公司实体抽取。

### 4.6 运行指标

- documents、new documents、new versions、by type/agency、truncated、429/errors。
- 抽样 20 条/周机构/主题相关性。
- 与 RSS/新闻的 lead time（如可匹配）：FR publication_date vs 首次 RSS/新闻提及；记录为正/负/无法匹配，不预设方向。

---

## 5. BLS 规格

### 5.1 目标

建立独立 `macro_observations` 数据域：就业、通胀、工资等官方序列；只内部使用；不进入评分/日报。

### 5.2 API

- Base：`https://api.bls.gov/publicAPI/v2/timeseries/data/`
- 方式：`POST` JSON；`seriesid` 数组、`startyear`、`endyear`、`registrationkey`。
- 注册 key；约 500 查询/日、50 series/请求、20 年/请求。`[官方]`
- 首批 9 个 series，一次请求；每周运行；首次回填 10 年。
- 错误：HTTP/`status != REQUEST_SUCCEEDED`/schema/empty → `ingest.http` 错误分类；不把空数据当 0。

### 5.3 首批 Series 清单

`config/pilot_bls_series.csv`：

`series_id,label,topic,unit,frequency,seasonal_adjustment,enabled,notes`

| series_id | 标签 | topic | unit | frequency | SA |
|---|---|---|---|---|---|
| `CES0000000001` | Total nonfarm payroll employment | employment | thousands of persons | monthly | seasonally adjusted |
| `LNS14000000` | Unemployment rate | employment | percent | monthly | seasonally adjusted |
| `CES0500000003` | Average hourly earnings, total private | wages | USD/hour | monthly | seasonally adjusted |
| `CUSR0000SA0` | CPI-U all items | inflation | index 1982-84=100 | monthly | seasonally adjusted |
| `CUUR0000SA0` | CPI-U all items | inflation | index 1982-84=100 | monthly | not seasonally adjusted |
| `JTS000000000000000JOL` | Job openings, total nonfarm | labor demand | thousands | monthly | seasonally adjusted |
| `JTS000000000000000HIL` | Hires, total nonfarm | labor demand | thousands | monthly | seasonally adjusted |
| `JTS000000000000000QUL` | Quits, total nonfarm | labor demand | thousands | monthly | seasonally adjusted |
| `PRS85006092` | Nonfarm business labor productivity, % change | productivity | percent change, annualized | quarterly | seasonally adjusted |

> 实现前用 BLS Data Viewer/Series ID lookup 逐项核验；任何 ID 不确认则 `enabled=false`，不猜测。

### 5.4 `macro_series` / `macro_observations` 表

```
macro_series(
  series_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL DEFAULT 'bls',
  label TEXT NOT NULL,
  topic TEXT NOT NULL,
  unit TEXT NOT NULL,
  frequency TEXT NOT NULL,
  seasonal_adjustment TEXT NOT NULL,
  source_url TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
)

macro_observations(
  observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_id TEXT NOT NULL,
  period_raw TEXT NOT NULL,              -- M01..M12/M13/Q01..Q04
  period TEXT,                           -- YYYY-MM/YYYY/YYYY-Qn; unknown -> NULL
  period_name TEXT,
  value_raw TEXT,                        -- preserve '-'
  value_num REAL,
  unit TEXT NOT NULL,
  preliminary INTEGER,
  latest INTEGER,
  footnotes_json TEXT NOT NULL DEFAULT '[]',
  quality_flags TEXT NOT NULL DEFAULT '',
  snapshot_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(series_id, period_raw)
)

macro_observation_versions(
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_id TEXT NOT NULL,
  period_raw TEXT NOT NULL,
  value_raw TEXT,
  value_num REAL,
  preliminary INTEGER,
  latest INTEGER,
  footnotes_json TEXT NOT NULL DEFAULT '[]',
  observed_at TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  change_kind TEXT NOT NULL,             -- initial/revision/rebase
  UNIQUE(series_id, period_raw, snapshot_hash)
)
```

### 5.5 周期与修订

- BLS `period` 保留为 `period_raw`；`periodName` 保留为 `period_name`。
- 规范化：
  - `M01`–`M12` → `YYYY-MM`；
  - `M13` → `YYYY`（年度平均；仅在 BLS series 确实使用 M13 时）；
  - `Q01`–`Q04` → `YYYY-Qn`；
  - 其他 → `period=NULL`，`quality_flags=unknown_period`，不猜测。
- `value` 为 `-`/空/非数值 → `value_num=NULL`，`value_raw` 保留，`quality_flags=missing_value`。
- `preliminary`/`latest`：仅使用 API 返回字段；缺失保留 NULL，不推断。
- 修订：同一 `(series_id, period_raw)` 的 `value_num`/flags 变化 → 新 version，`change_kind=revision`；更新 latest。
- CPI 季调每年 2 月修订；payrolls/JOLTS 多次修订；必须保留历史 version，不覆盖。
- 不把不同 series 拼成一条序列；不把 BLS 与 FRED/BEA 当独立双源。

### 5.6 与现有层的关系

- 不写 `articles`；不进入 `analyses`/日报。
- 不写 `events`/`evidences`/`claims`。
- 后续如要关联事件：`link_candidates` 按 `macro_observation ↔ event`、`basis=release_date_topic` 生成 candidate；第一版可不自动关联。
- 当前 `datasets.py` 只探最新期，不满足历史/修订；pilot 不复用它。

### 5.7 运行指标

- series 数、observations、new observations、revisions、missing values、unknown period、429/errors。
- 抽样数值与 BLS Data Viewer 一致率；period/unit/SA 错误数。
- 发布延迟（BLS 发布日 vs 首次入库日）；修订次数。

---

## 6. 与现有数据库、event/entity/evidence 层的关系

| 层 | 现有表 | 试点关系 | 是否写入 |
|---|---|---|---|
| RSS 文章 | `articles` | GDELT 只读匹配 URL/标题；不新增 Article | 否 |
| 事件 | `events` / `event_articles` | GDELT 通过 matched article 只读找 event；FR/BLS 不自动关联 | 否 |
| 证据 | `evidences` | 试点不生成 evidence | 否 |
| 主张 | `claims` / `claim_evidence` | 试点不生成 claim | 否 |
| 实体 | `entities` / `entity_mentions` | 第一版不做实体写入/抽取；只读参考 | 否 |
| 候选关联 | `event_links` | 不写生产；pilot `link_candidates` 只写 candidate | 否（生产） |
| SEC/EIA | ingest DB 的 `sec_facts` / `eia_*` | 不读写；保持隔离 | 否 |
| N0–N5 | `node_runs` / JSONL | 不读写 | 否 |
| 日报/门禁 | `digest.py` / `publication.py` | 不调用、不修改 | 否 |

**关联规则**：

1. GDELT candidate 可写 `link_candidates` 到已有 `event`（`basis=url_match`/`title_match`），仅 candidate。
2. Federal Register/BLS 第一版不自动生成 event link；只保留字段，后续按 topic/date 规则评估。
3. 任何 `link_candidates` 不改变生产 `event_links`、不合并事件、不影响日报。
4. 聚合器不计独立来源；试点不计算 `multi_source_coverage`。
5. 生产库连接必须 `read_only=True`；测试断言生产库未被修改。

---

## 7. 实际改造范围

### 7.1 新增文件（预计）

```
opportunity_radar/pilot/__init__.py
opportunity_radar/pilot/__main__.py
opportunity_radar/pilot/cli.py
opportunity_radar/pilot/config.py
opportunity_radar/pilot/store.py
opportunity_radar/pilot/rights.py
opportunity_radar/pilot/gdelt.py
opportunity_radar/pilot/federal_register.py
opportunity_radar/pilot/bls.py
opportunity_radar/pilot/report.py

config/pilot_sources.csv
config/pilot_gdelt_queries.csv
config/pilot_federal_register_watchlist.csv
config/pilot_bls_series.csv

tests/test_pilot_store.py
tests/test_pilot_gdelt.py
tests/test_pilot_federal_register.py
tests/test_pilot_bls.py
tests/fixtures/pilot/gdelt_artlist.json
tests/fixtures/pilot/fr_documents.json
tests/fixtures/pilot/bls_timeseries.json
```

### 7.2 不修改文件

- 不修改 `opportunity_radar/cli.py`、`digest.py`、`publication.py`、`scoring.py`、`verify.py`、`unified.py`、`store.py`。
- 不修改 `opportunity_radar/ingest/*`（只导入 `http`/`assert_isolated_db`）。
- 不修改 `pipeline_store.py`、N0–N5 任何节点/提示词。
- 不修改 `config/sources.csv`、`sources.local.csv`、`source_lineage.csv`。
- 不修改 scheduler/`run-digest.ps1`。
- 不修改生产 DB/迁移；pilot DB 独立。
- 不修改 SEC/EIA 库/入口/边界。
- 不新增 `pyproject.toml` 依赖。

### 7.3 运行期产出

- `data/pilot/source_pilot.sqlite3`
- `data/pilot/snapshots/<source_id>/<sha256>.json`
- `reports/pilot/<source_id>/<run_id>/summary.json`
- `reports/pilot/<source_id>/<run_id>/summary.md`

数据/报告目录按现有 `.gitignore` 的 `data/*`、`reports/*` 处理，不提交。

### 7.4 测试范围

- `PilotStore`：schema、run/failure、snapshot 幂等、隔离检查。
- GDELT：fixture 解析、URL canonicalization、candidate 去重、production fixture 匹配、invalid URL、250 条截断标记。
- Federal Register：fixture 解析、document_number 去重、content hash/version、agency/type、truncation。
- BLS：fixture 解析、period 映射、missing value、revision version、series config 校验。
- 所有测试离线；不调用真实 API；不改生产 DB。
- 不新增“为测试而测试”的无效用例。

---

## 8. 实施顺序（规格确认后）

| 步骤 | 内容 | 验收 |
|---|---|---|
| 1 | `pilot/config.py` + `pilot/store.py` + config files | `health` 可读配置/DB；隔离检查；测试通过 |
| 2 | GDELT client/normalize/store | fixture + dry-run + live 单 query；candidate 去重/溯源 |
| 3 | Federal Register client/normalize/version | fixture + dry-run + live watchlist；document 去重/版本 |
| 4 | BLS client/normalize/version | fixture + dry-run + live 9 series；period/unit/revision |
| 5 | report/metrics | summary.json/md；指标完整 |
| 6 | 4 周影子运行 | 每周报告；不改生产 |
| 7 | 2 周评审 | go/no-go；决定是否进入下一阶段 |

每个来源独立验收；不能用一个来源的良好表现掩盖另一个来源的问题。

---

## 9. 验收与停止条件

### 9.1 规格验收（本次）

- 本文档与现有表结构/代码一致；不假设已有 discovery/policy/macro 表。
- 明确新增/不修改范围。
- 明确 GDELT 只做发现、FR/BLS 只做 observation/policy。
- 明确生产库只读、pilot DB 独立。
- 明确不需要的：FRED、SEC 扩展、Form D、full-text、社交、商业数据。

### 9.2 试点停止条件

- GDELT 新增候选大多噪声/重复/不可解析 → 停止扩展 query，不进入下一阶段。
- Federal Register 相关文档比例低/无法过滤 → 缩窄 watchlist 或停止。
- BLS series 无法稳定/修订处理不清 → 停止扩展 series。
- 任何来源触发权利问题 → 停用该来源，保留历史标记。
- 生产库出现任何写入/日报变化 → 立即停止并回滚。

---

## 10. 需要确认的事项

1. GDELT 首批 5 组 query 是否接受；是否增加/删除主题。
2. Federal Register 首批 8 个 watchlist 是否接受；agency slug 需实现时核验。
3. BLS 首批 9 个 series 是否接受；是否只保留就业/通胀/工资 6 个。
4. GDELT 是否允许内部保存 title（仅审核/去重，不对外展示）。
5. 试点保留期限：建议 raw snapshot 90 天、候选/观测/版本保留至评审后 6 个月；是否接受。
6. 是否批准生产库只读匹配（`UnifiedStore(read_only=True)`）。
7. 是否接受 `data/pilot/source_pilot.sqlite3` 独立库，不写生产/ingest/node_runs。
8. 是否接受新增 `opportunity_radar/pilot/` package（不改现有模块）。
9. BLS API key 是否可用；若无 key，BLS 只能 dry-run/fixture，不能 live。
10. 试点运行节奏：GDELT 每日、FR 每日、BLS 每周；是否接受。
11. 本轮只批准规格，还是同时批准进入实现（建议先只批准规格）。

---

## 11. 结论

三个试点的最小可实现边界是：

- **GDELT**：独立 discovery 数据域；URL/元数据去重；只读匹配生产文章/事件；不生成证据。
- **Federal Register**：独立 policy 数据域；document_number 唯一；版本按 content hash；保留官方链接。
- **BLS**：独立 macro 数据域；series/period/unit/revision 保留；不覆盖历史。

所有写入进入 `data/pilot/source_pilot.sqlite3`；生产库只读；日报/评分/门禁/Claim/核验不变。规格确认后再分别实施，不一次性启动全部代码。

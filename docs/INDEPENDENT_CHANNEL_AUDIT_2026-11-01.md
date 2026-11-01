# 现有系统数据链路只读审查（实施前条件 5）

日期：2026-11-01
状态：**只读审查完成；条件 5 判定见 §8（可行性 PASS / 故障隔离 NOT_VERIFIED / 合并判定 NOT_VERIFIED）**
方法：仅阅读代码与配置，未运行 `cli.py`、`digest.py`、日报或定时任务，未连接数据库、未发起任何外部请求
边界：未修改任何文件；未创建连接器；未启动 R0；未提交 Git

---

## 1. 审查范围

| 文件 | 行数 | 作用 |
|---|---|---|
| `opportunity_radar/cli.py` | 441 | 编排入口：抓取 → 筛选 → 分析 → 评分 → 报告 → 邮件 |
| `opportunity_radar/store.py` | 243 | 全部 SQL；schema、去重、历史、运行记录 |
| `opportunity_radar/digest.py` | 383 | 文本日报渲染 |
| `opportunity_radar/scoring.py` | 267 | 确定性评分与证据门槛 |
| `opportunity_radar/freshrss_client.py` | 116 | RSS 抓取 |
| `opportunity_radar/analyzer.py` | 62 | LLM 单次调用 |
| `opportunity_radar/config.py` | 86 | 环境变量与 Settings |
| `opportunity_radar/page_monitor.py` | 395 | **已有的独立通道先例** |
| `opportunity_radar/admin_server.py` | 442 | 另一个 DB 读者/运行触发者 |
| `deploy/windows/run-digest.ps1` | — | 计划任务入口 |

---

## 2. 数据链路图

```
[Windows 计划任务]
deploy/windows/run-digest.ps1:43
   └─> python -m opportunity_radar.cli
       │
       ├─ Settings.from_env()                    config.py:36   → OR_DB_PATH / OR_REPORT_DIR / OR_MAX_ARTICLES
       ├─ load_scoring()                         config.py:19   → config/scoring.toml
       ├─ load_sources() → is_approved()         source_policy.py → config/sources.local.csv
       │     └─ approved_feed_ids                 cli.py:307-308
       ├─ ensure_model()                          model_service.py   （不可用直接 return 3，cli.py:319）
       │
       ├─ FreshRSSClient.fetch_articles(limit, feed_ids)   freshrss_client.py:95-116
       │     └─ [a for a in raw if a.feed_id in approved_feed_ids]      cli.py:332  ← 第二重过滤
       ├─ filter_articles(window) → articles[:max_articles]             sampling.py
       ├─ apply_article_bodies(articles, source_by_feed)                fulltext.py（逐来源开关）
       │
       ├─ for a in articles:                                            cli.py:344-375
       │     ├─ store.analyzed(key)                                     store.py:70   ┐
       │     ├─ store.analysis_input_hash(key)                          store.py:95   │ 读
       │     ├─ store.save_article(a,key)                               store.py      │ articles /
       │     ├─ store.event_seen(event_key,key,hash)                    store.py:52   │ analyses
       │     ├─ store.event_sources(event_key,key)                      store.py:58   ┘
       │     ├─ model.analyze(title,summary,source_name,url,published)  cli.py:364 → analyzer.py:31
       │     ├─ evaluate() → score_article()                            cli.py:365 → scoring.py:219
       │     │      ← source = registry 行；multi_source / event_seen_before 来自上面的 DB 查询
       │     └─ store.save_analysis()                                   → analyses / analysis_history / analysis_sections
       │
       ├─ apply_source_caps(items,sources)                              cli.py:61-88（来源配额）
       ├─ render_digest(items,stats)                                    digest.py:280  ← 纯内存，不读 DB
       ├─ render_html(items,stats)                                      render_html.py
       ├─ _write() → reports/ + archive                                 cli.py:151-186
       ├─ send_decision() → send_email_detailed()                       cli.py:188、400
       └─ store.finish_run()                                            store.py

[独立入口 A] python -m opportunity_radar.page_monitor   page_monitor.py:358
   └─ 自建 page_watch_state / page_watch_items（page_monitor.py:256-262）
   └─ 使用同一 OR_DB_PATH 文件；cli.py **不 import 它**（grep 无引用）

[独立入口 B] python -m opportunity_radar.cli --render-only   cli.py:216-263
   └─ store.list_analyses(500)  → analyses JOIN articles，**无来源过滤**（store.py:238-243）

[独立入口 C] admin_server.py
   └─ latest_run / deliveries / 触发运行（admin_server.py:255, 373, 385）
```

**结论性的结构事实**：日报由**本次运行内存中的 `items`** 渲染，不从数据库查询。数据库只参与三件事：去重、历史、运行记录。

---

## 3. 八个问题

### 3.1 现有 RSS 数据入口与完整调用链

入口唯一：`cli.main()`（`cli.py:265`），由 `deploy/windows/run-digest.ps1:43` 以
`python -m opportunity_radar.cli` 调用。

链路：`load_sources` → `is_approved` → `approved_feed_ids`（`cli.py:307-308`）→
`FreshRSSClient.fetch_articles(..., feed_ids=ordered_feed_ids(...))`（`cli.py:332`）→
**同一行内再过滤一次** `if a.feed_id in approved_feed_ids` → `filter_articles` → `articles[:max_articles]` →
逐篇分析。

抓取是**失败关闭**的：只有登记表中明确 approved 且映射了 FreshRSS feed ID 的来源才会被处理。

### 3.2 LLM 分析的数据读取范围

`model.analyze(a.title, a.summary, a.source_name, a.url, published=a.published)`（`cli.py:364`）。

- 输入只来自**当篇 article 对象**的五个字段；
- `analyzer.py` 只 import `json / urllib.request / hashlib / pathlib` 与 `schema.parse_model_json`（`analyzer.py:1-3`），**不接触数据库**；
- 不存在"把历史分析喂回模型"的路径。

**代码保证：LLM 看不到数据库里的任何其他记录。**

### 3.3 评分模块的数据来源与依赖字段

`score_article(a, weights, article, classification, thresholds, now, source, lane, lanes_config,
multi_source, event_seen_before, min_full_text_chars)`（`scoring.py:219-221`）。

| 依赖 | 来源 |
|---|---|
| 模型输出 `a`（facts / inferences / gaps / actions / evidence_quotes） | 当次 LLM 返回 |
| `article`（标题、摘要、正文抓取状态） | FreshRSS + `fulltext.py` |
| `source`（来源可靠性、内容权限） | `config/sources.local.csv` 的 registry 行 |
| `multi_source` / `event_seen_before` | **数据库查询结果**（`store.event_sources` / `event_seen`，`cli.py:356-363`） |
| 权重与门槛 | `config/scoring.toml` |

证据门槛（E0/E1/E2）由 `evidence.py` 判定，不受来源数量影响；`multi_source` 只影响 `corroboration` 分项。

### 3.4 日报的数据读取范围、筛选条件与生成入口

| 路径 | 数据来源 | 筛选 | 入口 |
|---|---|---|---|
| 正常日报 | 本次运行的 `items`（内存） | `status ∈ {priority, watch}` 且 `distribution ≠ deferred`（`digest.py` `_shown`） | `render_digest(items,stats)` `digest.py:280` |
| `--render-only` | **数据库** | `list_analyses(500)`，按 `analyzed_at` 倒序，**无来源、无状态过滤** | `cli.py:216-263` |
| `--sample` | 内置假数据 | — | `cli.py:284-289` |

`digest.py` 的 import 只有 `collections / datetime` 与同包的分析、标签模块（`digest.py:1-6`），**没有任何数据库访问**。

### 3.5 是否存在全库扫描、共享状态或隐式耦合

**存在，且不止一处：**

| 位置 | 性质 | 影响 |
|---|---|---|
| `store.list_analyses`（`store.py:238`） | `analyses JOIN articles` 全表按时间倒序 `LIMIT 500` | `--render-only` 会把表里所有内容当日报素材 |
| `store.event_seen`（`store.py:52`） | 按 `event_key`（规范化标题哈希）跨全表 JOIN `analyses` | 新写入的文章可能让 RSS 文章被误判为重复事件而跳过 |
| `store.event_sources`（`store.py:58`） | 同上，返回同事件的其他来源名集合 | 可能虚增"多来源佐证" |
| `store.consecutive_failures`（`store.py:209`） | 读 `runs` 表最近 30 条状态 | 熔断与告警（`cli.py:204`）按 `runs` 表判断；新来源若写 `runs` 会污染告警 |
| 单一 SQLite 文件 | `cli` / `admin_server` / `page_monitor` 共用 `OR_DB_PATH`（`config.py:63`、`page_monitor.py:268-269`） | **无 WAL，未显式设置 busy_timeout**（默认取 Python `sqlite3.connect` 的 5 s），并发写有锁竞争风险 |

### 3.6 新增 SEC/EIA 表或独立存储后，是否会自动进入现有分析或日报

**不会自动进入，前提是新数据不写进 `articles` / `analyses` 系表。**

| 路径 | 是否会自动纳入 | 依据 |
|---|---|---|
| LLM 分析 | 否 | 分析循环只遍历本次 FreshRSS 抓到的 `articles`（`cli.py:344`） |
| 评分 | 否 | 评分只对本次分析产出物执行（`cli.py:365`） |
| 正常日报 | 否 | 只渲染本次 `items`（`cli.py:386`） |
| 来源配额 | 否 | `apply_source_caps` 只处理 `items`，且未登记来源计为 `unresolved`（`cli.py:61-88`） |
| **`--render-only` 重渲染** | **会** | `list_analyses` 无来源过滤（`store.py:238`） |
| **事件去重与佐证** | **会** | `event_seen` / `event_sources` 按标题哈希跨全表匹配（`store.py:52-68`） |
| **熔断告警** | **会** | `consecutive_failures` 读 `runs`（`store.py:209`） |

第三类是**隐式耦合**：只要新来源往这三张表写数据，日报内容本身不会变，但会被去重逻辑和告警逻辑间接影响。

### 3.7 新来源失败时是否可能影响现有 RSS 任务

取决于接入位置，代码给出了三种明确的后果：

| 若新来源逻辑放在 | 后果 | 依据 |
|---|---|---|
| `cli.main()` 的外层 `try` 内、抓取/分析之前 | 异常 → `finish_run('failed')` + 告警邮件 → **当天日报不发送** | `cli.py:325,437-441` |
| 逐篇循环内 | 被 per-article `except` 捕获 → `errors+1` → 记 `analysis_failures`；若最终 `analyzed==0 且 failed>0`，`send_decision` 返回 `analysis_failed` → **不发日报** | `cli.py:372-376`、`cli.py:188-192` |
| 独立进程、独立表 | 不进入上述任一分支；但仍共享同一个 SQLite 文件 → 并发写可能 `database is locked` | `config.py:63`、`page_monitor.py:268` |

另有一项与失败无关但同样跨进程的影响：**整轮运行没有全局超时**，任何新增阶段变慢都会线性推迟日报。

### 3.8 实现完全隔离的最小边界

1. **独立表 + 独立前缀**：不得写 `articles` / `analyses` / `analysis_history` / `analysis_sections` / `runs`。
   写到这几张表的任何一张，都会通过 §3.5 的四个隐式入口影响现有链路。
2. **独立入口**：独立 module `main()` + 独立计划任务，且**不放在 `cli.main()` 的任何 `try` 块内**。
   仓库已有可复用的先例：`page_monitor.py`（自有表、自有 `main`、`cli.py` 不引用）。
3. **独立数据库文件**（首选）：彻底消除锁竞争；若必须共用同一文件，必须显式设置
   `PRAGMA journal_mode=WAL` 与 `busy_timeout`，并验证并发写。
4. **独立配置段**：不与 RSS 的 `freshrss_feed_id` 字段混用；`source_type` 明确区分。
5. **不进入 LLM 分析循环**：是否让新来源进入分析路径必须由显式开关控制，且默认关闭
   （条件 4 已量化：按实测 49.6–66.0 s/条，几十条就会让整轮从十几分钟膨胀到一小时以上）。
6. **失败自记**：新来源的运行结果不得写 `runs`，否则会污染 `consecutive_failures` 的熔断与告警判断。
7. **不动门槛**：不修改 `evidence.py`、`scoring.py`、`config/scoring.toml`。

---

## 4. 关键代码位置

| 关注点 | 位置 |
|---|---|
| 编排入口 | `cli.py:265` `main()` |
| 来源批准与 feed 过滤 | `cli.py:307-308`、`cli.py:332` |
| 抓取实现 | `freshrss_client.py:95-116` |
| 分析循环 | `cli.py:344-375` |
| LLM 输入 | `cli.py:364` → `analyzer.py:31` |
| 评分入口 | `cli.py:365` → `scoring.py:219-244` |
| 配额 | `cli.py:61-88`、`cli.py:377` |
| 日报渲染 | `cli.py:386` → `digest.py:280` |
| 重渲染（全库读） | `cli.py:216-263` → `store.py:238-243` |
| 事件去重/佐证 | `store.py:52-68` |
| 熔断告警 | `store.py:209` → `cli.py:203-215` |
| schema 与迁移 | `store.py:23`（`init()` 内含 `ALTER TABLE` 与回填） |
| 独立通道先例 | `page_monitor.py:256-262`（建表）、`page_monitor.py:358`（入口） |
| 计划任务 | `deploy/windows/run-digest.ps1:43` |

---

## 5. 隔离能力分级

### 5.1 代码已经保证的行为

| 结论 | 依据 |
|---|---|
| RSS 抓取是失败关闭的，未批准的 feed 不会被处理 | `cli.py:307-308, 332` 双重过滤 |
| LLM 只看到当篇文章的五个字段，看不到数据库 | `cli.py:364`、`analyzer.py:1-3` |
| 日报文本只由本次运行的内存 `items` 渲染 | `digest.py:1-6` 无 DB import；`cli.py:386` |
| 独立表 + 独立入口不会进入正常日报或分析 | 分析循环与渲染循环的数据源都限定在本次运行内 |
| 同一 DB 文件内可以并存独立表且互不引用 | `page_monitor.py` 已在运行，`cli.py` 无任何引用 |

### 5.2 通过代码推断的行为（未运行验证）

| 推断 | 依据与不确定性 |
|---|---|
| 新来源写入独立表后，`--render-only` 不会显示它们 | 推断自 `list_analyses` 的 SQL 只 JOIN `articles`/`analyses`；若新表改名或复制数据到这两张表则不成立 |
| 新来源不写 `articles`，则事件去重与多来源佐证不受影响 | 推断自 `event_seen`/`event_sources` 的 JOIN 条件 |
| 独立进程写同一 DB 时锁冲突概率低 | 推断自"日报每天一次、单进程顺序写"；**并发场景未测** |

### 5.3 需要运行测试才能确认的行为

| 待确认 | 为什么不能只靠读代码 |
|---|---|
| SQLite 并发写的实际锁行为 | 无 WAL、未设 busy_timeout，冲突时的重试与失败路径只能在真实并发下观察 |
| 新来源超时/限流时的传播范围 | 取决于尚未编写的调用位置与超时设计 |
| 新来源进程崩溃是否留下半写状态 | 取决于事务边界，尚未实现 |
| 熔断告警是否会因新增 `runs` 记录而误触发 | 需要构造失败序列 |

---

## 6. 尚未证实的判断

1. **"完全隔离"目前只是可设计，不是已实现。** 上述边界是建议，仓库里除 `page_monitor` 外没有第二个独立通道的实例可作证据。
2. **共享 DB 文件的并发安全性未经验证。** 现有系统实际是单进程顺序写，`page_monitor` 与日报同时运行时是否冲突，代码中没有 WAL 或 busy_timeout 的证据支持"不会冲突"。
3. **`--render-only` 的实际使用频率未知。** 如果它不在计划任务里，写入 `analyses` 的风险会降低，但我没有找到它的调度证据。
4. **新来源是否会进入 LLM 分析**是产品决策（条件 4 的 U5），不是代码能回答的问题。

---

## 7. 本轮未做

- 未运行任何入口（`cli.py`、`digest.py`、`page_monitor.py`、计划任务）。
- 未连接数据库（连只读连接也未建立）。
- 未修改任何文件，未创建连接器，未发起外部请求，未启动 R0。

---

## 8. 条件 5 判定

条件 5 原问："确认接入为独立通道，不影响现有日报、评分与证据门槛。"

它实际包含两个不同强度的断言，代码能证明的程度不同：

| 断言 | 判定 | 依据 |
|---|---|---|
| **A. 现有 RSS → LLM → 评分 → 日报链路不依赖新来源，新数据放独立表不会自动进入** | **PASS**（代码保证） | §5.1；`digest.py` 无 DB、分析循环限定本次抓取、`list_analyses` 只看 `articles/analyses` |
| **B. 新来源故障时能与现有 RSS 任务完全隔离** | **NOT_VERIFIED** | §5.3；无实现、无并发测试、共享 SQLite 无 WAL |

**合并判定：`NOT_VERIFIED`——独立通道可行性已由代码证实（A PASS），故障隔离有效性未验证（B）。**
不建议在完成一次本地故障注入前登记为 PASS_VERIFIED，否则会把"设计上可行"写成"已确认隔离"。

解除条件（二选一）：

1. 实现一个最小独立通道骨架（只读 mock、不接真实 API），跑一次并发与故障注入，观察锁行为与日报是否受影响；
2. 或由人工接受"设计层确认"这一较低标准，明确记录 B 仍为未验证。

无论哪种，§3.8 的七条边界都应作为条件 5 的落地要求写入实施设计。

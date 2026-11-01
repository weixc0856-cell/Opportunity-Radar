# R1 第一批（Event / Evidence / Claim 统一模型）— 实施与验收记录

日期：2026-11-01
状态：**第一批实现完成，测试通过，真实数据回填在数据库副本上验证**；未接入评分、日报或模型调用
上游设计：`docs/PRD.md` §5.3 / §6.1、`docs/IMPLEMENTATION_PLAN.md` §6

---

## 1. 范围

交付：事件（events）、事件—文章关联（event_articles）、证据（evidences）、主张（claims）、
主张—证据关联（claim_evidence）、事件纠错（event_corrections）六张表，加上把 RSS、SEC、EIA
已有数据映射进去的回填工具。

不做：评分、优先级、日报、LLM 抽取、事件合并的模型判定、核验（R2）、周报月报（R4）。

---

## 2. 数据契约（已冻结）

### 2.1 标识符

全部是内容哈希，因此重复运行不会产生第二条记录：

| 实体 | 生成方式 |
|---|---|
| `event_id` | `evt-` + sha256(规范化事件键)[:16]；事件键是种子文章的规范化 URL |
| `evidence_id` | `ev-` + sha256(article_key, 规范化引文, 定位字段, 定位起点, accn, period)[:16] |
| `claim_id` | `cl-` + sha256(article_key, fact_ordinal)[:16]；结构化来源用 (来源, 主体, 指标, 期间, accn) |
| `claim_evidence` | 主键 (claim_id, evidence_id) |

### 2.2 事件关联（保守优先）

两条规则，命中即停；其余一律视为不同事件：

| 规则 | 条件 | 关系 | 置信度 |
|---|---|---|---|
| 1 | 规范化 URL 相同 | `same_story` | 1.0 |
| 2 | 规范化标题相同 **且** 与事件已有成员的时间差 ≤ 72 小时 | `same_story` | 0.9 |
| — | 其他情况 | 各自独立事件，`reason=no_rule_matched` / `title_outside_window` | — |

规范化：URL 去掉 scheme/host 大小写差异、`www.`、追踪参数（`utm_*`/`fbclid`/`gclid`/`ref`）、
fragment 与末尾斜杠；标题去标点、统一大小写、折叠空白，并只剥除**末尾**的发布方后缀
（`time series`、`release`、`data` 等），避免把 "time series review" 误当作 "…review"。

不合并的情形（明确保留为独立事件）：同企业不同公告、同政策不同阶段、同成果不同载体、
同类事件连续发生。批次 1 没有实现基于实体/事件类型的候选判定，因此也不会因此误合并。

### 2.3 主张状态

`kind` ∈ fact / source_interpretation / system_inference / hypothesis / forecast / opinion。
`verification_state` 批次 1 只有 `unverified` —— R2 才做判定，任何"已验证"的标记都必须来自核验。

`extractor` 记录主张是怎么来的：

| 值 | 含义 |
|---|---|
| `skeleton` | 由 v5 fact（散文 + 引文 + 定位）生成；数值字段为空，因为 v5 提示词从不要求它们 |
| `structured` | 由 SEC XBRL fact 或 EIA observation 直接映射；数值、单位、期间、修订状态均有来源 |

### 2.4 隔离

- RSS 的统一表写入生产库（与文章同库，附加式建表）。
- SEC / EIA 的统一表写入**各自的摄取库**：契约相同、文件不同。G-D2 仍然禁止它们的记录进入
  RSS 业务表，因此共享的是数据结构而不是数据库。
- 迁移：`CREATE TABLE IF NOT EXISTS` + `PRAGMA user_version = 1`（只升不降）；只读路径不迁移。

---

## 3. 映射

| 来源 | 证据 | 主张 |
|---|---|---|
| RSS v5 fact（`status='located'`） | `evidence_kind='quote'`，引文 + 定位（字段/起点/长度）+ 来源 + 发布时间 | `extractor='skeleton'`，`subject` 取 fact 的 `actor`，`value_text` 取 fact 文本，其余结构化字段为空 |
| RSS v5 fact（`status='unlocated'`） | **不生成**证据与主张（FR-E4） | 计入 `facts_skipped_unlocated` |
| RSS v4 记录 | 不生成（计划 §6.3 明确不回填） | 计为 `articles_skipped_v4`，但**仍生成事件**（事件只依赖文章元数据） |
| SEC XBRL fact | `evidence_kind='sec_fact'`，定位含 accn / cik / taxonomy / tag / form / filed / 起止期间 | `extractor='structured'`，主体=公司，指标=metric_id，数值、单位、期间、修订关系（filing_relation） |
| EIA observation | `evidence_kind='eia_observation'`，定位含 series_id / period / 数据集 / route / 指标 / 快照哈希 | `extractor='structured'`，主体=route，指标=metric，期间与单位 |

来源独立性：RSS 一律 `unknown`（来源登记表尚无 `source_family` 字段，不猜）；SEC / EIA 记为
`independent_primary`，因为它们是发布者自己的原始记录——这是对来源性质的描述，不是对已核验
佐证数量的断言。

---

## 4. 真实数据验证（全部在数据库副本上进行）

| 库 | 输入 | 结果 |
|---|---|---|
| 生产库副本 `data/opportunity_radar.sqlite3` | 108 篇有分析的文章（其中 38 篇 v4） | 108 个事件、220 条证据、220 条主张、220 条关联；12 条无法定位的 fact 未生成主张 |
| 摄取库副本 | SEC 2,719 条事实 | 2,719 证据 / 2,719 主张 / 2,719 关联 |
| 摄取库副本 | EIA 34 条观测 | 34 证据 / 34 主张 / 34 关联 |

- **幂等**：两个库各重跑一次，新增证据/主张/关联均为 0。
- **可回溯**：`claims_without_locator = 0`、`claims_without_evidence = 0`（两库均为 0）。
- **事件合并**：当前语料里没有重复标题或重复 URL，所以 108 篇文章 = 108 个事件，是正确结果而不是
  规则失效。为验证规则本身，在另一个副本上把一篇真实 ONS 文章按 ONS 自己的方式重发一次
  （标题追加 `— time series`、URL 追加 `-series`）：回填后该事件有 2 名成员，第二条以
  `reason=title_within_window` 并入，其余 107 个事件不受影响。
- **生产库未被写入**：验证全程使用副本；生产库 SHA-256 保持 `e18272e69fcaea50…`。

---

## 5. 测试

| 项 | 数值 |
|---|---|
| 新增文件 | `tests/test_unified.py`（22 项） |
| 全量 | **604 项通过**（R1 前 582） |

覆盖：URL/标题规范化；时间窗边界（72 小时内合并、外不合并、只共享关键词不合并）；重复分配
不新增；无 `articles` 表的库也能写入；证据/主张 ID 的确定性；unlocated fact 无法生成证据；
SEC/EIA 的定位字段；回填幂等；主张可回溯到文章与位置；未知来源记为 `unknown`。

---

## 6. 未做与遗留

1. **RSS 主张是骨架**：v5 提示词不产出结构化主张，所以 220 条主张的 `value_num`/`unit`/`period`
   为空，`extractor='skeleton'`。R2 升级提示词后才会有可核验的数值主张；在此之前不应把骨架
   当作"已抽取的事实"。
2. **SEC/EIA 没有事件**：事件是文章级概念，结构化事实目前只有主张与证据，没有事件归属。跨来源
   关联（例如"某公司财报"同时出现在新闻与 XBRL）要等到有实体对齐或事件类型设计之后。
3. **独立性字段是占位**：RSS 全部 `unknown`。PRD §6.2 要求的来源谱系字段（source_family /
   parent_source / syndication_group / ownership_group）尚未进入来源登记表，属于后续批次。
4. **候选合并未实现**：批次 1 只有 URL 与标题两条规则，实体/事件类型的候选判定（`candidate` /
   `related_not_same`）没有实现，因此不会出现"看起来像但不确定"的中间态。
5. **未接入 CLI 与日报**：回填是独立命令，日报链路完全没有引用新表。是否在每日运行中增量回填，
   留到下一步决定。
6. **事件键的稳定性**：新事件以种子文章（最早的成员）的规范化 URL 作为键。补入比现有种子更早的
   文章会改变种子，从而改变事件键。当前语料是按时间回填的，不受影响；增量运行只追加更新的文章。

---

## 7. 与设计的差异

| `IMPLEMENTATION_PLAN.md` §6 | 本批实现 | 原因 |
|---|---|---|
| `event_articles` 有 relation/assignment/confidence | 另加 `reason` 列 | 记录命中哪条规则，便于复核误合并 |
| `claims` 有 `verification_state` | 另加 `extractor` 列 | 区分骨架主张与结构化主张，R2 需要知道证据来源强度 |
| 事件候选分级规则 | 未实现 | 需要实体/事件类型抽取；没有它就无法把"高度重叠"与"共享关键词"分开 |
| 回填从 analysis_sections 取 located fact | 同 | — |
| 来源谱系字段进入登记表 | 未做 | 属于来源治理批次，与本批解耦 |

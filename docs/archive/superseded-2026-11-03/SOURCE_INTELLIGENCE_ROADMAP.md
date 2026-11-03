# Opportunity-Radar 多渠道信息发现实施路线（建议稿）

版本：0.1（建议稿，未批准）
日期：2026-11-02
基线：`main@1c45b9b`；N0–N5 冻结在 Batch 16
性质：路线建议，不是开发计划，不代表已获 G5/G6 批准。

关联文件：

- [SOURCE_INTELLIGENCE_RESEARCH.md](SOURCE_INTELLIGENCE_RESEARCH.md)
- [source-catalog.csv](source-catalog.csv)
- [source-tools-comparison.csv](source-tools-comparison.csv)
- [source-coverage-matrix.csv](source-coverage-matrix.csv)

---

## 0. 路线原则

1. **先治理，后接入**：没有 `source_id`、adapter contract、权利/留存元数据、去重基线，不批量加来源。
2. **发现与证据分离**：GDELT/Event Registry/搜索服务只写 discovery candidates，不生成 evidence/claim。
3. **一手优先**：官方统计、政策原文、企业申报、公司登记、采购、专利优先于新闻聚合。
4. **RSS 收窄角色**：保留已批准发布者的 RSS/Atom，不再以 RSS 数量作为覆盖指标。
5. **SEC/EIA 隔离不变**：独立库、独立入口、独立运行记录；跨库仅 candidate link。
6. **影子优先**：新来源先观察/影子运行，不直接进日报/生产 claim；生产启用需 G5/G6。
7. **成本可持续**：免费/低成本优先；付费数据必须证明独特增量和单位经济。
8. **失败可见**：配额、解析失败、结构变化、覆盖率不足都写运行记录，不渲染成“没有信号”。

---

## 1. 阶段总表

| 阶段 | 目标 | 依赖 | 主要输出 | 预计工作量 | 生产影响 | 审批 |
|---|---|---|---|---|---|---|
| P0 来源治理基础 | 来源身份、adapter contract、权利/留存元数据、去重基线 | 无 | source registry v2、运行记录、去重报告 | 1–2 周 | 无 | 内部 |
| P1 发现层影子 | GDELT 只写 discovery candidates | P0 | discovery_candidates、对比报告 | 2–4 周 | 无 | G5 范围（数据访问/条款） |
| P2 一手宏观/政策 | FRED/BLS/Federal Register + Eurostat/GOV.UK | P0 | observations/policy docs、adapter 健康 | 3–5 周 | 独立库，不进日报 | G5 |
| P3 企业/实体 | SEC EDGAR 扩展、Companies House、GLEIF、DART/EDINET | P0/P2 | filings/registry、entity links | 3–5 周 | SEC 独立通道 | G5 |
| P4 Newsletter/页面监测 | 专用邮箱、gov.cn/NBS/IR/协会页面 | P0 | newsletter_items/page_changes | 2–4 周 | 影子/内部 | G5 + 法务确认 |
| P5 独立性与事件关联 | 正文相似度、转载、来源族、事件关联 | P1–P4 | dedupe/lineage/event clusters | 2–3 周 | 影响证据质量，不改门禁 | 内部 |
| P6 商业/社交（条件） | 付费数据、社交 API | P1–P5 + 预算 | 商业数据接入/评估报告 | 按合同 | 需单独批准 | G5/G6 相关 |

> 阶段可裁剪；不是所有阶段都必须实施。P6 只在 P1–P5 证明缺口且单位经济成立时启动。

---

## 2. P0：来源治理与接入基础

### 目标

在任何新来源接入前，先修“来源身份、接入契约、权利元数据、去重基线”。这是后续所有阶段的前提。

### 输入

- 当前 `config/sources.csv`、`sources.local.csv`、`source_lineage.csv`。
- 当前 `articles`/`analyses`/`events`/`evidences`/`claims` schema。
- `source_policy.py`、`freshrss_client.py`、`page_monitor.py`、`datasets.py`、`ingest/`。

### 输出

1. **source registry v2**：`source_id`、`source_role`、`source_family`、`access_method`、`connector_id`、`terms_url`、`license_status`、`retention_limit`、`credential_ref`、`subscriber_display`。
2. **adapter contract**：`fetch()`、`normalize()`、`provenance()`、`rights()`、`health()`；每个 adapter 独立 CLI 入口、运行 ID、退出码。
3. **来源身份**：`articles` 追加 `source_id`、`connector_id`、`external_id`、`retrieved_at`、`terms_reviewed_at`；历史文章回填/标记。
4. **原始记录层**：`raw_snapshots`（source_id、url、request_key、status、sha256、retrieved_at）。
5. **标准化记录层**：Article / Observation / Filing / NewsletterItem / Signal / PageChange / DiscoveryCandidate，不强行统一成 Article。
6. **权利/留存元数据**：来源级 + 字段级；`ALLOWED/CONDITIONAL/PROHIBITED/UNKNOWN/NOT_APPLICABLE`。
7. **去重基线**：URL canonicalization、标题、正文 shingle/Jaccard、`syndication_group`、来源族；小语料先用标准库，语料增大再评估 datasketch。
8. **配额/熔断**：读取 `max_requests_per_day`；每源失败/429/结构变化记录；不阻塞其他 adapter。
9. **验收报告**：100% 新文章有 `source_id`；来源审计通过；现有测试/日报不回归；无跨库写入。

### 技术选型

- Python 标准库 `urllib`、`sqlite3`、`csv/json/xml`、`hashlib`、`html.parser`。
- SQLite FTS5（内置）用于全文检索。
- Windows 计划任务 + 现有启动器模式。
- 不引入 Airflow/Kafka/Redis/向量数据库。

### 风险

- 历史文章回填可能无法确定 `source_id`；不能猜测，标 `unknown`。
- 去重阈值需要标注样本校准；不能凭感觉设阈值。
- 权利元数据需要人工/法务审核；`UNKNOWN` 不能上线。

---

## 3. P1：GDELT 发现层影子

### 目标

测量“RSS 之外还能发现什么”，不生成 evidence/claim。

### 输入

- GDELT DOC/GEO 2.0（免费、无 key）。
- 现有 RSS 文章标题/URL/来源族作为对照。

### 输出

- `discovery_candidates`：URL、domain、title、seendate、language、sourcecountry、query、matched_event、first_seen。
- 对比报告：新增 URL/事件/域名、与现有文章重复率、语言/地区分布、延迟、失败原因。
- 候选域名清单：是否已批准、是否可访问、是否需要条款复核。

### 验收指标

- 2–4 周影子运行。
- 新增事件/URL 数量与质量（人工抽样）。
- 与现有 RSS 的重复率（URL/标题/正文）。
- 可解析/可访问率。
- 采集失败/限流率。
- **不生成 evidence/claim**；不进入日报。

### 技术选型

- 标准库 `urllib` + JSON；单次最多 250 条；按时间窗切分；约 1 请求/5 秒；指数退避。
- 不用 GDELT 作为证据；原始来源必须回溯。

### 风险

- GDELT 覆盖/语言/来源偏差；不能把“可报道”当“有价值”。
- 上游新闻版权；只保留发现元数据，正文需原来源授权。
- 无 SLA；限流/封禁；需要缓存和退避。

---

## 4. P2：一手宏观/政策

### 目标

把“新闻标题级宏观”升级为“官方序列/政策原文”。

### 输入

- FRED、BLS、Federal Register、Eurostat、GOV.UK（首批）。
- 后续：BEA、Census、World Bank、IMF、OECD、ECB。

### 输出

- `observations`：dataset_id、indicator、geography、unit、frequency、seasonality、period、value、revision、published_at、retrieved_at、source_url、license_status。
- `policy_documents`：agency、document_type、title、published_at、effective_at、docket、url、raw_snapshot。
- adapter 健康记录：请求数、失败、429、schema 变化、最近成功时间。

### 验收指标

- 样本值与原站一致；期间/单位/季调/修订保留。
- 每个来源的条款/许可/配额/署名记录。
- 失败可见；无跨库写入；不影响 RSS/日报。
- 至少覆盖 P0 缺口中的宏观/政策两类。

### 技术选型

- 标准库 `urllib` + JSON/XML/CSV；SDMX/JSON-stat 用标准库解析。
- 独立 SQLite 库/命名空间；不写 RSS 业务表。
- 不能用 `datasets.py` 的“只探最新期”代替历史序列；需要新增 observation 存储。

### 风险

- 口径/修订/季调差异；不能直接拼序列。
- 第三方数据集许可；FRED/IMF/World Bank 例外。
- API 版本/字段变化；需要 schema 检查。

---

## 5. P3：企业披露与实体

### 目标

补“企业自己披露了什么”和“这家公司是谁”。

### 输入

- SEC EDGAR submissions/full-text/Form D。
- Companies House API。
- GLEIF API。
- 后续：DART、EDINET。

### 输出

- `filings`：CIK/company number、form type、accession、period、filed_at、url、raw_snapshot、amendment flag。
- `entities`/`entity_links`：LEI、CIK、company number、parent/child、aliases。
- 候选关联：filing↔event、company↔event，状态 `candidate`，不自动合并。

### 验收指标

- 标注样本上的 entity match precision/recall。
- 申报原文可追溯；期间/单位/表单/修订正确。
- SEC 仍在独立通道；不进入 RSS/LLM/日报。
- Companies House 公共登记条款/个人数据合规记录。

### 技术选型

- 标准库 `urllib` + JSON/XML；SEC UA/10 req/s；Companies House 600/5min。
- XBRL 标签/期间/YTD/修订需要专门解析；不能直接把所有 facts 拼成序列。
- GLEIF CC0；实体匹配规则先确定性，后模糊匹配。

### 风险

- XBRL 标签差异、季度累计值、修订申报。
- 同名/母子公司/股票代码冲突；LEI 覆盖不全。
- Companies House 公共登记≠OGL；个人数据/第三方版权。

---

## 6. P4：Newsletter 与页面监测

### 目标

补无 API/Feed 的专业信息和官方页面。

### 输入

- 用户自有订阅的专用邮箱（IMAP）。
- 已批准页面清单（gov.cn/NBS/IR/协会/标准/招投标）。

### 输出

- `newsletter_items`：sender、subject、date、message_id、thread_id、text、links、attachments、content_hash、rights_snapshot。
- `page_changes`：watch_id、url、title、hash、diff、first_seen、structure_change flag。
- 权利登记：每个 sender/site 的存储/分析/展示/再分发状态。

### 验收指标

- 专用邮箱/最小权限；SPF/DKIM/DMARC 检查；附件不自动执行。
- 页面结构变化告警；401/403/429 停止；robots/条款记录。
- 只存允许的内容；默认链接/标题/哈希。
- 不进入日报，除非来源与内容权利明确。

### 技术选型

- 标准库 `imaplib` + `email`；`mail-parser` 可选。
- 标准库 `urllib` + 条件请求 + 规范化哈希；`trafilatura` 可选。
- changedetection.io 仅作参考/独立服务；不嵌入核心。
- Playwright 仅对明确允许的 JS 页面，默认不用。

### 风险

- 订阅≠自动化/分析/展示/再分发。
- 钓鱼/恶意附件/远程图片/账号泄露。
- 页面结构变化/JS/反爬；维护成本高。
- 个人数据/跨境传输。

---

## 7. P5：独立性、转载与事件关联

### 目标

把“来源数量”变成“独立来源族 + 原始发布者 + 传播链”。

### 输入

- P1–P4 的 discovery/article/newsletter/page records。
- `source_lineage.csv`、`source_family`、`syndication_group`。

### 输出

- 正文相似度/SimHash/MinHash 报告。
- 转载/联合发布/新闻稿标记。
- `syndication_group` 回填（有证据才填）。
- 事件聚类与多文章事件；候选关联状态。
- 独立佐证画像：按来源族/所有权/原始发布者计数。

### 验收指标

- 标注样本上的重复识别 precision/recall。
- 误判独立佐证率（aggregator/转载被当独立）。
- 多文章事件数量与质量。
- `multi_source_coverage` 触发是否合理。
- 人工复核时间。

### 技术选型

- 标准库 shingle/Jaccard 起步；语料增大用 datasketch（MIT）。
- 通讯社/新闻稿标记：域名、boilerplate、联系人、forward-looking statements、wire 署名。
- 跨语言不自动合并；实体/期间/数值对齐后人工确认。

### 风险

- 过度合并/漏合并；阈值需要标注。
- 转载与独立报道难区分；保守合并。
- 跨语言/翻译重复。
- 聚合器误计为独立来源。

---

## 8. P6：商业授权与社交（条件启动）

### 启动条件

- P1–P5 已证明存在免费/官方来源无法补的缺口；
- 有明确预算与单位经济；
- 法务/商务确认许可允许内部使用/客户展示/衍生数据；
- 不影响本地优先/可追溯架构。

### 候选

- 新闻全文/事件：Event Registry、NewsAPI、RavenPack、Dataminr。
- 私营市场：PitchBook、Crunchbase、CB Insights。
- 电话会/专家：AlphaSense。
- 产业/能源：OICA、ACEA、IFR、IEA。
- 社交：X、Reddit、YouTube、Bluesky（观察）。

### 验收指标

- 每个有用事件的成本。
- 独特增量（free/baseline 没有的信息）。
- 许可/展示/再分发合规。
- 维护/合同/审计成本。
- 不达标即停止/不续费。

### 风险

- 高价/长约/最低采购。
- 内部使用 vs 客户展示 vs 再分发。
- 供应商锁定/数据删除义务。
- 与现有免费来源重叠。

---

## 9. 依赖关系

```
P0 治理基础
 ├─> P1 GDELT 发现影子
 ├─> P2 一手宏观/政策
 │     └─> P3 企业/实体（可与 P2 并行）
 ├─> P4 Newsletter/页面监测
 └─> P5 独立性/事件关联（依赖 P1–P4 的数据）
        └─> P6 商业/社交（条件）
```

- P1 不依赖 P2；可并行。
- P2 与 P3 可并行，但 P3 的实体解析依赖 P0 的 `source_id`/entity 规则。
- P5 需要 P1–P4 的样本；不能凭空设计阈值。
- P6 必须最后。

---

## 10. 验收指标

| 指标 | 基线 | 目标/说明 |
|---|---|---|
| `source_id` 覆盖率 | 0%（无列） | 100% 新文章/记录 |
| 来源审计 | 15 启用/32 未批准 | 每源条款/许可/配额/留存记录完整 |
| 发现新增 | 0 多文章事件 | 每周 RSS 外新增事件/URL；人工抽样质量 |
| 独立佐证 | `multi_source_coverage=0` | 标注事件中至少 2 个独立来源族；聚合器不计 |
| 重复/转载 | `syndication_group` 空 | 标注集 precision/recall；误判独立率 |
| 证据可追溯 | 生产 claim 骨架 | 新记录 100% 回到 raw snapshot/URL/定位 |
| 实体匹配 | 10 entities/2 mentions | 标注样本 precision/recall |
| 来源健康 | 仅 RSS | 每源成功率/延迟/陈旧/429/结构变化 |
| 成本/有用事件 | NOT_MEASURED | 付费源必须计算 |
| 人工复核时间 | NOT_MEASURED | 每条进入简报的记录 |
| 发布门禁 | R0 现有指标 | 新来源不得导致 HOLD/误报回退 |
| 来源数量/API 数量 | — | **不作为验收指标** |

---

## 11. 生产影响与审批

- P0/P1：不影响生产；P1 需数据访问/条款评审（G5 范围）。
- P2/P3：写独立库/命名空间；不进入 RSS/LLM/日报；需 G5。
- P4：Newsletter/页面监测先影子/内部；需 G5 + 法务确认。
- P5：影响证据质量与事件视图；不改门禁；需内部评审。
- P6：商业/社交需单独批准；涉及客户展示/再分发时需法务/商务。
- 任何生产 Claim 仍需 G6；v7 仍不启用；N0–N5 Batch 17 不启动。
- SEC/EIA 独立边界不变；不得因统一采集架构合并数据库。

---

## 12. 首批执行建议（有限资源）

### 必须做

1. P0：`source_id` + adapter contract + rights metadata + dedupe baseline。
2. P1：GDELT 影子发现，2–4 周，只写 candidates。
3. P2：FRED + BLS + Federal Register；P3：SEC EDGAR 扩展。

### 有余力再做

- Eurostat + GOV.UK。
- Companies House + GLEIF。
- TED。

### 暂不做

- Newsletter/页面监测大规模铺开。
- 社交 API。
- 商业终端/私募/电话会。
- 产业协会付费数据。

### 停止条件

- GDELT 新增价值不足/噪声过高 → 不进入下一阶段。
- 官方 API 样本口径/许可无法满足 → 暂停该源。
- 去重/实体匹配不达标 → 不扩大来源数量。
- 付费数据单位经济不成立 → 不采购/不续费。

---

## 13. 风险与回滚

- 每个 adapter 独立开关；失败不影响其他 adapter。
- 新来源写入独立库/命名空间；可整体停用/回滚。
- 保留原始快照与版本；可重建标准化记录。
- 权属变化/条款更新 → 停用来源，保留历史标记，不删除已发布证据（除非法律要求）。
- 任何阶段验收失败 → 停止，不进入下一阶段；不以“技术已跑通”代替业务价值。

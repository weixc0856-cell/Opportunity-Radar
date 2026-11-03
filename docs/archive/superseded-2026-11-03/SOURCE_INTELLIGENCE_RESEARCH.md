# Opportunity-Radar 多渠道信息发现与合规数据获取体系调研

版本：0.1（调研稿，未批准）
日期：2026-11-02
基线：`main@1c45b9b`；N0–N5 冻结在 Batch 16
性质：只读调研与方案建议。**未修改生产代码、数据库、配置、采集任务、日报、评分或发布门禁；未接入任何真实外部 API；未申请账号或订阅。**

关联交付物：

- [source-catalog.csv](source-catalog.csv)：56 个候选来源的统一结构化清单
- [source-tools-comparison.csv](source-tools-comparison.csv)：26 个工具/库的对照
- [source-coverage-matrix.csv](source-coverage-matrix.csv)：33 个行业/地域/信息类型覆盖矩阵
- [SOURCE_INTELLIGENCE_ROADMAP.md](SOURCE_INTELLIGENCE_ROADMAP.md)：分阶段实施建议

证据标记：

- `[官方]`：来自官方文档、服务条款、许可证或价格页；检索日期 2026-11-02。
- `[第三方]`：来自第三方摘要、评测或社区资料；需要复核。
- `[工程判断]`：基于当前代码与数据结构的工程结论。
- `[产品建议]`：需要用户/产品决策的建议。
- `[待法律/商务确认]`：不能由工程判断替代的事项。

**方法与限制**：

- 本次只读检查仓库；外部资料检索日期为 2026-11-02。
- 部分官方页面有反爬/地域/登录限制，未能直接读取；相关价格/配额以第三方摘要或搜索片段记录，已标 `[第三方]`，上线前必须回到官方页面复核。
- 价格、免费额度、API 配额和条款会变化；本报告不构成法律意见。
- `source-catalog.csv` 的 56 行包含 5 行“渠道类”记录（Newsletter/页面监测），用 `MULTIPLE`/`PER_SENDER`/`PER_SITE` 标记，它们不是单一来源，需要逐个 sender/site 建立子记录。

---

## 1. 执行摘要

### 1.1 当前事实

Opportunity-Radar 目前是一个**窄而可追溯的 RSS + 两个官方结构化通道**，还不是一个多渠道情报发现系统。

- 47 行来源登记，15 行启用，32 行 `review_required`；15 个启用来源形成 12 个来源族。
- 生产库 126 篇文章、117 篇已分析；L5 早期信号 82 篇（65.1%），L3 新闻 32 篇（25.4%），L0 官方/一手 12 篇（9.5%）；L1、L2、L4 为 0。
- 117 个事件中，**0 个事件包含多篇文章**；`multi_source_coverage` 为 0；`syndication_group` 全为空。
- 220 条 evidence / 220 条 claim 全部是 RSS 骨架主张、`unverified`；生产 `verify` 从未执行（`claim_verifications=0`）。
- SEC/EIA 独立库有 2,719 条 SEC facts、34 条 EIA observations，但与 RSS、日报、LLM 隔离。
- N0–N5 影子 Claim 冻结在 Batch 16；未进入生产 claims/analyses。

### 1.2 核心判断

当前最缺的不是 RSS 数量，而是四类能力：

1. **发现层**：在订阅之外发现事件、原始文档和跨来源报道（GDELT 类服务）。
2. **一手结构化来源**：官方统计、政策原文、企业申报、公司注册、采购、专利、贸易、能源序列。
3. **来源身份与独立性**：把原始发布者、传播者、聚合器、独立佐证者分开；不能把转载数量当多源。
4. **可持续成本模型**：免费 API 往往有非商业许可、额度、历史/展示限制；必须按“低成本可直接用 / 有条件可用 / 需商业合同 / 暂不值得”分层。

### 1.3 七类渠道结论

| 渠道 | 结论 | 首要用途 | 主要限制 |
|---|---|---|---|
| 官方 API | **最高优先级** | 一手统计、政策、申报、注册、采购、专利 | 需逐源条款；部分亚洲来源无正式 API/条款不明 |
| RSS/Atom | **保留但收窄角色** | 已批准新闻、企业官方、协会公告 | 摘要为主、无历史/结构、转载/来源身份弱 |
| Newsletter | **可行，第三阶段** | 政府/IR/协会/智库/垂直媒体的专业更新 | 订阅≠自动化/分析/展示/再分发；邮箱安全与维护 |
| 页面变更监测 | **必要但高维护** | 中国政策、IR、协会、标准/招投标页面 | JS/反爬/结构变化；robots 不等于许可 |
| 公共数据平台 | **高价值** | 宏观、贸易、能源、人口、企业登记 | 口径差异、许可证差异、历史/修订处理 |
| 社交平台 API | **暂缓** | 早期弱信号、官方/专家账号 | 付费/非商业/保留期限/删除义务；不能作证据 |
| 商业授权数据 | **暂缓，按需** | 全文新闻、私营市场、电话会、终端数据 | 高价、内部使用/展示/再分发限制 |

### 1.4 成本分层（catalog 统计）

- `low_cost_direct`：20 个来源——免费/开放、无需商业合同，可直接进入研究或首批接入。
- `limited_use`：24 个来源——免费或低成本，但有额度、非商业、展示、历史或地域限制。
- `commercial_contract`：9 个来源——需要付费、企业合同或询价。
- `not_worth_it`：3 个来源——已退役、许可不可接受或维护成本高于价值。

> 这些数量只描述目录构成，**不是情报覆盖指标**。真正指标见第 12 章。

### 1.5 首批建议

10 个 `PRIORITY_1` 来源（完整清单见第 11 章）：

GDELT、FRED、BLS、Eurostat、Federal Register、GOV.UK、SEC EDGAR、Companies House、GLEIF、TED。

若下一阶段只允许投入有限开发时间，建议先做三件事：

1. **修来源身份与接入基础**：`source_id`、adapter contract、权限/留存元数据、正文相似度与转载识别。这不是“来源”，但决定后续是否可控。
2. **GDELT 发现层影子运行**：只写发现候选，不生成 evidence/claim，用来测量“RSS 之外还能发现什么”。
3. **接 3–5 个一手来源**：FRED/BLS（宏观）、Federal Register（政策）、SEC EDGAR（企业申报）；第二批再补 Eurostat、GOV.UK、Companies House、GLEIF、TED。

### 1.6 架构建议

推荐**方案 C：混合式架构**——RSS 继续走 FreshRSS；官方/结构化数据走独立 adapter + 独立库；发现服务只写 discovery candidates；Newsletter/页面监测各自 adapter；在 event/evidence/claim 层统一关联。不推荐一次性建统一采集大框架（方案 B），也不推荐只做零散脚本（方案 A）。

---

## 2. 当前系统真实能力

### 2.1 来源与数据

| 项目 | 实际状态 | 证据 |
|---|---|---|
| 来源登记 | 47 行；15 启用；32 `review_required` | `config/sources.csv`、`config/sources.local.csv` |
| FreshRSS | 27 个订阅；15 个已批准 Feed；12 个抓取但未批准 | S0 审计、本机配置 |
| 文章 | 126 篇；117 篇已分析 | `data/opportunity_radar.sqlite3` |
| 来源族 | 15 来源 → 12 族 | `config/source_lineage.csv` |
| 层级 | L5 82（65.1%）、L3 32（25.4%）、L0 12（9.5%）、L1/L2/L4 0 | 按来源类型与文章数 |
| 事件 | 117 个；0 个多文章事件 | `events` / `event_articles` |
| 证据/主张 | 220 / 220；全部 skeleton、unverified | `evidences` / `claims` |
| 实体 | 10 entities；2 mentions；3 candidate links | `entities` / `entity_mentions` / `event_links` |
| 谱系 | 15 条全部 `declared`；`syndication_group` 空 | `source_lineage.csv`、`evidences` |

### 2.2 代码能力

| 能力 | 当前实现 | 限制 |
|---|---|---|
| Feed 接入 | 仅 FreshRSS Fever API | 没有通用 API/JSON/批量连接器 |
| 来源身份 | `articles` 只有 `source_name`，没有 `source_id` | 新增来源无法稳定绑定；已有 3 篇无法按名称归属 |
| `official_api` | 配置允许，但 `is_approved()` 仍要求 `feed_url` + `freshrss_feed_id` | API 来源不能仅靠配置接入 |
| 配额 | `max_requests_per_day` 未进入 `Source` 数据类 | 未读取、未强制、无采集层退避/熔断 |
| 正文 | `full_text_fetch` 全部 `none` | 新闻/官方多为 E1 摘要证据 |
| 页面监测 | `page_monitor.py` 只存链接/标题 | 不抓正文；JS 页面 blocked |
| 结构化数据 | `datasets.py` 只探测最新期 | 不存历史、修订、原始快照 |
| 结构化摄取 | SEC/EIA 独立库 | 10 家公司 XBRL、少量 EIA 序列；不进入 RSS/日报 |
| 去重 | URL/标题 72 小时 | 无正文相似度、通讯社标记、跨语言 |
| 主张 | N0–N5 影子链路 | 生产 claim 仍是骨架；verify 未运行 |

### 2.3 现有边界（必须保留）

1. **RSS 生产链路**：`cli.py` → FreshRSS → `analyses` → R1 events/evidences/claims → 日报/门禁。生产提示词仍是 v6。
2. **SEC/EIA 独立链路**：独立库、独立入口、独立运行记录；不进入 RSS 业务表、LLM、日报；跨库仅 candidate link。
3. **影子 Claim 链路**：N0–N5 只写 `data/claim-pipeline/` 与 node_runs；不写生产 claims/analyses；不进入日报/verify。
4. **R0 门禁**：覆盖率、HOLD、失败可见；新增来源不得改变现有门禁语义。
5. **Windows 本地部署**：Python 标准库 + SQLite + 计划任务；不引入重型编排。

### 2.4 结论

当前系统能回答“这 126 篇已订阅文章里发生了什么”，不能回答“今天还有哪些重要事件没有出现在我的订阅里”。这就是本调研要解决的差距。

---

## 3. 现有信息源覆盖缺口

### 3.1 覆盖结构

| 维度 | 当前 | 缺口 |
|---|---|---|
| 地理 | 美国、英国、全球平台（HN/OpenAI/工程论坛） | 中国、亚洲其他、欧洲非英国 |
| 来源类型 | 社区/论坛、新闻媒体、少量官方统计、一家企业新闻室 | 监管、协会、交易所/披露、采购、专利、智库、行业媒体 |
| 信息类型 | 标题/摘要、少量全文论坛帖 | 结构化序列、申报原文、政策原文、合同、职位、专利、贸易/航运 |
| 证据基础 | 多数 E1；E2 仅来自声明 `full_text` 的论坛 | 官方/新闻正文获取受限；`full_text_fetch` 全关 |
| 事件 | 0 个多文章事件；0 独立佐证 | 跨来源事件、转载识别、来源族计数 |
| 实体 | 10 个 entity、2 个 mention | 公司主数据、LEI/CIK/公司号、母子公司、别名 |
| 主张 | 骨架、无数值/单位/期间 | 可核验数值主张仍靠 R2 影子链路 |

### 3.2 来源角色：四个概念不能混用

本次调研把来源角色单独建模，而不是只记“来源名称”：

| 角色 | 定义 | 例子 | 证据含义 |
|---|---|---|---|
| 原始发布者 `original_publisher` | 政府、监管、统计机构、企业、协会、标准组织等直接发布 | SEC、EIA、BLS、Federal Register、公司 IR | 可作为一手证据；企业自述只证明“它这样说过” |
| 传播者 `transmitter` | 新闻机构、通讯社、媒体 | BBC、NYT、Reuters、行业媒体 | 二手报道；可能有独立采编，也可能是转载 |
| 聚合器 `aggregator` | 把多方内容聚合/聚类，不原创事实 | GDELT、Event Registry、NewsAPI、FRED/World Bank 等汇编 | 只做发现/索引；不能按条目数算独立佐证 |
| 独立佐证者 `independent_corroborator` | 不同所有权、不同采编/数据来源，独立确认同一事实 | 两家独立媒体、官方统计 + 独立调查 | 才能计入独立来源族 |

**规则**：

- 同一篇新闻被 10 家媒体转载 = 1 个传播单元，不是 10 个来源。
- 10 家媒体各自独立调查同一事件 = 10 个传播者，但仍需按所有权/来源族判断独立性。
- 聚合器返回 100 条结果 ≠ 100 个独立信源。
- 新闻稿/企业 IR 是 `first_party_announcement`，不是独立佐证。
- 官方统计与二次汇编（如 Ember 对 EIA）即使数值接近，也不能自动当作两份独立证据。

### 3.3 结构性缺陷

1. **来源身份缺失**：`articles` 无 `source_id`；来源靠名称匹配，新增来源会放大不可追溯。
2. **采集层单一**：只有 FreshRSS；`official_api` 没有实现；配额未强制。
3. **正文能力不足**：`full_text_fetch=none`；官方/新闻多在 E1。
4. **事件/去重能力弱**：只有 URL/标题 72 小时；无正文相似度、通讯社/新闻稿识别、跨语言。
5. **独立佐证无法计算**：`syndication_group` 空；`multi_source_coverage=0`。
6. **结构化数据模型缺失**：observations/filings/newsletter/signal/page change 都会被强行塞进 Article 或被拒之门外。
7. **权限元数据不足**：没有字段级/内容级“可否展示、可否存储、可否再分发”。

---

## 4. 七类渠道调研结果

### 4.1 官方 API

#### 4.1.1 政府、监管、公共机构

**已核验/高价值**：

- SEC EDGAR：`data.sec.gov` 无需 key；10 请求/秒、声明 UA；提交/公司事实/全文检索/Form D；政府内容可复用，第三方附件例外。`[官方]`
- EIA：免费 key；v2 API；电力、油气、煤、排放、国际能源；数据量大、频率全；美国政府作品，第三方材料例外。`[官方]`
- BLS：注册 key；约 500 查询/日、50 series/请求；公共领域。`[官方]`
- BEA：免费 key；GDP/贸易/收入等；美国政府作品。`[官方]`
- Census：免费 key；人口、住房、企业统计；公共领域。`[官方]`
- Federal Register：无 key；1994 起；美国政府作品；API 是原型，不是官方法律版。`[官方]`
- Eurostat：免费；JSON-stat/SDMX；CC BY 4.0，带非 EU/第三方例外。`[官方]`
- World Bank：无 key；CC BY 4.0；第三方数据集例外。`[官方]`
- IMF：统计数据可商业使用但有条件；当前版权页建议商业复用先询问；批量自动化受限。`[官方/待确认]`
- OECD：多数数据允许商业使用并署名；第三方/PISA 例外。`[官方]`
- ECB：免费 API；具体再分发条款未在本次核验。`[待确认]`
- e-Stat：免费 appId；商用允许、署名；内容条款兼容 CC BY 4.0。`[官方]`
- DART：免费 key；官方披露；商业使用条款需书面确认。`[官方/待确认]`
- EDINET：免费 key；不禁止商业使用，但署名、访问限制、再分发申请；未来 IFRS 分类可能收费。`[官方]`
- KOSIS：免费 key；商用/再分发条款存在冲突；外国公司注册可能有障碍。`[官方/第三方/待确认]`
- 中国 NBS：有公开 JSON 查询接口（社区文档，2026 年变更），但没有确认到正式 API 文档/条款；商业使用 `UNKNOWN`。`[第三方/待确认]`
- PBoC / MIIT：以网页、报告、Excel 为主；未见正式 API；条款未核验。`[待确认]`
- 中国政府网英文门户：可访问；无正式 RSS/API；中文政策列表 JS 渲染。`[官方/工程判断]`
- HKEXnews：条款禁止未经许可的系统性抓取；合法再分发需 HKEX-IS 许可。`[官方]`

**适合当前系统的接入方式**：

- 统计/序列 → API/bulk → observation 表，不塞 Article。
- 申报/披露 → API/bulk → filing 表，保留 accession/CIK/期间/表单/修订。
- 政策/法规 → API/bulk → document 表，保留机构、docket、发布日期、生效日期。
- 采购 → API → opportunity/award 表，保留买方、CPV/NAICS、金额、截止日期。

#### 4.1.2 企业与产业

- 上市公司 IR：多数有 RSS/邮件提醒，但格式不统一；适合 Newsletter/页面监测，不适合作为通用 API。
- 企业公告/财报：美国 SEC、韩国 DART、日本 EDINET、英国 Companies House 是更稳定的官方入口。
- 企业开发者平台：GitHub、OpenAI、NVIDIA 等有官方 blog/RSS；适合 C 通道与开发者信号，但不构成财务证据。
- 行业协会/标准组织：OICA、ACEA、IFR、SIA、SEMI、ISO/IEC、IEEE 等。多数统计收费或限制商业使用；免费新闻稿只能作线索。`[官方/第三方]`

#### 4.1.3 新闻机构及聚合服务

- GDELT：免费、无 key、65 语言、DOC 最近 3 个月、历史 2017+；官方未给固定配额，实践约 1 请求/5 秒、单次最多 250 条；上游来源权利仍需核对。`[官方/第三方]`
- Event Registry / NewsAPI.ai：15 万+ 来源、60+ 语言、2014+ 历史、事件聚类；免费 2,000 tokens，商业需付费；禁止再分发/竞品聚合。`[官方/第三方]`
- NewsAPI：免费 100 请求/日、24 小时延迟、1 个月历史、仅开发环境；Business $449/月；无全文。`[官方]`
- GNews：免费 100 请求/日、12 小时延迟、30 天历史、非商业；Essential €49.99/月。`[官方/第三方]`
- Mediastack：免费 100 调用/月、非商业；Standard $24.99/月。`[官方]`
- Currents API：免费 250 请求/日、30 天历史、300 字符预览；Builder $69/月；商业再分发/AI 摘要需额外条款。`[官方/第三方]`
- NewsData.io：免费 200 credits/日、12 小时延迟、48 小时历史；商业使用未明确授权。`[官方/第三方]`

**判断**：新闻聚合服务适合“发现/补全”，不适合作为事实证据；GDELT 是当前最优的免费发现层。付费新闻 API 只有在 GDELT 覆盖不足且预算明确时才考虑。

#### 4.1.4 金融与产业数据商

- Bloomberg：1.5M+ 经济序列、1,000+ 新闻源、151 个分社、350+ BI 分析师；终端/数据许可，企业报价。`[官方/第三方]`
- LSEG Workspace：Reuters 2,500+ 记者、10,000+ 新闻源、Datastream 120 年、50M 工具、175 国、27M 私营公司；企业报价。`[官方/第三方]`
- FactSet：800+ 数据源、1,100+ 数据集、StreetAccount、Open:FactSet Marketplace；企业报价。`[官方/第三方]`
- S&P Capital IQ Pro：64M 私营公司、10,700+ 新闻源、5,550+ 电话会、Key Developments；企业报价。`[官方/第三方]`
- PitchBook：12.75M 公司、3M 交易、600k 投资者、170k 基金；订阅。`[官方/第三方]`
- Crunchbase：API 定制报价；标准 API 仅内部研究，禁止再分发；免费 Basic API 已停止。`[官方]`
- CB Insights：12M+ 公司、1,600+ 市场、1,700+ 来源、Mosaic/Exit Probability；订阅/API。`[官方/第三方]`
- AlphaSense：5 亿+ 文档、90,000+ 新闻源、1,500+ 券商研究、240,000+ 专家访谈；企业报价。`[官方/第三方]`

**判断**：这些不是“第一批数据源”，而是“需要时购买的许可内容”。当前阶段不应以终端平替为目标。

### 4.2 RSS / Atom

#### 4.2.1 当前实际

- 15 个启用来源、12 族；47 行登记、32 行未批准。
- HN Ask/Show 50 篇（39.7%）；HN + OpenAI 社区 + 四个工程论坛 82 篇（65.1%）；BBC/NYT 32 篇（25.4%）；BEA/Fed/ONS/NVIDIA 12 篇（9.5%）。
- 地理：美国、英国、全球平台；中国 0、欧洲非英国 0、亚洲其他 0。
- 证据：`full_text_fetch` 全 `none`；新闻/官方多为 E1；E2 仅来自声明 `full_text` 的论坛。
- 去重：URL/标题 72 小时；`syndication_group` 空；`multi_source_coverage=0`。

#### 4.2.2 如何提升 RSS 质量

1. **收窄角色**：RSS 只做“已批准发布者的通知层”，不承担发现、历史、结构化数据。
2. **来源绑定**：文章必须写 `source_id`、`feed_id`、`connector_id`、`external_id`。
3. **Feed 健康**：记录每次抓取状态、条目数、最近发布时间、结构变化；空 feed 不能当作“没有信号”。
4. **Atom/JSON Feed**：登记表已允许 `atom`；优先使用官方 Atom/JSON Feed；没有映射时才考虑直接解析。
5. **正文策略**：正文抓取默认关闭；只有条款允许、人工复核的来源才开 `article_page`；不得把摘要当全文。
6. **来源族**：按机构/所有权/联合发布组计数；同一机构多栏目算一族；转载/通讯社稿算一个单元。
7. **去重**：URL canonicalization + 标题 + 正文 shingle/MinHash + 通讯社标记 + `syndication_group`；不确定保持独立。
8. **不建议**：Google News RSS 商业使用；用 RSSHub 绕过无 Feed 站点的条款；用 RSS 数量作为覆盖指标。

#### 4.2.3 现有 RSS 来源的判断

- 保留：HN/OpenAI 社区/工程论坛用于 B/C 早期信号；BBC/NYT 用于 A 通道二手报道；BEA/Fed/ONS 保留作为发布提醒，但结构化数据应改走 API。
- 补充：企业 IR、行业协会、监管机构、智库/垂直媒体（通过 RSS/Atom/Newsletter/页面监测）。
- 不建议：继续增加同类新闻 RSS；转载/同质化会放大 L5 噪声。

### 4.3 Newsletter / 邮件订阅

#### 4.3.1 可行性

Newsletter 是 RSS 之外最现实的专业信息渠道，尤其适合：

- 政府/监管：BLS、BEA、Fed、SEC、Federal Register、GOV.UK 的发布提醒。
- 企业 IR：财报、电话会、新闻稿提醒。
- 行业协会：SIA、SEMI、ACEA、IFR 等月报/公告。
- 智库/研究机构：Brookings、CSIS、Bruegel、Rhodium、MERICS 等。
- 垂直媒体：能源、汽车、半导体、AI、工业软件等。

#### 4.3.2 技术方案

- 专用邮箱 + IMAP（`imaplib` + `email` 标准库）；不要用个人主邮箱。
- MIME/HTML/纯文本解析；附件元数据与哈希；HTML 清理；去除 tracking pixel/remote content。
- 线程识别：`Message-ID`、`In-Reply-To`、`References`；主题规范化。
- 去重：`.eml` 内容哈希 + 正文 shingle + 链接 canonicalization。
- 身份认证：SPF/DKIM/DMARC 检查；发件人域名与登记来源匹配；异常发件人隔离。
- 安全：钓鱼/恶意附件/远程图片/账号泄露；专用邮箱、最小权限、应用专用密码、附件不自动执行。
- 存储：原始 `.eml` 哈希 + 解析文本 + 链接 + 附件元数据；正文留存按来源条款。

**工具**：标准库足够；`mail-parser`（Apache-2.0）可选处理 MIME 边界；`dnspython`/`checkdmarc` 可选做认证检查；不引入邮件 SaaS。

#### 4.3.3 权利边界

必须逐项区分：

| 行为 | 不能默认 |
|---|---|
| 用户订阅 | 不等于允许自动化读取 |
| 自动化读取 | 不等于允许长期存储 |
| 本地存储 | 不等于允许分析/AI 处理 |
| 分析处理 | 不等于允许向订阅用户展示 |
| 摘要展示 | 不等于允许原文/附件再分发 |
| 原文再分发 | 通常需要单独授权 |

**判断**：Newsletter 可作为第三阶段试点；先做“用户自有订阅 + 专用邮箱 + 仅本地分析”，不做对外展示/再分发；每个 sender 单独登记权利状态。

### 4.4 页面变更监测

#### 4.4.1 适用对象

- 政府政策发布页（中国 gov.cn、NBS、部委）。
- 监管公告页（无 API 的机构）。
- 上市公司 IR/新闻室。
- 企业新闻稿页。
- 行业协会/标准组织公告。
- 专利/招投标公开页面。

#### 4.4.2 技术方案

- 优先官方 RSS/Atom/JSON/API/sitemap；没有才做页面监测。
- HTTP 条件请求：`ETag`、`Last-Modified`、`If-None-Match`、`If-Modified-Since`。
- 页面发现：sitemap、列表页链接模式、JSON-LD、结构化元数据。
- 变更检测：规范化可见文本哈希；selector/XPath 提取；忽略时间戳/广告/导航；保留 raw HTML + normalized text + diff。
- 结构变化：`min_links`、空结果、selector 失效 → 报结构变化，不把“0 条”当“无更新”。
- JS 渲染：默认不做；只有条款允许且无替代入口时才考虑 Playwright；成本/维护高。
- 频率：按页面声明的最小间隔；默认 6 小时以上；遵守 robots 和 429。
- 工具：`changedetection.io`（Apache-2.0）可作参考/独立服务；`RSS-Bridge`（Unlicense，PHP）只作模式参考；自建标准库条件请求 + 哈希更适合当前架构。

#### 4.4.3 合规与维护

- robots.txt 只是访问规则，不是版权/商业使用许可。
- 401/403/429 停止；不绕过登录/付费墙/验证码；不使用未授权 Cookie。
- 没有明确存储/展示授权时，只保留链接、标题、哈希、发现时间。
- 页面结构变化是常态；每站点需要 selector/规则维护；优先级低于 API，高于“无来源”。

**判断**：页面监测是中国政策/IR/协会的关键补充，但维护成本高；只对少量高价值页面做，不做全站爬取。

### 4.5 公共数据平台与开放数据集

#### 4.5.1 范围

- 美国：data.gov（CKAN 元数据）、Census、BLS、BEA、FRED、USAspending、SEC、EIA。
- 欧盟：Eurostat、ECB、data.europa.eu、TED、EUR-Lex。
- 全球：World Bank、IMF、OECD、UN Comtrade、WTO、IMF PortWatch、IEA。
- 亚洲：NBS、e-Stat、KOSIS、DART、EDINET、各国央行/统计机构。
- 学术/非营利：OpenAlex、Crossref、arXiv、PatentsView、EPO OPS、WIPO。

#### 4.5.2 接入方式

- API：JSON/XML/SDMX/JSON-stat；适合增量同步。
- 批量下载：CSV/JSON/XML/Parquet/ZIP；适合历史回填。
- 页面/Excel：NBS、PBoC、MIIT 等；需要解析和人工核验。
- 元数据目录：data.gov/data.europa.eu 只提供目录，不提供数据本身；需追到数据集。

#### 4.5.3 数据模型

统计数据不是 Article。应存为 `observation`：

- dataset_id、provider、indicator、geography、unit、frequency、seasonality、period、value、revision、published_at、retrieved_at、source_url、license_status。
- 保留原始快照/版本；修订不覆盖历史。
- 不同来源口径不能因名称相似就合并；EIA 与 Ember、OICA 与 ACEA 不能直接拼成一条序列。

#### 4.5.4 权利

- 明确开放/可商用：Eurostat（例外）、World Bank、OECD（多数）、Ember、ENTSO-E、e-Stat、GLEIF、OpenAlex、Crossref 元数据、SEC/EIA/BLS/BEA/Census/Federal Register/USAspending。
- 有条件：FRED（无一般再分发）、IMF（商业需确认）、UN Comtrade（商业再分发受限）、WTO（待确认）、ECB（待确认）、KOSIS（条款冲突）、NBS/PBoC/MIIT（未知）。
- 付费/限制：IEA 数据集、IFR、OICA、ACEA。

**判断**：公共数据平台是补充 L0/L1 的最高性价比来源；优先 API/批量，不做页面抓取。

### 4.6 社交平台官方 API

#### 4.6.1 事实

- X API：2026 年起按量计费；自助仅最近 7 天搜索；完整历史/流式需企业；成本高、删除/保留义务。`[第三方/官方]`
- Reddit Data API：免费层非商业（约 100 查询/分钟）；商业需合同；无自助付费。`[官方/第三方]`
- YouTube Data API：默认 10,000 units/日，其中搜索 100 次/日；配额扩展需合规审计；商业使用受 API 条款约束。`[官方]`
- Bluesky/AT Protocol：公共 API 无需 key；但个人数据/GDPR/CCPA、内容权利、速率限制。`[官方/第三方]`
- Product Hunt：默认禁止商业用途，需单独联系；GraphQL 复杂度/速率限制。`[官方]`

#### 4.6.2 价值与限制

- 价值：官方机构账号、企业账号、专家账号、开发者社区、产品发布、用户痛点。
- 限制：噪声、机器人、转发/引用重复、删除/编辑、地域/账号限制、展示/存储限制。
- 规则：社交内容只能作为 `social_signal` / discovery；必须回溯到原始公告、正式文件、企业披露或独立来源；不能直接作为事实证据。

**判断**：暂缓。等 event/entity/evidence 管线成熟、且明确需要早期信号时再评估；优先 Bluesky/官方账号，X/Reddit 成本高。

### 4.7 商业授权内容源

#### 4.7.1 类别与代表

- 新闻全文/通讯社：Bloomberg、LSEG/Reuters、FactSet/StreetAccount、RavenPack、Dataminr、NewsAPI、Event Registry。
- 金融市场数据：Bloomberg、LSEG、FactSet、S&P。
- 企业与行业数据库：S&P Capital IQ、PitchBook、Crunchbase、CB Insights、Quid。
- 电话会/专家访谈：AlphaSense/Tegus。
- 专利/技术/竞争情报：Clarivate、Lens.org、PatSnap 等（本次未逐一核查）。
- 研究报告/行业数据：IEA、IFR、OICA、Gartner/IDC 等。

#### 4.7.2 权利与成本

- 多数许可区分：内部研究、内部报告、客户展示、再分发/OEM。
- 大多数禁止把原始内容/数据再分发给第三方；部分允许衍生数据/聚合分析。
- 价格多为企业报价；公开价格极少（Feedly MI 约 $19.2k–$28.8k/年；OICA €7.5k–€35k/年；NewsAPI $449/月；Event Registry $90–$3,000/月）。
- 最低采购成本、合同期、地域、审计条款需商务确认。

**判断**：暂不作为第一批。只有在免费/官方层证明存在不可替代缺口（如私募交易、电话会、全文历史）且单位经济成立时才采购。

---

## 5. 候选 API 与服务对比

### 5.1 首批 10 个 `PRIORITY_1`

| # | 来源 | 补什么缺口 | 获取/成本 | 权利判断 | 角色 | 首批 |
|---|---|---|---|---|---|---|
| 1 | GDELT | 全球/多语言事件发现；RSS 外线索 | 免费、无 key；约 1 请求/5 秒、250 条/次 | 数据可商用需署名；上游文章权利另核；**只做发现** | 聚合器 | 是 |
| 2 | FRED | 美国宏观序列、修订 | 免费 key；无公开数值配额 | 无一般再分发权；第三方序列受限 | 汇编 | 是 |
| 3 | BLS | 就业、通胀、工资 | 免费 key；约 500 查询/日 | 公共领域；署名 | 原始 | 是 |
| 4 | Eurostat | 欧盟宏观/结构数据 | 免费；JSON-stat/SDMX | CC BY 4.0，非 EU/第三方例外 | 原始 | 是 |
| 5 | Federal Register | 美国法规/公告/征求意见 | 免费、无 key | 美国政府作品；API 非官方法律版 | 原始 | 是 |
| 6 | GOV.UK | 英国政策/法规/公告 | 免费、无 key | OGL v3；页面级适用性需核 | 原始 | 是 |
| 7 | SEC EDGAR | 美国企业申报、财报、Form D | 免费；10 请求/秒、UA | 政府内容可复用；第三方附件例外 | 原始 | 是 |
| 8 | Companies House | 英国公司登记/高管/申报 | 免费 key；600 请求/5 分钟 | 公共登记按法定条款，不等同 OGL | 原始 | 是 |
| 9 | GLEIF | LEI/母公司/实体解析 | 免费、CC0 | 可商用、无署名要求 | 原始 | 是 |
| 10 | TED | 欧盟招标/采购 | 免费搜索 API | EU 复用决定，署名；批量限制 | 原始 | 是 |

### 5.2 互补关系

- **GDELT** 负责“发现哪里有事”，不负责“事实是什么”。
- **FRED/BLS/Eurostat** 负责“宏观数字与修订”。
- **Federal Register/GOV.UK** 负责“政策原文与生效时间”。
- **SEC/Companies House** 负责“企业自己披露了什么”。
- **GLEIF** 负责“这家公司是谁、和谁有关系”。
- **TED** 负责“谁在采购、预算/合同信号”。

它们不是同类替代，而是发现 → 一手 → 实体 → 采购的互补链。

### 5.3 第二批 `PRIORITY_2`（19 个）

| 来源 | 缺口 | 成本/权利 | 备注 |
|---|---|---|---|
| e-Stat | 日本统计 | 免费 key；商用允许、署名 | 亚洲补充 |
| DART | 韩国披露 | 免费 key；商业待确认 | 韩国企业 |
| EDINET | 日本披露 | 免费 key；商业有条件 | 日本企业 |
| NBS China | 中国统计 | 免费；条款 UNKNOWN | 观察/内部研究 |
| gov.cn English | 中国政策 | 免费；条款 UNKNOWN | 页面监测 |
| World Bank | 全球发展数据 | CC BY 4.0 | 汇编，注意独立性 |
| IMF | 全球宏观 | 免费；商业待确认 | 批量自动化受限 |
| OECD | 全球宏观/结构 | 多数可商用、署名 | 第三方例外 |
| OpenAlex | 论文/机构 | CC0 | 研究信号 |
| Crossref | 论文元数据 | 元数据公共领域 | 摘要版权 |
| arXiv | 预印本 | 免费；商业需审条款 | 研究信号 |
| Ember | 全球电力 | CC BY 4.0 | 二次汇编 |
| ENTSO-E | 欧洲电网 | CC BY 4.0；400 req/min | 一手电网 |
| UN Comtrade | 贸易 | 免费 500/日；商业再分发受限 | 内部研究优先 |
| WTO | 贸易 | 免费 key；条款待确认 | 官方贸易 |
| USAspending | 美国支出/合同 | 公共领域；D&B 例外 | 采购信号 |
| Event Registry | 新闻事件聚类/历史 | 免费试用；商业付费 | 发现，非证据 |
| SAM.gov | 美国采购机会 | 免费 key；条款待确认 | 采购信号 |
| USAJOBS | 美国联邦招聘 | 免费 key；条款待确认 | 就业信号 |

### 5.4 延后/商业合同/不建议

| 类别 | 来源 | 结论 |
|---|---|---|
| 新闻聚合 | NewsAPI、GNews、Mediastack、Currents、NewsData | 延后；GDELT 免费发现更优；商业再分发/展示限制多 |
| 事件/新闻分析 | RavenPack、Dataminr | 延后；企业高价，当前不需要实时告警 |
| 机构终端 | Bloomberg、LSEG、FactSet、S&P Capital IQ | 延后；不复制终端 |
| 私募/交易 | PitchBook、Crunchbase、CB Insights | 延后；先用 SEC Form D/Companies House；商业库按需 |
| 电话会/专家 | AlphaSense | 延后；高价，但未来可能是差异化内容 |
| 市场情报 | Feedly MI、Quid | 延后；参考 UX/发现能力，不复制许可内容 |
| 产业协会 | OICA、ACEA、IFR、IEA | 延后；授权复杂/高价；先用官方统计 |
| 受限披露 | HKEXnews、KOSIS | 延后；条款/注册/授权未解决 |
| 社交 | X、Reddit、YouTube、Product Hunt、Bluesky | 延后；成本/非商业/个人数据 |
| 搜索 | Google News RSS、Bing Search API、Google CSE | 拒绝；个人非商业/已退役/停止新客户 |
| 自建搜索 | SearXNG、RSSHub | 不作为来源；上游条款不因软件许可而获得 |

---

## 6. 合规及数据权利矩阵

### 6.1 统一字段

每个来源在 `source-catalog.csv` 中分别记录：

`commercial_use`、`local_cache`、`long_term_storage`、`analysis_use`、`subscriber_display`、`redistribution`。

状态：

- `ALLOWED`：官方条款或明确授权支持。
- `CONDITIONAL`：允许，但受额度、用途、期限、展示条件限制。
- `PROHIBITED`：条款明确禁止。
- `UNKNOWN`：证据不足；**不得自动视为 ALLOWED**。
- `NOT_APPLICABLE`：不适用。

### 6.2 分组结论

| 来源组 | commercial_use | storage | subscriber_display | redistribution | 关键提醒 |
|---|---|---|---|---|---|
| 美国政府官方（SEC/EIA/BLS/BEA/Census/Federal Register/USAspending） | ALLOWED | ALLOWED | ALLOWED/CONDITIONAL | ALLOWED/CONDITIONAL | 第三方材料、D&B 数据、商标例外 |
| 英国政府（GOV.UK） | ALLOWED | ALLOWED | CONDITIONAL | CONDITIONAL | OGL v3 页面级适用性 |
| 英国登记（Companies House） | CONDITIONAL | ALLOWED | CONDITIONAL | CONDITIONAL | 公共登记≠OGL |
| 欧盟统计/能源（Eurostat/Ember/ENTSO-E） | ALLOWED | ALLOWED | CONDITIONAL | CONDITIONAL | CC BY 4.0；第三方/非 EU 例外 |
| 全球机构（World Bank/OECD） | ALLOWED | ALLOWED | CONDITIONAL | CONDITIONAL | 第三方数据集例外 |
| IMF/FRED/UN Comtrade/WTO | CONDITIONAL | CONDITIONAL | CONDITIONAL | CONDITIONAL/PROHIBITED | 再分发/商业需确认 |
| 亚洲官方（e-Stat/DART/EDINET） | CONDITIONAL/ALLOWED | CONDITIONAL | CONDITIONAL | CONDITIONAL | 署名、申请、条款差异 |
| 中国官方（NBS/PBoC/MIIT/gov.cn） | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 观察/内部研究；不作商用假设 |
| 聚合器（GDELT/Event Registry/NewsAPI） | ALLOWED/CONDITIONAL | CONDITIONAL | CONDITIONAL | CONDITIONAL/PROHIBITED | 只做发现；上游权利 |
| 社交（X/Reddit/Bluesky） | CONDITIONAL | CONDITIONAL | CONDITIONAL | PROHIBITED | 个人数据/删除义务 |
| 商业终端/私营数据 | CONDITIONAL | CONDITIONAL | CONDITIONAL | PROHIBITED | 合同决定 |
| 产业协会（OICA/ACEA/IFR） | CONDITIONAL | CONDITIONAL | CONDITIONAL | PROHIBITED | 商业许可/书面同意 |

### 6.3 `UNKNOWN` 与待确认

- 中国 NBS/PBoC/MIIT/gov.cn 条款。
- KOSIS 商用/再分发冲突。
- HKEXnews 系统性抓取/再分发。
- IMF PortWatch 特定许可。
- ACEA 复制/商业展示。
- JODI 条款（未在本次核验）。
- WTO API 条款。
- ECB 再分发。
- IMF 商业复用（需书面确认）。
- Currents/NewsData 商业再分发。
- Brave 存储/训练限制。
- X/Reddit 企业合同细节。
- Crunchbase/PitchBook/CB Insights 报价与展示权。

**处理规则**：`UNKNOWN` 来源只能进入研究储备/内部观察，不得进入“可直接商用上线”清单；上线前必须有书面条款或法务/商务确认。

### 6.4 来源角色与证据角色

`source-catalog.csv` 增加了两个字段：

- `source_role`：`original_publisher` / `transmitter` / `aggregator` / `independent_corroborator` / `first_party_announcement` / `mixed` / `unknown`。
- `evidence_role`：`discovery` / `primary_evidence` / `secondary_evidence` / `entity_reference` / `context` / `procurement_signal` / `jobs_signal` / `research_signal` / `industry_signal` / `compliance_signal` / `social_signal` / `not_evidence`。

**硬规则**：

1. `aggregator` 只能进 `discovery`，不能直接生成 evidence/claim。
2. `first_party_announcement` 只能证明“该机构这样说过”，不是独立事实核验。
3. `transmitter` 是二手报道；是否独立取决于来源族/所有权/采编。
4. `primary_evidence` 必须能回到原始发布者的文档/数据。
5. 同一事实的多个 `transmitter` 条目，只有在来源族独立时才计为多源。
6. 转载/联合发布写入 `syndication_group`；没有证据留空；未知保持 `unknown`。

### 6.5 留存/删除/展示

- 每个来源记录 `retention_limit`、`regional_restrictions`、`attribution_required`。
- 社交/新闻/Newsletter 需要删除/撤回/同步更新义务；不能只追加不删除。
- 订阅展示分级：标题/摘要/链接/结构化字段/原文，分别授权。
- 衍生数据（如统计指标、事件摘要）是否可展示，需逐源确认；不能假定“衍生即自由”。

### 6.6 明确、受限与未知来源清单

**明确可商用（仍需逐源署名/第三方例外）**：

- SEC EDGAR、EIA、BLS、BEA、Census、Federal Register、USAspending（D&B 收件人数据例外）。
- GLEIF（CC0）、OpenAlex（CC0）、Crossref 元数据（摘要除外）。
- Eurostat（CC BY 4.0，非 EU/第三方例外）。
- World Bank（CC BY 4.0，第三方数据集例外）。
- OECD（多数数据，第三方/PISA 例外）。
- Ember、ENTSO-E（CC BY 4.0）。
- e-Stat（商用允许、署名）。
- GDELT（数据可商用、需署名；上游文章权利另核，且只做发现）。

**有条件/受限**：

- FRED：无一般再分发权；第三方序列可能受限。
- IMF：统计数据商业使用有条件，当前版权页建议先询问；批量自动化受限。
- Companies House：公共登记按法定条款，不等同 OGL；个人数据/第三方版权。
- DART、EDINET：免费，但展示/再分发/申请条件需确认。
- UN Comtrade：商业再分发原数据受限；衍生数据另议。
- WTO、ECB：免费但条款/再分发待确认。
- Event Registry、NewsAPI、GNews、Mediastack、Currents、NewsData：商业使用需付费/额外条款；禁止再分发/竞品聚合。
- X、Reddit、YouTube、Bluesky、Product Hunt：商业/存储/展示/删除义务。
- Newsletter：订阅≠自动化/分析/展示/再分发。
- PatentsView、EPO OPS：免费额度/公平使用；展示/再分发需确认。
- OpenSanctions：免费层非商业；商业需许可。

**未知/待确认（不得商用上线）**：

- 中国 NBS、PBoC、MIIT、gov.cn。
- KOSIS。
- HKEXnews。
- IMF PortWatch。
- ACEA。
- JODI。
- Currents/NewsData 的商业再分发。
- Brave/X/Reddit 的商业合同细节。
- Crunchbase/PitchBook/CB Insights 的展示/再分发/报价。

**禁止/不建议**：

- Google News RSS：个人、非商业 Feed Reader 使用；不得作为商业数据源。
- Bing Search API：2025-08-11 已退役。
- Google CSE：停止新客户，2027-01-01 停止服务。
- HKEXnews 未授权系统性抓取。
- OICA/IFR/IEA 商业使用未获许可。
- Product Hunt 默认商业用途需批准。
- Media Cloud 商业工具用途。
- Crunchbase 标准 API 再分发。

---

## 7. 成熟工具和框架对比

完整 26 项见 [source-tools-comparison.csv](source-tools-comparison.csv)。原则：

1. **标准库优先**：当前运行期只依赖 Python 标准库；新增依赖需证明必要性。
2. **小依赖优先**：BSD/MIT/Apache-2.0；避免 AGPL/重型框架进入核心。
3. **不引入新基础设施**：不默认引入 Airflow/Prefect/Kafka/Redis/向量数据库/微服务。
4. **Windows 本地可维护**：避免 Linux-only 组件；Docker 仅用于隔离可选工具。
5. **许可与数据权利分开**：工具许可证不等于数据许可。

### 7.1 推荐/条件推荐

| 工具 | 用途 | 许可证 | 建议 |
|---|---|---|---|
| Python 标准库 `urllib` | HTTP/API | PSF-2.0 | `ADOPT_NOW` |
| Python 标准库 `imaplib` + `email` | Newsletter | PSF-2.0 | Newsletter 获批后 `ADOPT_NOW` |
| Python 标准库 `csv/json/xml/sqlite3` | 解析/存储 | PSF-2.0 | `ADOPT_NOW` |
| SQLite FTS5 | 全文检索 | Public domain | `ADOPT_NOW` |
| `feedparser` | RSS/Atom 解析 | BSD-2-Clause | `CONDITIONAL`；FreshRSS 已覆盖则不引入 |
| `trafilatura` | 正文提取 | Apache-2.0 (v1.8+) | `CONDITIONAL`；页面监测用 |
| `mail-parser` | MIME 边界 | Apache-2.0 | `CONDITIONAL` |
| `datasketch` | MinHash/LSH | MIT | `CONDITIONAL`；语料增大后 |
| `rapidfuzz` | 实体/标题匹配 | MIT | `CONDITIONAL` |
| `pypdf` / `pdfplumber` | PDF | BSD-3/MIT | `CONDITIONAL`；仅必要时 |
| `openpyxl` | XLSX | MIT | `CONDITIONAL` |
| `OpenSanctions yente` | 制裁实体匹配 | MIT（代码） | `CONDITIONAL`；数据另授权 |

### 7.2 不推荐现在引入

| 工具 | 原因 |
|---|---|
| changedetection.io | 成熟但完整应用+Docker/Playwright；作为参考，不作为核心 |
| RSS-Bridge | PHP 栈；只作模式参考 |
| Playwright | 默认不上 JS；只在条款允许的特定页面 |
| APScheduler | Windows 计划任务已足够 |
| Scrapy | 重型爬虫框架；合规风险高 |
| newspaper3k | 维护风险；用 trafilatura/定向抽取 |
| SearXNG / RSSHub | 软件许可不授予上游数据权；不作为生产来源 |
| Airflow/Prefect/Dagster | 本地 SQLite 系统不需要 |
| Kafka/Redis/向量数据库/微服务 | 当前规模不需要；增加运维负担 |
| PyArrow | 只有 Parquet/大规模时 |
| requests/httpx | 标准库足够；除非需要复杂认证/异步 |

### 7.3 语言选择

- **Python**：与现有代码、Windows、SQLite、标准库一致；首选。
- **Rust**：仅在需要高性能解析/去重时考虑；当前规模不需要。
- **TypeScript**：只在页面监测/前端工具链需要时考虑；不作为核心采集语言。
- **PHP**：RSS-Bridge 只作参考，不引入运行栈。

### 7.4 调度

- 复用 Windows 计划任务 + `run-digest.ps1` 的启动器模式；每个 adapter 有独立 CLI 入口、运行 ID、退出码。
- 不用 Airflow/Prefect；不做常驻队列。
- 对高频发现（GDELT）和低频官方统计分别设置节奏；失败写运行记录，不阻塞其他 adapter。

---

## 8. 竞品能力分析

| 产品 | 主要用户/场景 | 信息源/能力 | 事件/实体/验证 | 价格/授权 | 可学习 | 不照搬 |
|---|---|---|---|---|---|---|
| AlphaSense | 投资/企业研究 | 5 亿+ 文档、90k 新闻、1,500+ 券商研究、240k+ 专家访谈 | 语义搜索、引用定位；不保证独立佐证 | 企业报价，约 $10k–$40k/用户/年（第三方估计） | 引用到句、内容覆盖、工作流 | 高价许可内容/专家访谈 |
| Bloomberg Terminal | 金融/交易 | 1.5M+ 经济序列、1,000+ 新闻源、151 分社、350+ BI 分析师 | 实时数据、事件日历、分析 | 终端/数据许可，企业报价 | 数据整合、事件日历、分析深度 | 终端/交易功能 |
| LSEG Workspace | 投行/资管 | Reuters 2,500+ 记者、10k+ 新闻源、Datastream 120 年、50M 工具、175 国、27M 私营公司 | 实时新闻、估值、组合分析 | 企业报价 | 全球覆盖、数据字典 | 全量终端 |
| FactSet | 投研/量化 | 800+ 数据源、1,100+ 数据集、StreetAccount、Open:FactSet | 筛选、提醒、组合分析 | 企业报价 | 数据 marketplace/API | 重型终端 |
| S&P Capital IQ Pro | 投行/私募/企业 | 64M 私营公司、10,700+ 新闻源、5,550+ 电话会、Key Developments | 公司/交易/人物图谱 | 企业报价 | 私营公司 schema、事件类型 | 全量数据库 |
| PitchBook | 私募/VC | 12.75M 公司、3M 交易、600k 投资者、170k 基金 | 交易/融资/估值 | 订阅 | 私募市场数据模型 | 全量交易库 |
| Crunchbase | 销售/VC/企业 | 公司/融资/联系人 | 公司搜索/提醒 | API 定制报价；内部研究，禁止再分发 | 公司/融资字段 | 许可数据再分发 |
| CB Insights | 企业战略/VC | 12M+ 公司、1,600+ 市场、1,700+ 来源、Mosaic/Exit Probability | 市场图谱、信号评分 | 订阅/API | 早期信号/市场地图 | 预测分数当事实 |
| Quid | 消费/市场情报 | 580k+ 新闻源、2M+ 博客、85+ 评论站、Crunchbase/Capital IQ、Clarivate 专利；2PB 数据 | 社交/媒体/消费者分析 | 企业报价 | 多模态/主题聚类 | 2PB 许可数据 |
| Feedly MI | 企业市场情报 | 厂商称 40M+ 来源、15 语言、AI Feed/趋势 | 主题跟踪、AI 摘要 | 约 $19.2k–$28.8k/年 | 信息分流/UX | 来源许可/大规模聚合 |
| GDELT | 研究/媒体/发现 | 65 语言、3 个月滚动、2017+ 历史 | 事件/文章/时间线 | 免费，署名 | 全球发现层 | 当作事实证据 |
| Google News | 大众/发现 | 聚合新闻 | 无事件/实体 API | 个人非商业 RSS | 覆盖广度 | 商业抓取/依赖 |

**差距总结**：

- 许可内容：通讯社、券商研究、电话会、专家访谈。
- 私营市场：公司/交易/投资者/估值。
- 实体图谱：LEI/母公司/所有权/人物。
- 实时发现：流式/告警/多语言。
- 结构化财务：全球公司/估值/一致预期。
- 替代数据：招聘/采购/专利/航运/社交/应用。

Opportunity-Radar 不应复制这些高成本能力；应把“可追溯、独立性、本地、低成本”做成差异。

---

## 9. 业务场景覆盖分析

### A. 企业与竞争对手动态

| 问题 | 回答 |
|---|---|
| RSS 能发现什么 | 产品发布、社区讨论、少量新闻稿/财报新闻 |
| RSS 容易遗漏什么 | 8-K/10-Q/10-K、管理层变动、资本开支、并购、工厂建设/关闭、供应商/客户变化 |
| 官方/专业来源 | SEC EDGAR、DART、EDINET、Companies House、GLEIF、公司 IR |
| 聚合服务 | GDELT 发现事件/URL；Event Registry 聚类 |
| 事实核验 | 申报原文、公司 IR、官方公告；新闻稿只证明“公司这样说” |
| 授权障碍 | HKEX、部分 IR 页面、商业数据库 |
| 低成本组合 | GDELT + SEC EDGAR/Companies House + GLEIF + 公司 IR RSS/页面监测 |

### B. 宏观经济与政策

| 问题 | 回答 |
|---|---|
| RSS 能发现什么 | 统计机构新闻稿标题、央行新闻稿、媒体解读 |
| RSS 容易遗漏什么 | 序列/修订/季调/单位、政策原文、征求意见、关税/制裁细节 |
| 官方/专业来源 | FRED/BLS/BEA/Census/Eurostat/World Bank/IMF/OECD/ECB、Federal Register/GOV.UK/EUR-Lex/TED |
| 聚合服务 | GDELT 发现政策新闻；Event Registry 追踪 |
| 事实核验 | 官方统计/法规原文；媒体只作解释 |
| 授权障碍 | IMF/UN Comtrade/WTO/ECB 再分发；中国官方条款 |
| 低成本组合 | FRED/BLS/Eurostat + Federal Register/GOV.UK + GDELT |

### C. 科技与产业

| 问题 | 回答 |
|---|---|
| RSS 能发现什么 | HN/OpenAI/工程论坛、少量科技新闻、NVIDIA 新闻稿 |
| RSS 容易遗漏什么 | 半导体销售/资本开支、汽车产销、机器人安装、能源/电网、专利/论文、数据中心电力 |
| 官方/专业来源 | SEC/DART/EDINET、EIA/Ember/ENTSO-E、SIA、OICA/ACEA/IFR、PatentsView/EPO、OpenAlex/Crossref/arXiv |
| 聚合服务 | GDELT 发现产业新闻；Event Registry 聚类 |
| 事实核验 | 公司申报/官方统计/专利原文；协会数据注意口径 |
| 授权障碍 | OICA/IFR/IEA 付费；ACEA 需同意；HKEX 受限 |
| 低成本组合 | SEC + EIA/Ember/ENTSO-E + OpenAlex/Crossref/arXiv + GDELT；产业协会按需 |

### D. 市场与资本

| 问题 | 回答 |
|---|---|
| RSS 能发现什么 | 融资/IPO/并购新闻、少量公司公告 |
| RSS 容易遗漏什么 | Form D、S-1、交易结构、投资者、估值、私募/VC 数据 |
| 官方/专业来源 | SEC Form D/S-1、Companies House、PitchBook/Crunchbase/CB Insights（付费） |
| 聚合服务 | GDELT/Event Registry 发现交易新闻 |
| 事实核验 | SEC 申报/公司公告；商业数据库交叉核对 |
| 授权障碍 | Crunchbase/PitchBook 内部使用/再分发限制；报价不公开 |
| 低成本组合 | SEC Form D + Companies House + GDELT；付费库按需 |

---

## 10. 架构方案比较

### 10.1 三种方案

| 维度 | A 渐进式扩展 | B 统一采集框架 | C 混合式 |
|---|---|---|---|
| 做法 | 复用 FreshRSS/SQLite/计划任务，逐个加脚本 | 建统一 source registry/adapter contract/运行记录/标准化接口 | RSS 保持 FreshRSS；官方/结构化、发现、Newsletter/页面监测各自 adapter；在 event/evidence 层统一 |
| 开发成本 | 低 | 中高 | 中 |
| 维护成本 | 随脚本增多失控 | 中高（框架本身要维护） | 中 |
| 可扩展性 | 低 | 高 | 高 |
| 运行复杂度 | 低 | 高 | 中 |
| 现有兼容 | 高 | 中 | 高 |
| 数据隔离 | 弱（脚本容易越界） | 强（但需设计） | 强 |
| 合规控制 | 弱 | 强 | 强 |
| 推荐 | 仅作过渡 | 不推荐现在 | **推荐** |

### 10.2 推荐：方案 C 混合式

核心原则：

1. **来源层统一描述**：`source_id`、`source_role`、`source_family`、`access_method`、`terms_url`、`license_status`、`retention`、`credential_ref`。
2. **采集层分类 adapter**：RSS、API、Email、Page monitor、Dataset、Social、Licensed feed。每个 adapter 只解决一种获取方式。
3. **原始记录层**：source_id、external_id、URL、retrieved_at、published_at、content_hash、raw_snapshot、connector、version、rights snapshot。
4. **标准化层**：Article、Observation、Filing、NewsletterItem、Signal、PageChange、DiscoveryCandidate；不要强行都变成 Article。
5. **事件/证据层**：Event、Evidence、Claim、Entity、Source lineage；原始发布者 vs 二次报道分开。
6. **生产/影子隔离**：SEC/EIA 独立库不变；新官方来源独立库/命名空间；影子 Claim 不进入生产。
7. **权限与留存**：来源级/字段级/内容级 rights；订阅展示分级；删除/撤回义务。

### 10.3 数据流

```
[已批准 RSS] FreshRSS -> cli -> analyses -> R1 events/evidences/claims -> 日报/门禁

[官方/结构化 API] adapter -> raw_snapshots -> normalized records
    -> observations / filings / policy docs / procurement
    -> evidence/claim（经批准，暂不自动进日报）

[发现层] GDELT/Event Registry -> discovery_candidates
    -> URL/domain/title/date/language/query
    -> 原始来源已批准? -> 进入对应 adapter；否则只记录

[Newsletter] dedicated mailbox -> IMAP -> .eml hash + text + links
    -> newsletter_items（按 sender 权利分级）

[页面监测] approved pages -> conditional GET -> normalized hash/diff
    -> page_changes（默认只存链接/标题/hash）

[SEC/EIA] 现有独立入口 -> 独立库 -> 同库 R1 表
    -> 跨库仅 candidate link；不进 RSS/LLM/日报
```

### 10.4 明确不做

- 不把 GDELT/Event Registry 当 evidence 表。
- 不把 SEC/EIA 合并进 RSS 库。
- 不把统计 observation 塞进 Article。
- 不把 Newsletter 当 Article 直接进日报。
- 不默认上 Playwright/浏览器自动化。
- 不引入 Airflow/Kafka/Redis/向量数据库/微服务。
- 不在未获 G5/G6 前改变生产行为。

---

## 11. 推荐来源清单

### 11.1 10 个优先来源及互补关系

| 顺序 | 来源 | 角色 | 补什么 | 成本层 | 前置条件 |
|---|---|---|---|---|---|
| 1 | GDELT | 发现 | 全球/多语言事件与 URL | 低成本直接 | 只做 discovery；观察配额；上游权利 |
| 2 | FRED | 汇编 | 美国宏观序列/修订 | 低成本直接 | 系列级 provenance；再分发限制 |
| 3 | BLS | 原始 | 就业/通胀/工资 | 低成本直接 | key；署名；序列/期间 |
| 4 | Eurostat | 原始 | 欧盟宏观/结构 | 低成本直接 | CC BY 4.0 例外；dataset DOI |
| 5 | Federal Register | 原始 | 美国法规/公告 | 低成本直接 | 机构/主题过滤；非官方法律版 |
| 6 | GOV.UK | 原始 | 英国政策/法规 | 低成本直接 | OGL v3 页面级确认 |
| 7 | SEC EDGAR | 原始 | 美国企业申报/财报/Form D | 低成本直接 | 独立 SEC 通道；XBRL/期间/修订 |
| 8 | Companies House | 原始 | 英国公司登记/高管/申报 | 低成本直接 | 公共登记条款/个人数据 |
| 9 | GLEIF | 实体 | LEI/母公司/实体解析 | 低成本直接 | CC0；实体匹配规则 |
| 10 | TED | 原始 | 欧盟招标/采购 | 低成本直接 | EU 复用/署名；批量限制 |

**首批实际建议（有限资源）**：

- **第一波（5 个）**：GDELT（发现影子）、FRED、BLS、Federal Register、SEC EDGAR。
- **第二波（5 个）**：Eurostat、GOV.UK、Companies House、GLEIF、TED。

理由：第一波覆盖“发现 + 美国宏观 + 美国政策 + 美国企业披露”；第二波补“欧盟宏观/政策、英国公司、实体解析、采购”。这两波之间没有重复劳动：GDELT 只发现，FRED/BLS 给数字，Federal Register 给政策原文，SEC 给企业披露。

### 11.2 明确不进入第一批

- 新闻 API：NewsAPI、GNews、Mediastack、Currents、NewsData。
- 商业终端/私募/电话会：Bloomberg、LSEG、FactSet、S&P、PitchBook、Crunchbase、CB Insights、AlphaSense、Feedly MI、Quid。
- 产业协会：OICA、ACEA、IFR、IEA（除非有明确预算/授权）。
- 社交：X、Reddit、YouTube、Product Hunt（Bluesky 可观察）。
- 受限：HKEXnews、KOSIS、中国 NBS/PBoC/MIIT（观察/内部研究，不做商用假设）。
- 拒绝：Google News RSS、Bing Search API、Google CSE。

### 11.3 选择逻辑

不是“覆盖最广”，而是：

1. 是否能补 P0 缺口；
2. 是否有明确访问/权利边界；
3. 是否能以低维护方式持续；
4. 是否能与现有 event/evidence/entity 模型关联；
5. 是否能在有限开发时间内做出可验证结果。

---

## 12. 分阶段实施建议

完整路线见 [SOURCE_INTELLIGENCE_ROADMAP.md](SOURCE_INTELLIGENCE_ROADMAP.md)。摘要：

| 阶段 | 目标 | 输入/输出 | 验收 | 生产影响 | 审批 |
|---|---|---|---|---|---|
| 0. 治理基础 | source_id/adapter contract/rights 元数据/去重基线 | 现状登记 → 新 registry/记录 schema | 100% 文章有 source_id；审计通过；无跨库写入 | 不影响生产 | 内部 |
| 1. 发现影子 | GDELT 只写 discovery candidates | GDELT → candidates/指标 | 与 RSS 对比新增事件/域名/重复/延迟；不生成 evidence | 无 | 需数据访问评审（G5 范围） |
| 2. 一手宏观/政策 | FRED/BLS/Federal Register + Eurostat/GOV.UK | API → observations/policy docs | 样本值/期间/单位/修订一致；条款记录 | 独立库，不进日报 | G5 |
| 3. 企业/实体 | SEC EDGAR 扩展、Companies House、GLEIF、DART/EDINET | filings/registry → entity links | 实体匹配 precision/recall；申报可追溯 | SEC 独立通道 | G5 |
| 4. Newsletter/页面监测 | 专用邮箱；gov.cn/NBS/IR/协会页面 | .eml/page changes → items | 权利分级；结构变化告警；只存允许内容 | 影子/内部 | G5 + 法务确认 |
| 5. 独立性与事件关联 | 正文相似度/转载/来源族/事件关联 | 去重/lineage/event clusters | 重复率/误判独立佐证率；多文章事件 | 影响证据质量，不改门禁 | 内部 |
| 6. 商业/社交（条件） | 付费数据/社交 API | 商业合同/社交信号 | 单位经济；许可；不达标停止 | 需单独批准 | G5/G6 相关 |

**阶段纪律**：

- 每阶段独立验收；不以“为后续铺路”作为完成理由。
- 阶段 1 只做发现，不生成 claim；阶段 2/3 只做一手记录，不自动进日报。
- 任何生产 Claim 仍需 G6；新增来源准入仍需 G5。
- 失败/覆盖率不足必须可见，不能渲染成“没有信号”。

---

## 13. 风险、未知项及待确认事项

### 13.1 权利未知（必须确认）

| 来源 | 未知项 | 影响 |
|---|---|---|
| 中国 NBS/PBoC/MIIT/gov.cn | 存储、分析、商用、再分发 | 不能商用上线 |
| KOSIS | 商用/再分发条款冲突 | 不能商用上线 |
| HKEXnews | 系统性抓取/再分发许可 | 只能走 HKEX-IS |
| IMF PortWatch | 特定数据许可 | 不能假定 IMF 通用条款覆盖 |
| ACEA | 复制/商业展示同意 | 不能直接使用 |
| JODI | 条款未声明 | 不能假定允许 |
| WTO | API 条款/再分发 | 不能商用上线 |
| ECB | 再分发/展示 | 需确认 |
| IMF | 商业复用书面确认 | 需确认 |
| Currents/NewsData | 商业再分发/摘要 | 需确认 |
| Brave/X/Reddit | 存储、展示、商业 | 需确认 |
| Crunchbase/PitchBook/CB Insights | 内部/展示/再分发/报价 | 需商务确认 |

### 13.2 技术风险

- 页面结构变化、JS 渲染、反爬/429；维护成本高。
- API 版本/字段/配额变化；需要 adapter 级健康检查。
- 实体消歧：同名/母子公司/股票代码/LEI 映射。
- 跨语言/转载/翻译重复；不能自动合并。
- 统计口径/单位/季调/修订；不能直接拼序列。
- 正文抽取质量；不能把摘要当全文。
- 数据量增长后 SQLite 索引/FTS/归档策略。

### 13.3 产品风险

- 来源偏向：GDELT/新闻聚合会放大可报道事件，不等于商业价值。
- 假多源：聚合器/转载/新闻稿被误计为独立佐证。
- 成本蔓延：付费 API/商业数据订阅增加，单位经济未验证。
- 维护蔓延：页面监测/Newsletter 逐源维护，长期成本高。
- 过度建设：为了“统一”引入重型框架，违背本地优先。

### 13.4 合规风险

- 版权/数据库权利/出版商邻接权。
- 个人数据（社交、Newsletter、公司高管）。
- 跨境数据传输（中国/欧盟/美国）。
- 服务条款变更；API 弃用。
- 订阅展示/再分发/衍生数据边界。
- AI 处理限制（部分新闻 API 禁止训练/摘要）。

### 13.5 待法律/商务确认

1. 中国官方数据（NBS/PBoC/MIIT/gov.cn）的存储/分析/展示权。
2. KOSIS 商用/再分发。
3. HKEX-IS 许可成本/范围。
4. IMF/UN Comtrade/WTO/ECB 的商业展示/再分发。
5. ACEA/OICA/IFR/IEA 的许可成本与展示权。
6. Newsletter 的自动化处理/分析/展示/再分发。
7. 社交 API 的存储/展示/删除义务。
8. 商业数据商的内部使用/客户展示/OEM 条款。

---

## 14. 最终决策建议

### 14.1 建议批准的方向

1. **批准调研结论进入下一阶段设计**，但不批准生产接入。
2. **先做来源治理与接入基础**（source_id/adapter/rights/dedupe），这是所有渠道的前提。
3. **批准 GDELT 影子发现试验**（只写 candidates，不生成 evidence/claim）。
4. **批准 3–5 个一手来源的技术设计**：FRED/BLS、Federal Register、SEC EDGAR；第二批 Eurostat/GOV.UK/Companies House/GLEIF/TED。
5. **Newsletter/页面监测/社交/商业数据暂不进入第一批**；先完成权利确认与试点设计。

### 14.2 如果只有有限开发资源和预算：最值得做的三件事

1. **修来源身份与接入基础**  
   `source_id`、adapter contract、配额/熔断、权利/留存元数据、正文相似度/转载识别。没有这层，新增来源只会制造不可追溯的重复。

2. **GDELT 发现层影子运行**  
   免费、全球、多语言；只做 discovery，不生成 evidence/claim；用 2–4 周测量“RSS 之外新增了什么、重复率多少、哪些域名可用”。

3. **接 3–5 个一手来源**  
   FRED + BLS（美国宏观）、Federal Register（美国政策）、SEC EDGAR（美国企业申报）；如果还有余力，加 Eurostat + GOV.UK。它们补的是数字、政策原文、企业披露，和 GDELT 的发现能力互补。

### 14.3 明确不建议现在做

- 不买 Bloomberg/LSEG/FactSet/PitchBook/AlphaSense 等终端/商业库。
- 不接 X/Reddit/Product Hunt 等社交 API。
- 不做大规模页面爬取/浏览器自动化。
- 不把 GDELT/Event Registry 当证据。
- 不启动 R2/N0–N5 的 Batch 17，不启用 v7，不申请 G6。
- 不在没有 G5 的情况下改变生产采集/日报/门禁。

### 14.4 停止点

本报告完成调研与建议，不进入 PRD 或开发。等待用户审查来源质量、授权判断、技术选型和商业价值后，再决定第一批实际接入范围。

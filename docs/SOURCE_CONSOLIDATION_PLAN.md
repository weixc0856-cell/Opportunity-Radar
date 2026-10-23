# 信源整合方案（2026-10-23）

> **实施状态（2026-10-23）**：本方案已部分执行——`intelligence_lines` 字段、7 个已核验官方/新闻来源、
> 数据集登记、页面监测适配器与 FreshRSS 九分类均已落地。执行记录见 `docs/SOURCE_REVIEW.md` §13，
> 影子运行对比见 `docs/SHADOW_RUN_2026-10-23.md`。本文保留为设计与实测依据，未执行的部分在 §10 标注。

> **性质**：这是可审计的**规划与实测记录**，不是批准、不是配置变更。
> 本轮**没有**修改 `config/sources.csv`、`config/sources.local.csv`、任何运行代码、评分规则或证据规则，
> **没有**启用任何来源，**没有**改动 FreshRSS 订阅与分类。
> 表中 `review_required` 的来源一律保持禁用；`verified_feed` 只表示"该 URL 当前返回可解析的 RSS/Atom"。

## 0. 一句话结论

方向成立：把体系从"订阅了一堆博客"改成"官方文件与数据打底、企业披露为主体、新闻做发现、社区做补充"。
但要落地，需要先补上当前代码里**不存在**的一个维度——**情报主线**——并承认三件事实：
**六条主线不是 A/B/C 通道**；**官方来源不自动等于高证据**；**大多数官方入口没有可用的机器端点**。

## 1. 对现有建议的采纳与修正

### 1.1 采纳

- 以六条情报主线重组来源体系，CAE 从核心退到专业子信道。
- 官方一手文件与数据优先于新闻解读；新闻只做发现与背景。
- 不一次扩充几十个来源，按阶段推进，每阶段有验收门。
- 先建立可审计的来源总表，再改配置。
- 对每个来源分别登记访问方式、真实端点、许可状态，不允许"官网能打开"冒充"可以采集"。

### 1.2 必须修正的四点

| # | 建议中的说法 | 实际情况（本仓库已核实） |
|---|---|---|
| 1 | 六条主线可以直接作为产品分类 | 现有 A/B/C 是**编辑通道**（商业情报/机会/技术），由 `lanes.py` 决定；六条主线是**主题维度**，两者正交。一个来源可服务多条主线，但只能进入其声明的通道。主线目前**没有字段承载**：`topic` 与 `topic_tags` 是自由文本，不参与路由、不参与评分，也不受审计校验。 |
| 2 | "当前代码中超额条目会被降为 `filtered/source_cap`" | **不成立**。`cli.apply_source_caps()` 只把超额条目的 `distribution` 置为 `deferred`，`status`、分数、证据全部保留，并出现在附录（`cli.py:58-83`）。配额影响"这一期读不读"，不影响"值不值得读"。这条区别是刻意的，不应回退。 |
| 3 | 建议新增 `rss / api / licensed / metadata_only / manual_review` 五类访问方式 | 现有 `access_method` 的允许值是 `rss`、`atom`、`official_api`、`authorized_email_export`，且 `is_approved()` 要求 HTTPS + 已填 `freshrss_feed_id`。把 `licensed` / `manual_review` 塞进 `access_method` 会让它们永远无法通过准入判断。它们是**许可状态**与**端点状态**，应各自成字段（见 §4、§8）。 |
| 4 | 官方来源能提升情报质量 | 官方的价值是**权威性**，不是**证据等级**。证据等级由"正文是否在 feed 里"决定：实测 BEA 正文中位 472 字符、Census 106、Fed 100、BBC 113，都只能到 E1。E2 需要复核后声明 `content_access_level=full_text`，且引文可在正文定位。**加来源不会自动提高证据等级。** |

### 1.3 一条被建议低估的边界

FRED、Eurostat 是**结构化时间序列 API**，World Bank、IMF 是**出版物库**。它们不产生"文章"，也无法被当前管线消费：抓取路径只有 FreshRSS Fever API（`cli.py:302`），`official_api` 只是登记值，没有对应的抓取实现。
**把它们登记成 `sources.csv` 的一行，只会得到一条永远不产出的记录。** 结构化数据需要独立的数据集登记表与独立管线（见 §6.3）。

## 2. 现状基线（本机实测，2026-10-23）

### 2.1 FreshRSS

只读方式读取容器内 `db.sqlite` 副本，未写入。

| 项 | 实测值 |
|---|---|
| 订阅数 | **16** |
| 分类数 | **1**，名为 `Uncategorized`（建议书"全部未分类"的描述属实） |
| 条目总数 | **3,783** |
| 与登记表已映射 | 14 个（有 `freshrss_feed_id`） |
| 未被登记表映射 | 2 个：`FreshRSS releases`（id=1）、`Hacker News`（id=2；登记表有 `hackernews-front` 行但未填 feed id） |
| 本地已启用采集 | 7 个（id 3,4,5,6,7,8,9） |
| 已填 feed id 但禁用 | 7 个（id 10-16） |

逐源条目量（体现当前的"信息供给结构"）：

| id | 订阅 | 条目 | id | 订阅 | 条目 |
|---|---|---|---|---|---|
| 1 | FreshRSS releases | 12 | 9 | OpenAI Developer Community | 372 |
| 2 | Hacker News | 238 | 10 | OpenAI News | 1315 |
| 3 | Hacker News Ask | 158 | 11 | DeepMind Blog | 101 |
| 4 | Hacker News Show | 438 | 12 | Hugging Face Blog | 900 |
| 5 | SimScale Forum | 34 | 13 | GitHub Blog | 13 |
| 6 | preCICE Forum | 31 | 14 | TechCrunch AI | 57 |
| 7 | ParaView Forum | 34 | 15 | Simon Willison | 38 |
| 8 | SALOME Forum | 31 | 16 | SimScale Blog | 11 |

CAE/工程类 5 个（5,6,7,8,16）合计 141 条，占 3.7%；Hacker News 三个入口（2,3,4）合计 834 条，占 22%；AI 厂商与社区 5 个（9-12,14）合计 2,745 条，占 72.6%。
**结构问题不是"CAE 太多"，而是"AI 技术社区几乎垄断了供给，政策、宏观、企业披露为 0"。** 建议书的判断方向对，但归因需要按这个数字修正。

### 2.2 登记表

| 项 | 实测值 |
|---|---|
| 模板行数 | 31（`config/sources.csv`，全部禁用） |
| 本地行数 | 31（`config/sources.local.csv`，7 启用） |
| 主线字段 | **不存在** |
| `topic` / `topic_tags` | 存在，自由文本，只供登记与审计 |
| 有 `feed_url` 的行 | 26 行；其中 nvidia-newsroom、amd-ir 已改到实测可用地址，但 amd-ir 条目正文为空（只能 E0） |
| 无端点（`feed_url` 留空） | 5 行：nvidia-ir、imf-publications、oecd-publications、world-bank-research、sia-news |

## 3. 六条情报主线：定义与字段设计

主线回答的是**"这个来源为什么值得监测"**，通道回答的是**"这条内容该用哪种尺度评分"**。两者互不替代。

| 代码 | 主线 | 回答的问题 | 主要证据角色 | 允许的通道 |
|---|---|---|---|---|
| `POL` | 政策与监管 | 规则变了吗？谁受影响？ | 正式文件、生效日期、适用范围 | A |
| `MACRO` | 宏观经济与统计 | 经济、就业、价格、贸易、投资发生了什么？ | 统计公报、发布时间、修订记录 | A |
| `CORP` | 企业经营与资本配置 | 企业在投资什么、削减什么？ | 财报、IR 公告、监管披露 | A |
| `IND` | 产业、能源与供应链 | 哪些行业出现结构性变化？ | 产能、价格、贸易流向、产业政策 | A |
| `NEWS` | 国际新闻与调查报道 | 有什么事件值得进一步调查？哪些来源如何报道？ | 通讯社与主流媒体的发现与背景 | A |
| `TECH` | 科技、研究与商业机会 | 哪些新技术/新需求值得投入？ | 研究、专利、开源、产品发布、招标、招聘、投诉 | A / B / C |

工程与专业技术（CAE、CFD、仿真论坛）是 `TECH` 下的**子领域**，用 `topic_tags` 表达，不单设主线。

### 3.1 字段设计（建议，尚未实现）

新增一列 `intelligence_lines`，取值来自 `{POL,MACRO,CORP,IND,NEWS,TECH}` 的多选集合，与 `editorial_lanes` 同构：

- 解析复用 `lanes.editorial_lanes()` 的同款分词逻辑；
- `source_audit` 校验取值，并**不要求**启用来源必须声明主线（避免与 `editorial_lanes` 重复强制）；
- 报告附录可按主线汇总来源与条目数——这是证明"结构改善"的唯一量化手段；
- 不参与评分，不参与 `derive_lane()`。

替代方案（若不想动 schema）：把 `topic_tags` 的首个标签约束为受控词表。不建议——`topic_tags` 已经承载自由描述，混用会让"治理字段"和"备注字段"再次边界模糊。

## 4. 来源总表 schema（13 列）

与现有登记表字段的对应关系，以及本轮新增的候选表字段：

| 列 | 含义 | 现有字段 | 状态 |
|---|---|---|---|
| `source_id` | 稳定 ID | `source_id` | 已有 |
| `institution` | 机构 | `name` | 已有 |
| `region` | 国家/地区 | — | 新增 |
| `intelligence_lines` | 情报主线 | — | **新增（§3.1）** |
| `authority_type` | 官方/企业/媒体/社区/研究 | `source_type` | 已有 |
| `official_entry` | 官方入口页 | `homepage` | 已有 |
| `access_kind` | 网页 / RSS / Atom / API / 人工 | `access_method` | 已有，需扩语义（见 §4.1） |
| `real_endpoint` | 实测端点 | `feed_url` | 已有 |
| `endpoint_status` | 实测结论 | — | **新增（§8）** |
| `endpoint_checked_at` | 实测时间 | `last_verified_at` | 已有 |
| `content_basis` | 正文完整度 | `content_access_level` | 已有 |
| `update_cadence` | 更新频率 | — | 新增（观测值，非声明） |
| `license_status` | 许可状态 | `permission_status` | 已有，但语义需拆分（见 §4.1） |

### 4.1 `permission_status` 与 `access_method` 的语义拆分

现在一个 `permission_status` 同时承担"法律/条款判断"和"本地是否可用"。建议拆成三个正交字段：

- `endpoint_status`：端点是否存在且可用（实测事实）；
- `license_status`：条款是否允许自动获取、存储、摘要、再发布（人工判断，默认 `unknown`）；
- `local_approval`：是否允许在本机私测（本地决定，现有 `approved` 的实际含义）。

`is_approved()` 只应消费 `local_approval` + `endpoint_status`；`license_status=unknown` 不阻止**本机私测**，但必须阻止**对外发布**。
这一条需要改代码，本轮不做。

## 5. 第一批候选来源实测（2026-10-23）

**方法**：每个候选发起 1 次入口页 GET，解析 `<link rel="alternate" type="application/(rss|atom)+xml">` 与含 rss/feed/xml 的锚点；再对发现的端点与已知候选端点各发起 1 次 GET。UA 标明本地研究用途，单请求最多读 400KB，**不保存任何文章内容**。全部结论来自**单次采样**。原始结果见 `docs/source-probe-2026-10-23.json`，复现脚本见 `tools/probe_sources.py`。

**未做**：未核对任何条款、未登录、未绕过任何访问控制、未抓取正文页。

### 5.1 中国：政策、统计与监管

| source_id | 机构 | 入口 | 端点结论 | 可用端点 | 条目 | 正文中位 | 最新 |
|---|---|---|---|---|---|---|---|
| `cn-gov` | 中国政府网 | 200 | **无 feed** | — | — | — | — |
| `cn-stats` | 国家统计局 | 200 | **无 feed** | — | — | — | — |
| `cn-pbc` | 中国人民银行 | 200 | **可用（有保留）** | `https://www.pbc.gov.cn/goutongjiaoliu/113456/2986536/index.html` | 6 | 1519 | 2026-10-20 |
| `cn-mof` | 财政部 | 200 | **无 feed** | — | — | — | — |
| `cn-ndrc` | 国家发展改革委 | 200 | **无 feed** | — | — | — | — |
| `cn-miit` | 工业和信息化部 | 200 | **无 feed** | — | — | — | — |
| `cn-mofcom` | 商务部 | 200 | **无 feed** | — | — | — | — |
| `cn-customs` | 海关总署 | **412** | 入口被拦截 | — | — | — | — |
| `cn-nea` | 国家能源局 | 200 | **无 feed** | — | — | — | — |
| `cn-samr` | 国家市场监管总局 | 200 | **无 feed** | — | — | — | — |

PBOC 的保留：该地址 `Content-Type` 返回 `text/html`，实际内容是 RSS；编码为 GBK；只返回 6 条。**这是"能解析"不等于"是实现规范的 Feed"的典型样本**，启用前需连续采样确认稳定性。

### 5.2 国际宏观经济与官方数据

| source_id | 机构 | 入口 | 端点结论 | 可用端点 | 条目 | 正文中位 | 最新 |
|---|---|---|---|---|---|---|---|
| `us-bea` | BEA | 200 | 可用 | `https://www.bea.gov/news/rss` | 10 | 472 | 2026-09-30 |
| `us-bls` | BLS | 200 | 可用（两条互补） | `https://www.bls.gov/feed/bls_latest.rss` | 1 | 685 | 2026-10-20 |
| | | | | `https://www.bls.gov/feed/wkyeng.rss` | 12 | 253 | 2026-10-21 |
| `us-census` | Census Bureau | 200 | 可用 | `https://www.census.gov/newsroom/press-releases.xml` | 10 | **106** | 2026-09-30 |
| `us-fed` | Federal Reserve | 200 | 可用 | `https://www.federalreserve.gov/feeds/press_all.xml` | 20 | **100** | 2026-10-07 |
| `uk-ons` | UK ONS | 200 | 可用 | `https://www.ons.gov.uk/releasecalendar?rss` | 10 | 168 | 2026-10-21 |
| `fred` | FRED | 200 | **无 feed**（只有 API） | — | — | — | — |
| `eurostat` | Eurostat | 200 | **无 feed**（只有 API） | — | — | — | — |
| `imf` | IMF | **403** | 入口被拦截 | — | — | — | — |
| `worldbank` | World Bank | 200（重定向至 `/ext/research-publications`） | **无 feed** | — | — | — | — |
| `oecd` | OECD | **403** | 入口被拦截 | — | — | — | — |

注意：`bls_latest.rss` 只有 1 条——它是"最新发布"提示，不是归档。要监测发布节奏就登记它，要读内容要登记 `wkyeng.rss`。

### 5.3 国际新闻媒体

| source_id | 机构 | 入口 | 端点结论 | 可用端点 | 条目 | 正文中位 | 最新 |
|---|---|---|---|---|---|---|---|
| `reuters` | Reuters | **401** | 无匿名访问 | — | — | — | — |
| `ap` | AP | **403** | 无匿名访问 | — | — | — | — |
| `afp` | AFP | 200（重定向 `/fr`） | **无 feed** | — | — | — | — |
| `bbc` | BBC News | 200 | 可用 | `https://feeds.bbci.co.uk/news/rss.xml` | 32 | 113 | 见 §8.2 |
| `xinhua` | 新华网 | 200 | **无 feed** | — | — | — | — |
| `nyt` | NYT | **403** | 站点拦截，但官方 RSS 域名可用 | `https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml` | 19 | 244 | 2026-10-20 |

### 5.4 实测汇总

| 结论 | 数量 | 明细 |
|---|---|---|
| 端点可用 | **8** | cn-pbc、us-bea、us-bls、us-census、us-fed、uk-ons、bbc、nyt |
| 只有官方入口，无机器端点 | **13** | cn-gov、cn-stats、cn-mof、cn-ndrc、cn-miit、cn-mofcom、cn-nea、cn-samr、worldbank、afp、xinhua、fred、eurostat |
| 被拦截（401/403/412） | **5** | cn-customs、imf、oecd、reuters、ap |

按建议书的分层看：**中国 10 个部委里只有 1 个有可用端点；国际官方 10 个里 5 个可用；三大通讯社 0 个可匿名获取。**
这决定了第一阶段不可能"接入政策与宏观"，只可能"登记并标注待核验"。

## 6. 准入规则

### 6.1 按证据角色分配

| 角色（`provenance_class`） | 典型来源 | 默认通道 | 默认 `content_access_level` | 可以证明什么 | 不能证明什么 |
|---|---|---|---|---|---|
| `first_party`（官方文件/统计/企业披露） | 部委、统计局、IR、财报 | A | `excerpt`（除非抽样确认全文） | 某人/某机构在何时说过什么 | 政策效果、市场反应 |
| `first_party`（社区一手表达） | 论坛、HN Ask | B（必要时 C） | `full_text` 需抽样确认 | 有人提出了这个问题 | 需求普遍、有人付费 |
| `vendor_marketing` | 厂商博客、云厂商 | A | 同左 | 厂商在推什么 | 独立市场事实 |
| `secondhand_report` | 通讯社、媒体 | A | 同左 | 有报道存在 | 事实本身；须回溯一手 |
| `primary_research` | arXiv、研究院 | C | `excerpt`（摘要即原文摘要） | 论文摘要说了什么 | 方法可复现、可商用 |
| `project_record` | GitHub Releases | C | 同左 | 项目发布了什么 | 采用率、商业价值 |

### 6.2 三条硬规则

1. **没有实测端点的来源不得启用。** `feed_url` 留空 + `enabled=false`，用 `endpoint_status=no_endpoint` 记录，不用网页冒充 Feed。
2. **新闻来源不得单独构成 E2。** `multi_source_coverage` 目前只统计"多个来源都有条目"，**没有**核对独立性；转载同一通讯社稿件不算多源。主张级交叉验证未实现。
3. **同一机构多端点合并管理。** 一个机构的多条 Feed（如 BLS 两条、NYT 多个栏目）共用 `institution`，`source_cap` 按机构总量计，而不是每个端点各算一次配额。

### 6.3 结构化数据（本管线外）

FRED、Eurostat、World Bank Data、国家统计局数据库属于**数据集**，不是文章源。建议独立登记，字段为：数据集 ID、API 端点、需否密钥、更新频率、单位、季调口径、修订策略、发布日历来源。
它们服务于"数字"而不是"事件"，不能混进简报条目流；否则会出现"CPI 同比 0.3%"这种没有事件、无法评分的条目。

## 7. 去重规则

| 规则 | 现状 | 建议 |
|---|---|---|
| URL 规范化（去 utm、去尾斜杠、去 AMP、统一域名） | 未实现（按 FreshRSS 的 guid/链接） | 实现：标准化后再取哈希 |
| 正文哈希去重 | **已实现**：`article_versions` 按 `article_key + summary_hash` 记录，内容变化追加版本并触发重分析 | 保持 |
| 通讯社转载识别（同一稿源多家转载） | 未实现 | 提取署名通讯社 + 比对正文前 N 字符；同稿只保留首发与转载标注 |
| 企业重复公告（同一新闻稿多渠道） | 未实现 | 以 `institution + 标题规范化 + 日期` 生成公告键 |
| 媒体 → 一手来源链接 | 未实现 | 抽取正文中的 .gov / IR / 法院 / 统计页链接，作为 `primary_source_located` 的候选 |
| 事件聚类 | 未实现 | 需要实体 + 日期 + 主题键；在没有标注集之前不做 |

前两条是"同一篇文章"，后四条是"同一件事"。**当前系统只解决前者**，报告里的 `multi_source_coverage` 容易被误读为后者。

## 8. 失效治理

### 8.1 状态机

```
unknown → verified_feed → (stale | blocked | no_endpoint | not_a_feed) → disabled
```

| 状态 | 判定 | 处置 |
|---|---|---|
| `verified_feed` | 200 且可解析，条目 ≥1 | 可进入准入审查 |
| `no_endpoint` | 入口页无 feed 声明 | 登记为人工查看；不得启用 |
| `blocked` | 401/403/412/429 | 记录并停止尝试；**不得绕过** |
| `not_a_feed` | 端点返回 HTML | 修正端点或删除该字段 |
| `stale` | 连续 3 次采样无新条目，且超过声明频率的 3 倍周期 | 复核是否停更/改版 |
| `unknown` | 只做过 1 次采样或采样失败 | 不得作为"可用"统计 |

### 8.2 已知的不稳定样本（本轮实测）

- **BBC**：同一 URL 在数分钟内两次采样，第一次 `latest=2025-04-30`，第二次 `latest=2026-10-22 21:29`。这是 CDN/边缘缓存造成的**观测不稳定**，不是来源停更。→ **任何"停更"结论都必须至少两次采样**，否则会误杀。
- **PBOC**：`Content-Type: text/html` 但内容是 RSS；GBK 编码。→ 端点可用性与响应头声明不一致时，以内容为准并记录差异。
- **`apps.bea.gov/rss/rss.xml`**：可解析但最新条目是 2013-12-18。→ 这是历史归档，不是新闻源；**"可解析"必须同时看最新日期**。

### 8.3 与现有审计的关系

`source_audit.py` 已检查：启用来源必须有 `reviewed_at`/`last_verified_at` 且在 180 天内（`MAX_REVIEW_AGE_DAYS`）、HTTPS、feed id、至少一条 `editorial_lanes`。
缺口：**没有 `endpoint_status`，也没有"连续失败自动降级"**。运行期失败只进 `errors` 计数，不改变来源状态。建议后续在 `runs` 中记录每源失败次数，连续 3 次 → 审计报 `stale_source`。

## 9. FreshRSS 分类迁移映射

FreshRSS 分类只服务人工阅读与维护，**不等于** A/B/C 通道，也不等于评分。

| 建议分类 | 现有订阅 | 登记表动作 |
|---|---|---|
| 01 政策与监管 | 无 | 新登记（§5.1，全部无端点/待核验） |
| 02 宏观与数据 | 无 | 新登记（§5.2，5 个可用） |
| 03 企业与资本 | 无 | 新登记（IR 披露；NVIDIA 已有，AMD 只能 E0） |
| 04 国际新闻 | 无 | 新登记（BBC、NYT 可用；Reuters/AP/AFP 拦截） |
| 05 产业与能源 | 无 | 新登记 |
| 06 AI 与软件 | OpenAI News、DeepMind、Hugging Face、GitHub Blog、TechCrunch AI、Simon Willison、OpenAI Developer Community、Hacker News | 保留；DeepMind/Hugging Face 保持禁用（正文为空） |
| 07 市场需求与机会 | HN Ask、HN Show | 保留 |
| 08 工程与专业技术 | SimScale 论坛、preCICE、ParaView、SALOME、SimScale Blog | 保留；从核心信息流降级 |
| 09 系统维护 | FreshRSS releases | **移出简报**；登记表当前无对应行，建议显式登记为 `enabled=false`、不进任何通道，而不是留作"未映射" |

两个当前"未映射"订阅的处置：

- `FreshRSS releases`（id=1）：登记一行 `source_type=tooling`，`editorial_lanes` 留空，永不启用。**留空是允许的，因为禁用行不需要通道。**
- `Hacker News`（id=2）：登记表已有 `hackernews-front` 但未填 feed id。二者是同一订阅，应填 `freshrss_feed_id=2`；是否采集单独决定（它是链接流，正文中位 68 字符，只能作发现入口）。

## 10. 分阶段落地与验收门

| 阶段 | 内容 | 验收门（必须可量化） |
|---|---|---|
| 0 | 本文档 + 候选实测（本轮） | 每个候选有 `endpoint_status`；无"官网可打开即视为可用"的记录 |
| 1 | 国际官方 5 源（BEA、BLS、Census、Fed、ONS） | 连续 7 天采集，失败率 <5%；E1 及以上占比 >80%；A 通道 `priority` 条目中出现官方口径 |
| 2 | 中国企业披露与产业协会 | 至少 3 个 IR/协会端点实测可用且正文非空；否则本阶段**不启用**，只登记 |
| 3 | 新闻发现层（BBC、NYT） | 同一事件的媒体条目能链接到一手来源的比例可测量；转载重复率 <30% |
| 4 | 政策与监管 | 只有在获得稳定端点（自建页面变更监测或官方 API）后才进入；否则保持人工查看 |
| 5 | 影子运行与留汰 | 按 `docs/SOURCE_REVIEW.md` §7 执行；用独有事件数、证据定位率、重复率、人工有用率决定留降删 |

**关键约束**：第 1 阶段之前不要动 `sources.csv` 的启用状态。现在的 7 个启用来源已能产出简报，先拿到基线数字，再谈结构调整。

## 11. 验收报告（本轮）

| 结论 | 来源 |
|---|---|
| 端点实测可用 | `cn-pbc`、`us-bea`、`us-bls`、`us-census`、`us-fed`、`uk-ons`、`bbc`、`nyt` |
| 仅确认官方入口，无机器端点 | `cn-gov`、`cn-stats`、`cn-mof`、`cn-ndrc`、`cn-miit`、`cn-mofcom`、`cn-nea`、`cn-samr`、`worldbank`、`afp`、`xinhua`、`fred`、`eurostat` |
| 被访问控制拦截，未尝试绕过 | `cn-customs`(412)、`imf`(403)、`oecd`(403)、`reuters`(401)、`ap`(403) |
| 许可状态 | **全部 `unknown`**。本轮未阅读任何服务条款，未做任何法律判断 |
| 正文完整度 | 未做抽样核验。表中"正文中位"只是 feed 自带文本长度，**不等于全文** |

## 12. 未验证项与风险

1. **单次采样**：所有端点结论只有一次观测；BBC 已证明一次观测会给出错误的最新日期。
2. **条款与许可**：26 个候选全部未读条款。`verified_feed` 与"允许保存/摘要/再发布"无关。
3. **CN 部委站点的真实结构**：入口无 feed 不等于永远没有；部分站点可能有需登录或需申请的数据接口，本轮未探查。
4. **FreshRSS 全文抓取能力**：能否为标题流来源补正文（Readability 扩展）未验证；若能，DeepMind/Hugging Face 的处置结论需要重估。
5. **`intelligence_lines` 的改动成本**：涉及 `source_policy.Source`、CSV 两张、`source_audit`、`admin_server.SOURCE_FIELDS`、报告附录与测试。
6. **`permission_status` 拆分**（§4.1）会改变 `is_approved()` 语义，必须单独一轮，不能与来源变更同批。

## 13. 待决事项（不阻塞本方案执行）

1. 是否引入 `intelligence_lines` 字段（推荐），还是用 `topic_tags` 受控词表（不推荐，理由见 §3.1）。
2. CN 部委无端点时，是否要新建"页面变更监测"能力（抓取栏目页 → 比对条目 → 生成条目）。这是**新管线**，不是 RSS 配置。
3. FRED/Eurostat 是否进入独立数据集登记表（推荐），还是永久排除。
4. `hackernews-front` 是否填 feed id=2 并启用（当前它是唯一"有登记、无映射"的来源）。

## 14. 本轮未做的修改

- 未改 `config/sources.csv`、`config/sources.local.csv`。
- 未启用、未禁用、未重命名任何来源。
- 未改 FreshRSS 的 16 个订阅、1 个分类、任何条目的已读状态。
- 未改 `lanes.py`、`scoring.py`、`evidence.py`、`source_audit.py`。
- 未改评分权重、阈值、证据等级或 `promote_rank`。
- 新增文件仅：本文件、`docs/source-probe-2026-10-23.json`（原始实测结果）、`tools/probe_sources.py`（只读探测脚本）。

## 附录 A：现有 31 个登记行的主线归属（建议，未写入登记表）

| source_id | 主线 | FreshRSS 分类 | 备注 |
|---|---|---|---|
| openai-news | TECH | 06 | 厂商自述 |
| deepmind-blog | TECH | 06 | 正文为空，保持禁用 |
| huggingface-blog | TECH | 06 | 正文为空，保持禁用 |
| google-ai-blog | TECH | 06 | 营销占比高 |
| arxiv-cs-ai | TECH | 06 | 摘要即摘要 |
| arxiv-cs-lg | TECH | 06 | 同上 |
| techcrunch-ai | NEWS, TECH | 06 | 二手报道 |
| simon-willison | TECH | 06 | 个人专家 |
| github-blog | TECH | 06 | 平台官方 |
| simscale-blog | TECH | 08 | 工程子领域，厂商自述 |
| hackernews-front | TECH | 06 | 链接流，仅作发现 |
| hn-ask | TECH | 07 | 一手用户表达 |
| hn-show | TECH | 07 | 产品自述 |
| precice-forum | TECH | 08 | 工程子领域 |
| paraview-forum | TECH | 08 | 工程子领域 |
| salome-forum | TECH | 08 | 工程子领域 |
| openai-community | TECH | 06 | 开发者社区 |
| simscale-forum | TECH | 08 | 工程子领域 |
| nvidia-newsroom | CORP | 03 | 官方公告 |
| nvidia-ir | CORP | 03 | 无端点 |
| microsoft-blog | CORP, TECH | 03 | 企业叙事 |
| microsoft-research | TECH | 06 | 研究 |
| amd-ir | CORP | 03 | 端点可用但正文为空 |
| google-research | TECH | 06 | 标题流 |
| aws-ml-blog | TECH | 06 | 厂商内容营销 |
| imf-publications | MACRO | 02 | 无端点 |
| oecd-publications | MACRO | 02 | 无端点 |
| world-bank-research | MACRO | 02 | 无端点 |
| sia-news | IND | 05 | 无端点 |
| mit-tech-review | NEWS, TECH | 04 | 二手报道 |
| ieee-spectrum | IND, TECH | 04/05 | 技术媒体 |

**`POL` 与 `NEWS`（除两家科技媒体外）在现有 31 行中完全没有承载。** 这正是"结构不匹配"的量化证据：不是博客太多，而是政策与企业披露为零。

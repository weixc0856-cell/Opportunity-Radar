# Opportunity Radar 产品需求文档（PRD）

版本：1.1
日期：2026-11-01
状态：已实施部分见 `docs/PROJECT_STATUS.md`；R2–R6 待批准
指导文件：[CLAUDE.md](../CLAUDE.md)
实施计划：[docs/IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
现状数据来源：生产库 `data/opportunity_radar.sqlite3`、仓库代码与配置，只读查询，2026-11-01

---

## 0. 文档说明

- 本文描述**产品需求与验收口径**，不描述具体实现步骤；实现顺序、文件级改动与测试计划见实施计划。
- 本文与 [CLAUDE.md](../CLAUDE.md) 冲突时，以 CLAUDE.md 的原则与阶段边界为准。
- 所有"现状"数字均来自 2026-11-01 的只读审计；未验证的外部 API 能力在文中标注"待核验"。
- 本文不承诺任何外部数据源的免费性、稳定性或商业使用许可；这些必须由 S0 审计逐项核验。

---

## 1. 产品定位与目标

### 1.1 一句话定位

Opportunity Radar 是**本地优先的全球商业、经济与政策情报系统**：从公开来源自动发现事件，抽取可追溯的事实主张，按证据质量判断可信度，并生成每日简报、每周研究与月度专题。

### 1.2 目标用户

单一专业用户（项目所有者），具备汽车、制造业、CFD、工程软件与 AI 工程背景，需要：

- 每天用 5–8 分钟掌握全球重要变化；
- 每周形成趋势与因果判断；
- 长期积累可验证、可转化的商业机会。

用户**不承担**日常新闻编辑、逐条标注或模型评分工作（见 CLAUDE.md §4）。

### 1.3 非目标

- 不是 RSS 阅读器、新闻搬运工具或自动财经写作系统。
- 不提供投资建议、法律结论或市场规模断言。
- 不做多用户 SaaS、团队协作与公网部署。
- 不绕过登录、付费墙、robots 或来源许可限制。
- 不追求每日内容数量。

### 1.4 成功定义（分阶段）

| 阶段 | 成功定义 |
|---|---|
| S0 | 来源覆盖、候选 API、许可风险与接入顺序有可复核的审计结论 |
| R0 | 系统故障时不再发出误导性简报；失败可归因、可追溯 |
| R1 | 同一事件可聚合，主张可回溯到原文定位 |
| R2 | 重要数字类主张可被确定性核验，核验失败不进入事实结论 |
| R3 | 重要性、证据质量与阅读优先度分离，编辑决策可追溯 |
| R4 | 周报/月报从事件与数据重新生成，而非拼接日报 |
| R5 | 官方经济数据可复现地计算同比/环比并关联事件 |
| R6 | 质量变化可被自动发现，指标缺失时标注 NOT_MEASURED |

---

## 2. 现状与问题

### 2.1 运行现状（实测）

| 项 | 数值 |
|---|---|
| 生产库 articles / analyses | 110 / 99（v5 61、v4 38） |
| analysis_sections | 658（fact 211，其中可定位 197） |
| 运行记录 runs | 13（2026-10-20 至 2026-11-01） |
| 邮件投递 deliveries | 26 |
| 人工复核 reviews | 0 |
| 单元测试 | 423 项通过（1.5 秒） |
| 本地模型 | Qwen3-30B-A3B-Instruct-2507-Q4_K_M，约 11 tok/s |
| 单次完整运行 | 20 篇约 10–16 分钟 |

### 2.2 来源产出（10 天窗口，实测）

| 来源 | 文章 | 已分析 | 类型 |
|---|---|---|---|
| Hacker News Show | 22 | 19 | 社区项目发布（L5） |
| Hacker News Ask | 20 | 19 | 社区讨论（L5） |
| OpenAI Developer Community | 11 | 9 | 开发者论坛（L5） |
| ParaView Forum | 8 | 7 | 工程论坛（L5） |
| SimScale Forum | 7 | 7 | 工程论坛（L5） |
| NYT Business | 7 | 6 | 新闻媒体（L3） |
| BBC Technology | 7 | 5 | 新闻媒体（L3） |
| BBC Business | 7 | 7 | 新闻媒体（L3） |
| NYT Technology | 6 | 5 | 新闻媒体（L3） |
| NVIDIA Newsroom | 4 | 4 | 企业公告（L0） |
| UK ONS Release Calendar | 3 | 3 | 官方统计（L0/L1） |
| BEA News | 3 | 3 | 官方统计（L0/L1） |
| preCICE Forum | 2 | 2 | 工程论坛（L5） |
| Federal Reserve Press Releases | 2 | 2 | 官方政策（L0） |
| SALOME Forum | 1 | 1 | 工程论坛（L5） |

论坛/社区七源合计 71/110（65%）；四个新闻源 27；官方统计与政策四源合计 12。

### 2.3 通道与证据分布

| 通道 | 已分析条数 | 说明 |
|---|---|---|
| A 商业、科技与经济情报 | 35 | 主要来自新闻媒体，官方来源产出少 |
| B 商业机会 | 53 | 被 HN / 论坛来源主导 |
| C 技术观察与工程信号 | 2 | 几乎为空 |
| 无通道记录（旧 v4 记录） | 9 | 兼容旧数据 |

证据等级：E0 8、E1 70、E2 21。

### 2.4 核心问题

| 编号 | 问题 | 证据 |
|---|---|---|
| P1 | 来源覆盖偏斜：RSS 论坛源占比过高，L0/L1 官方来源产出极低，C 通道几乎无内容 | 2.2 / 2.3 |
| P2 | 文章级分析：同一事件多篇报道无法聚合，`event_key` 只是标题哈希 | store.py；`docs/OPEN_ISSUES.md` ISSUE-003 |
| P3 | 主张不可核验：fact 有引文与定位，但没有主体/指标/数值/单位/期间/口径 | schema.py v5；analysis_sections |
| P4 | 发布不可靠：模型中途故障时仍发布近乎空白的简报 | 2026-11-01 run 13 |
| P5 | 无多周期产品：只有日报与归档，无周报/月报 | 代码库无 weekly/monthly |
| P6 | 质量不可度量：无固定样本集，无独立基准，reviews=0 | 生产库；`docs/archive/P0_AUDIT_2026-10-26.md` |

---

## 3. 产品原则

1. **Evidence First**：结论必须能回到可定位的原文。
2. **Source Independence**：多来源覆盖按来源谱系计算，不按文章数量。
3. **Reproducible Analysis**：相同输入、相同规则版本产生相同结果。
4. **Quantitative Evaluation**：无真实基准时标注 NOT_MEASURED，不用模型自评代替。
5. **Fail-Closed Publication**：不能可靠验证或运行不完整的内容降级、隔离或阻止发布。
6. **No Daily Manual Labor**：用户不做日常标注、打分或新闻价值判断。
7. **Local First / Stdlib First**：本地运行，运行期标准库优先；依赖经 uv 管理，可追溯。
8. **Stage Delivers Value**：每个阶段必须产生可独立使用的产品价值，而不是只产出下一阶段的技术基础；不得为后续目标提前开发暂时无法验证的模块。

---

## 4. 信息架构与产品形态

### 4.1 数据分层

```
Source → Article → Event → Claim / Evidence → Analysis → Editorial → Publication
```

- **Source**：RSS、官方 API、网页监测、结构化数据集，带谱系与许可字段。
- **Article**：文章版本、来源身份、发布时间、内容哈希、检索状态。
- **Event**：同一事件的聚合、时间线、来源关系。
- **Claim / Evidence**：结构化主张与逐字引文定位、独立性、冲突关系。
- **Analysis**：A/B/C 通道判断，区分事实/解释/推断/假设/预测。
- **Editorial**：Signal / Evidence / Editorial Priority、重复抑制、发布决策。
- **Publication**：Daily / Weekly / Monthly、归档与历史。

### 4.2 研究通道

| 通道 | 研究范围 | 核心问题 |
|---|---|---|
| A | 全球宏观经济、货币财政政策、贸易与地缘经济、产业政策与监管、企业战略与资本开支、行业供需与竞争 | 发生了什么、相对基线变化、波及谁、有哪些解释、如何验证 |
| B | 新需求、买方痛点、企业采购、付费行为、供给缺口、商业模式 | 谁有痛点、谁付费、证据是什么、能否交付 |
| C | AI、半导体、算力、数据中心、能源、制造、汽车、工业软件、CAE、机器人、新材料 | 技术是否实质进展、能否复现、商业与工程意义 |

### 4.3 产品形态

| 产品 | 频率 | 核心问题 | 数据来源 |
|---|---|---|---|
| Daily Brief | 每日 | 今天发生了什么重要变化 | 当日 events + claims + 指标 |
| Weekly Intelligence | 每周 | 过去一周哪些变化之间有联系 | 7 日 events + claims + dataset_observations |
| Monthly Research | 按需 | 某个研究问题的完整判断 | 专题证据集合 + 反面证据 |
| Opportunity Database | 持续 | 哪些需求/买方/付费证据可验证 | B 通道证据链 |
| 本地工作台 | 常驻 | 状态、来源、运行、报告 | SQLite + 日志 |

---

## 5. 功能需求

优先级定义：P0 = 阶段必须；P1 = 阶段内重要；P2 = 后续。

### 5.1 来源覆盖与接入（S0–S4）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-S1 | 每个来源在登记表中具备统一治理字段（见 §6.2），包括访问方式、许可、配额、成本、历史可用性与存储策略 | P0 |
| FR-S2 | 记录来源谱系：`source_family`、`parent_source`、`syndication_group`、`ownership_group`、`primary_or_secondary`、`independence_status` | P0 |
| FR-S3 | 每条文章在入库时绑定 `source_id` 与 `connector`，不再依赖来源名称匹配 | P0 |
| FR-S4 | 来源按用途分层 L0–L5，并声明允许进入的通道 | P0 |
| FR-S5 | 新增连接器必须声明许可状态；未核验许可的数据源保持 blocked，不得启用 | P0 |
| FR-S6 | 同一内容经多个媒体转载时，只计一个原始来源；转载关系可查询 | P0 |
| FR-S7 | 每个连接器有独立配额、超时、失败隔离与健康度记录 | P0 |
| FR-S8 | 支持结构化数据连接器（统计口径、期间、单位、修订），与文章管道分离 | P1 |
| FR-S9 | S0 对每个候选来源独立评估 Coverage（覆盖领域）、Signal Yield（可持续产出的独立事件）、Evidence Value（能否提供原始数据/公告/可定位证据）；三者分别记录，不得用文章数量代替 | P0 |

验收要点：

- 任一来源的数据可在不依赖名称匹配的情况下归因到 `source_id`。
- 转载关系可区分 `independent_primary` / `syndicated` / `unknown`。
- 未核验许可的来源无法被启用，且报告中可见原因。

### 5.2 运行可靠性与发布门禁（R0）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-R0-1 | 模型调用对连接类错误做有限退避重试，超时错误限制重试次数 | P0 |
| FR-R0-2 | 首次传输失败后复查模型健康；不可达则熔断，不再逐篇发起调用 | P0 |
| FR-R0-3 | 失败按原因分类记录（transport / timeout / invalid_output / schema_error / unknown） | P0 |
| FR-R0-4 | 运行级覆盖率 `analyzed / attempted` 决定发布状态 | P0 |
| FR-R0-5 | 全部分析失败或模型不可用 = HOLD，不发送订阅邮件 | P0 |
| FR-R0-6 | 部分失败按覆盖率进入 PASS_WITH_LIMITATIONS，报告必须披露覆盖率与失败原因 | P0 |
| FR-R0-7 | 运行完整但没有信号 = 正常报告，不误判为故障 | P0 |
| FR-R0-8 | 每个失败可追溯到 `analysis_failures`（含原因）与 `runs`（含覆盖率、发布状态） | P0 |

验收要点见 §7.3 与实施计划 §5。

### 5.3 事件、主张与证据（R1）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-E1 | 新增事件实体，一个事件关联多篇文章 | P0 |
| FR-E2 | 新增文章—事件关联，记录关系类型与分配方式（规则/模型/人工） | P0 |
| FR-E3 | 新增 Claim 实体：主体、指标、数值、文本值、单位、币种、地区、期间、比较口径、分母、季节调整、修订状态、引文、定位、核验状态 | P0 |
| FR-E4 | Claim 必须关联证据定位；无法定位的引文不得生成已核验 Claim | P0 |
| FR-E5 | 事件合并、拆分与纠错为追加式记录，不覆盖历史 | P0 |
| FR-E6 | 旧数据回填：可定位 fact 生成 Claim；v4 旧记录不伪造 Claim | P0 |
| FR-E7 | 同一账号重复运行不产生重复事件或重复 Claim | P0 |
| FR-E8 | 事件聚类优先确定性规则，不因新增阶段而增加逐篇模型调用 | P0 |
| FR-E9 | 新增独立 Evidence 实体（稳定 ID、引文、定位、来源、来源族、独立性），一条 Evidence 可支撑或反驳多条 Claim；Claim 与 Evidence 通过关联表连接 | P0 |

验收要点：

- 已知重复事件对（同源近似标题、跨栏目同稿）能正确聚合。
- 无关事件不因共享关键词被错误合并。
- 每条 Claim 可回溯到文章与原文位置。
- 旧日报、旧分析、人工复核历史不被破坏。

### 5.4 证据核验（R2）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-V1 | 提示词升级为 Claim 抽取契约（字段在 R1 已可存储）；不合规字段降级为偏差记录，不整篇丢弃 | P0 |
| FR-V2 | 确定性核验 R1 已存储的全部 Claim 字段（主体、指标、数值、单位、币种、地区、期间、比较口径、分母、季调、修订状态） | P0 |
| FR-V3 | 单位换算与百分点/百分比区分使用显式规则表 | P0 |
| FR-V4 | 引文支持关系分为直接支持、间接支持、不支持、冲突 | P0 |
| FR-V5 | 同一事件+指标+期间的多来源主张做冲突检测 | P0 |
| FR-V6 | 区分 fact / source_interpretation / system_inference / hypothesis / forecast / opinion | P0 |
| FR-V7 | 未通过核验的主张标记为 rejected / unverifiable，不得作为已核验事实发布 | P0 |
| FR-V8 | 派生数据保留公式、输入值、单位与来源 | P1 |

验收要点：

- 构造的数值/单位/期间陷阱样本被正确拒绝。
- 转载来源不因数量优势通过核验。
- 核验失败不会阻止整篇分析入库，但会阻止其以事实身份发布。

### 5.5 编辑与评分（R3）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-ED1 | 分离 Signal Score（重要性）、Evidence Score（证据质量）、Editorial Priority（本期阅读价值） | P0 |
| FR-ED2 | Editorial Priority 采用 P0 / P1 / P2 / P3 / REJECT，与来源配额分开存储 | P0 |
| FR-ED3 | 重复事件跨期抑制；deferred 条目有跨期承载机制 | P0 |
| FR-ED4 | 重要事件晋升机制可解释、可追溯 | P0 |
| FR-ED5 | What to Watch 字段可跨期跟踪 | P1 |
| FR-ED6 | 编辑决策独立成表，记录规则版本与理由 | P0 |
| FR-ED7 | 政策类内容分类覆盖（解决 `policy_change` / `political_event` 被拒） | P0 |

### 5.6 多周期发布（R4）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-P1 | Daily Brief 保持现有版式结构，Executive Summary 基于最终选中事件生成 | P0 |
| FR-P2 | Weekly Intelligence 从 7 日事件、主张、证据与指标重新生成 | P0 |
| FR-P3 | Monthly Research 围绕研究问题组织，必须包含反面证据与局限 | P1 |
| FR-P4 | 历史事件时间线与跨期比较 | P1 |
| FR-P5 | 同一事件不在不同日报重复占据主要位置 | P0 |
| FR-P6 | 图表必须标注来源、分母、时间范围与统计口径 | P0 |

### 5.7 经济数据引擎（R5）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-D1 | 数据集登记包含定义、单位、频率、地区、季调、基期、分母、发布日、修订策略、许可 | P0 |
| FR-D2 | 历史观察值快照；修订不覆盖历史值 | P0 |
| FR-D3 | 确定性计算：YoY / MoM / QoQ / 移动平均 / 指数变化 / 百分点变化 / 滚动波动 / 历史区间 / 异常检测 | P0 |
| FR-D4 | 每次计算保留输入、公式、单位与时间范围 | P0 |
| FR-D5 | 数据集与新闻事件可关联 | P1 |
| FR-D6 | 图表可由原始数据重新生成 | P1 |
| FR-D7 | 不引入预测模型作为当前目标 | P2 |

### 5.8 质量与回测（R6）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-Q1 | 建立 Benchmark Corpus，包含 deterministic_gold / source_grounded / synthetic_adversarial / historical_cases / unresolved_cases | P0 |
| FR-Q2 | 固定样本、固定规则版本的自动回归 | P0 |
| FR-Q3 | 30 天与 90 天回测 | P1 |
| FR-Q4 | 模型 / 提示词 / 规则版本对比，记录新增通过项、回归项与耗时变化 | P0 |
| FR-Q5 | 来源健康度、来源独立性统计、失败率、证据通过率 | P0 |
| FR-Q6 | 无法真实测量的指标标注 NOT_MEASURED，不用模型自评填充 | P0 |
| FR-Q7 | 每周系统质量报告 | P1 |
| FR-Q8 | 质量下降可自动发现 | P0 |

### 5.9 本地工作台（已实现能力，需保持）

| ID | 需求 | 优先级 |
|---|---|---|
| FR-W1 | 总览：模型状态、启用来源数、最近运行、最近报告、失败摘要 | P0 |
| FR-W2 | 信息源：治理字段编辑、审核状态、Feed 映射、启用/禁用 | P0 |
| FR-W3 | 收件人：格式校验、逐地址测试结果 | P0 |
| FR-W4 | 运行与定时：手动运行确认、运行中互斥、阶段展示 | P0 |
| FR-W5 | 报告与归档查看、失败详情、日志脱敏 | P0 |
| FR-W6 | 只监听 `127.0.0.1`，不显示密钥 | P0 |

信息架构保持：总览 / 机会线索 / 信息源 / 收件人 / 运行与定时 / 运行历史 / 日报与归档 / 系统设置。
现有实现：`opportunity_radar/admin_server.py` + `admin/`。

---

## 6. 数据模型需求

### 6.1 实体

| 实体 | 状态 | 要求 |
|---|---|---|
| sources | 已有（CSV 登记） | 增加谱系、许可、层级、连接器字段 |
| articles | 已有 | 增加 `source_id`、`connector`、`external_id` |
| article_versions | 已有 | 保持不变，追加式 |
| events | 新增 | 事件标识、类型、首末次出现、状态、合并关系 |
| event_articles | 新增 | 关系类型、分配方式、置信度 |
| evidences | 新增 | 稳定证据 ID、引文、定位、来源、来源族、独立性；一条证据可支撑多条主张 |
| claims | 新增 | 结构化主张（含币种/地区/分母/季调/修订状态）+ 核验状态 |
| claim_evidence | 新增 | 主张与证据的连接：直接/间接/不支持/冲突，附带定位 |
| analyses / analysis_sections | 已有 | v5 保持；v6 增加 claim 字段 |
| editorial_decisions | 新增 | 优先级、理由、规则版本 |
| reviews / review_history | 已有 | 保留，不要求日常使用 |
| runs / deliveries | 已有 | 增加覆盖率、发布状态、失败原因 |
| reports | 由 runs + 归档扩展 | 报告类型（daily/weekly/monthly）、版本 |
| dataset_observations | 新增 | 期间、值、单位、修订、抓取时间 |

### 6.2 来源治理字段（最低集）

`source_id`、`source_name`、`source_type`、`source_category`、`target_lanes`、`access_method`、`api_documentation`、`terms_url`、`license_type`、`rate_limit`、`api_cost`、`historical_availability`、`content_storage_policy`、`redistribution_policy`、`commercial_use`、`retrieval_method`、`implementation_complexity`、`priority`、`review_status`，以及谱系字段 `source_family`、`parent_source`、`syndication_group`、`ownership_group`、`primary_or_secondary`、`independence_status`。

### 6.3 数据规则

- 迁移只允许附加式（ADD COLUMN / CREATE TABLE），使用 `PRAGMA user_version` 版本化。
- 只读路径（如 `--render-only`）不得触发迁移。
- 文章、版本、分析历史、编辑决策与纠正记录均为追加式，不覆盖。
- 原始正文默认不在许可未确认时长期保存；保存策略按来源登记执行。

---

## 7. 质量框架与发布判定

### 7.1 五个质量层

Q1 Evidence Quality、Q2 Source Independence、Q3 Claim Verification、Q4 Analytical Quality、Q5 Publication Quality（定义见 CLAUDE.md §5）。

### 7.2 发布状态

| 状态 | 含义 | 行为 |
|---|---|---|
| PASS | 全部质量门通过 | 正常发布 |
| PASS_WITH_LIMITATIONS | 存在已知限制（覆盖率不足、证据等级偏低） | 发布并明确标注限制 |
| HOLD | 无法可靠判断（模型不可用、全失败、核验冲突） | 不发送订阅邮件；保留本地报告与运行记录 |
| REJECT | 内容不具情报价值或违反约束 | 不进入本期 |

### 7.3 门禁矩阵（草案，阈值需批准）

| 门 | 检查 | 失败后果 |
|---|---|---|
| Source Gate | 来源已批准、许可有效、身份可追溯 | REJECT 该条 |
| Evidence Gate | 重要主张有定位证据；通道晋升门槛满足 | 降级或 HOLD |
| Factual Gate | 数值/单位/期间/主体/引文支持通过 | REJECT 该主张（不阻止整篇） |
| Analytical Gate | 事实/推断/假设/预测分离；反面证据未被忽略 | PASS_WITH_LIMITATIONS |
| Editorial Gate | 无重复事件、结论明确、有阅读价值 | REJECT 或 P3 |
| Publication Gate | 格式、链接、归档、邮件、运行完整性 | HOLD |

运行级覆盖率（草案）：`coverage ≥ 0.8` → PASS；`0.5 ≤ coverage < 0.8` → PASS_WITH_LIMITATIONS；`coverage < 0.5` 或模型不可用 → HOLD。阈值属产品决策，见 §12。

### 7.4 失败分类

`transport`、`timeout`、`invalid_output`、`schema_error`、`evidence_gate`、`unknown`。每类在报告中独立计数，不与"无信号"混同。

---

## 8. 指标定义

| 指标 | 计算 | 周期 | 数据来源 | 状态 |
|---|---|---|---|---|
| Source Coverage | 有产出的启用来源 / 启用来源 | 30 天 | sources + articles | 可测（需 source_id 绑定后更准确） |
| Source Domain Coverage | 该来源覆盖的信息领域与通道（人工核验 + 标签） | S0 / 季度 | sources | S0 核验后可用 |
| Source Signal Yield | 该来源在周期内产生的独立事件数 / 抓取文章数 | 30 天 | events + articles | NOT_MEASURED（待 R1） |
| Source Evidence Value | 该来源提供原始数据/公告/可定位证据的比例 | 30 天 | claims + evidences + sources | NOT_MEASURED（待 R2） |
| Retrieval Success Rate | 成功抓取 / 抓取尝试 | 每次运行 | 运行日志 / connector 记录 | R0/S1 后可测 |
| Unique Event Yield | 去重事件数 / 文章数 | 30 天 | events + articles | NOT_MEASURED（待 R1） |
| Independent Evidence Yield | 有 ≥2 独立来源族的 Claim / 全部 Claim | 30 天 | claims + 谱系 | NOT_MEASURED（待 R1/R2） |
| Primary Source Coverage | 引文来自 L0/L1 的 Claim / 全部 Claim | 30 天 | claims + sources | NOT_MEASURED（待 R2） |
| Source Cost per Useful Event | （API 费用 + 维护工时）/ 通过编辑门的事件数 | 季度 | 来源登记 + editorial_decisions | NOT_MEASURED |
| Historical Availability | 来源提供历史区间的比例 | 季度 | 来源登记 | 可测（人工核验后） |
| License Compliance | 已核验许可来源 / 启用来源 | 每次来源变更 | sources | 可测 |
| Claim Evidence Coverage | 有定位证据的重要主张 / 重要主张 | 每次运行 | claims | NOT_MEASURED（待 R1） |
| Citation Support Rate | 被判定直接支持的引文 / 全部引文 | 每次运行 | claim_evidence | NOT_MEASURED（待 R2） |
| Numeric Consistency Rate | 数值核验通过 / 数值类主张 | 每次运行 | claims | NOT_MEASURED（待 R2） |
| Duplicate Cluster Precision / Recall | 对照基准样本 | 回测 | benchmark corpus | NOT_MEASURED（待 R6） |
| Publication Gate Escape Rate | 不应通过却通过门禁的样本 / 全部样本 | 回测 | benchmark corpus | NOT_MEASURED（待 R6） |
| Runtime Failure Rate | 失败运行 / 全部运行 | 30 天 | runs | 可测（R0 后含原因） |

规则：没有独立基准的指标一律 NOT_MEASURED，禁止用模型自评替代。

区分三个层次：**抓取成功率**（能不能取到）、**文章数量**（取到多少）、**情报价值**（是否产生独立事件与可验证证据）。S0 与后续报告不得用前两者代替第三者。

---

## 9. 非功能需求

| ID | 需求 |
|---|---|
| NFR-1 | 本地优先：FreshRSS、SQLite、llama.cpp、Windows 计划任务；不引入云端依赖 |
| NFR-2 | 运行期标准库优先；任何新增依赖需记录用途、版本、替代方案 |
| NFR-3 | Python 依赖由项目内 uv 环境管理（`.venv`、`pyproject.toml`、`uv.lock`、`uv run`）；禁止全局 pip 安装 |
| NFR-4 | 单次 20 篇运行在现有硬件上不超过 20 分钟；新增分析步骤不得无上限增加模型调用 |
| NFR-5 | 所有网络请求有超时；失败幂等、可重试、可隔离 |
| NFR-6 | 报告先写临时文件、校验后原子替换；失败保留上一份有效报告 |
| NFR-7 | 日志不含密钥、授权码或完整认证头 |
| NFR-8 | 管理后台只绑定回环地址；破坏性操作需确认 |
| NFR-9 | 来源许可与存储策略可追溯；未确认许可不保存、不再发布 |
| NFR-10 | 数据库迁移可回滚（先备份、事务内迁移、只读路径不迁移） |

---

## 10. 里程碑与验收

| 里程碑 | 内容 | 独立交付价值 | 完成标志 |
|---|---|---|---|
| M0 | 设计一致性修订 | PRD、实施计划、CLAUDE.md 无相互矛盾 | 一致性审计记录关闭全部已知冲突 |
| M1 | S0 审计报告 | 知道哪些来源值得接入、成本与许可边界 | 来源价值评估（Coverage / Signal Yield / Evidence Value）、候选表、风险清单、连接器设计、分批顺序获批 |
| M2 | R0 设计冻结 | 明确故障处理与发布门禁 | 设计经批准，阈值与 HOLD 行为确定 |
| M3 | R0 实施 | 模型故障时不再发送误导性日报 | 故障注入全部通过；11-01 场景不再发布；回归全绿 |
| M4 | R1 实施 | 可在库中按事件与主张检索、回溯原文 | 事件聚合、Claim/Evidence 回填、来源独立性、幂等验证通过 |
| M5 | R2 实施 | 报告中的数字类结论可被核验或明确标记未核验 | 核验陷阱样本通过；未核验主张不得作为事实发布 |
| M6 | R3 实施 | 读者看到的是编辑判断后的条目 | 三分评分、优先级、跨期抑制可追溯 |
| M7 | R4 实施 | 每周/每月获得跨期研究，而非日报拼接 | 周报/月报基于事件与数据生成 |
| M8 | R5 实施 | 新闻中的变化可与官方数据对照 | 数据集快照与确定性计算可复现 |
| M9 | R6 实施 | 质量变化可被发现，指标缺失被标注 | Benchmark 回归、30/90 天回测、质量报告 |

阶段验收必须区分：设计完成 / 代码实现 / 测试通过 / 数据迁移完成 / 真实运行通过 / 生产发布成功。

---

## 11. 风险与开放问题

| 编号 | 风险 | 影响 | 缓解 |
|---|---|---|---|
| RK-1 | 本地模型吞吐约 11 tok/s | 增加分析步骤会显著拉长运行 | 聚类确定性化；新增模型调用需预算论证 |
| RK-2 | 模型服务不稳定（11-01） | 运行失败、误发布 | R0 重试、熔断、覆盖率门禁 |
| RK-3 | 外部 API 许可/配额不确定 | 来源无法接入或成本上升 | S0 逐项核验；未核验保持 blocked |
| RK-4 | 官方来源产出低 | A 通道信息稀薄 | 连接器接入 + 抓取频率评估 |
| RK-5 | 无独立基准 | 无法宣称准确率 | Benchmark Corpus；NOT_MEASURED |
| RK-6 | 事件聚类误合并 | 错误情报 | 确定性规则优先；人工纠错追加记录 |
| RK-7 | 旧数据兼容 | 迁移破坏历史 | 附加式迁移；不虚构 Claim |

开放问题：

1. 覆盖率阈值（0.8 / 0.5）是否采用。
2. HOLD 时是否允许当天完全不发信，或改发"限制性摘要"。
3. 官方来源的抓取/调用频率与成本上限。
4. 是否允许保存正文用于事后复核（按来源许可分级）。
5. 周报/月报的发布载体（邮件 / 本地 HTML / 两者）。

---

## 12. 待批准决策

| 编号 | 决策 | 默认建议 |
|---|---|---|
| D-1 | R0 覆盖率阈值 | 0.8 PASS / 0.5 HOLD |
| D-2 | HOLD 的邮件行为 | 不发订阅邮件，只保留本地报告与后台状态 |
| D-3 | 模型重试策略 | 连接错误 3 次，超时 1 次，指数退避 |
| D-4 | 来源接入顺序 | L0/L1 官方优先，L3 新闻次之，L5 仅线索 |
| D-5 | 正文保存策略 | 按来源许可分级；未确认不长期保存 |
| D-6 | 依赖边界 | 仅 uv 环境管理；运行期仍为纯标准库，除非基准测试证明不足 |

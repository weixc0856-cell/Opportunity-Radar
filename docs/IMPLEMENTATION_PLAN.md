# Opportunity Radar 实施计划（S0–R6）

版本：1.1
日期：2026-11-01
状态：S0 冻结、R0 已实施并验收、R1 Batch 1–4 已交付；R2 未开始
配套文档：[docs/PRD.md](PRD.md)、[CLAUDE.md](../CLAUDE.md)、[docs/PROJECT_STATUS.md](PROJECT_STATUS.md)
阶段边界：**已完成阶段的事实记录见 §19 与 `docs/PROJECT_STATUS.md`；下一阶段（R2）需 G6 批准。**

---

## 1. 现状基线（2026-11-01 只读审计）

### 1.1 仓库

| 项 | 状态 |
|---|---|
| 分支 | `feat/evidence-lanes-source-governance`，比 `origin` 领先 7 个提交，共 22 个提交 |
| 工作区 | 干净（本轮新增未跟踪的 `CLAUDE.md`、`docs/PRD.md`、本文件） |
| 测试 | 423 项 unittest 通过（1.5 秒） |
| CI | `.github/workflows/django.yml`，Python 3.11 / 3.12，仅 `main` 的 push/PR |
| 运行期依赖 | 无第三方包（`pyproject.toml` dependencies = []） |
| 本地 Python | 3.13.14（`BUILD_STATUS.txt` 记录的是 3.12.10 的冻结检查点） |

### 1.2 数据库

| 表 | 行数 | 说明 |
|---|---|---|
| articles | 110 | 无 `source_id` 列，来源归属只在 `analyses.meta.source_id` |
| article_versions | 116 | 内容版本，追加式 |
| analyses | 99 | v5 61、v4 38 |
| analysis_history | 104 | 追加式 |
| analysis_sections | 658 | fact 211（可定位 197）、inference 119（可支撑 106）、gap 163、action 165 |
| analysis_failures | 7 | 全部来自 2026-11-01 运行，stage 恒为 `analyze`，无原因分类 |
| runs | 13 | 最近一次 `partial_failed`、exit 1 |
| deliveries | 26 | 逐收件人 |
| reviews / review_history | 0 / 0 | 机制存在，未使用 |

证据分布：E0 8、E1 70、E2 21。通道分布：A 35、B 53、C 2、无记录 9。

### 1.3 来源

| 项 | 数值 |
|---|---|
| 登记行 / 启用 | 47 / 15 |
| approved 但未启用 | 0 |
| 声明通道 | A 28、A,C 6、B,C 5、C 4、B 3、空 1 |
| content_access_level | excerpt 26、full_text 11、auto 10 |
| full_text_fetch | 全部 `none` |
| 10 天内有产出的来源 | 15（全部启用来源都有产出） |

产出结构：论坛/社区七源 71 篇（65%），四个新闻源 27 篇，官方统计/政策四源 12 篇。
实测每源产出见 PRD §2.2。

### 1.4 结构化数据与页面监测

| 项 | 数值 | 状态 |
|---|---|---|
| datasets.csv | 2 行 | Eurostat HICP approved；FRED GDP blocked（缺 API key） |
| page_watch.csv | 2 行 | 国家统计局 approved；中国政府网 blocked（JS 渲染） |

无时间序列存储、无同比/环比计算、无图表生成。

### 1.5 运行环境

- 模型：Qwen3-30B-A3B-Instruct-2507-Q4_K_M，约 11 tok/s，超时 300 秒。
- 单次 20 篇运行 10–16 分钟。
- 2026-11-01：模型中途连接重置/拒绝，9 篇中 7 篇失败，覆盖率 22%，仍发送简报。

---

## 2. 差距与优先级

| 差距 | 关联阶段 | 优先级 | 理由 |
|---|---|---|---|
| 故障时误发布 | R0 | P0 | 直接影响可信度；修复成本最低 |
| 来源覆盖偏斜、官方来源缺失 | S0 / S1 | P0 | 决定 A 通道与 C 通道是否有内容可研究 |
| 事件级缺失 | R1 | P0 | 后续所有跨期能力的前提 |
| 主张不可核验 | R2 | P0 | 研究价值与证据审计的核心 |
| 无编辑优先级 | R3 | P0 | 决定读者看到什么 |
| 无多周期报告 | R4 | P1 | 依赖 R1/R2 |
| 经济数据引擎为空 | R5 | P1 | 可与 R1/R2 并行 |
| 质量不可度量 | R6 | P1 | 依赖 R0/R1 |

---

## 3. 路线图与依赖

```
设计一致性修订 ──> S0（只读来源审计）──> D1 SEC/EIA 接入设计 ──> R0 设计冻结 ──> R0 实施
                        │                                      │
                        │                                      └──> R1（Event/Claim/Evidence）──> R2（核验）──> R3（编辑/评分）
                        │                                                 │                                   │
                        │                                                 └──> R4（周报/月报）<── R5（经济数据）
                        │                                                                       │
                        │                                                            R6（Benchmark/回测）
                        └──> S1（连接器 + L0/L1 官方源）──> S2 / S3 / S4
```

顺序说明：

1. **设计一致性修订**（2026-11-01）：先消除 PRD、实施计划与 CLAUDE.md 之间的矛盾，见 §21。
2. **S0 只读审计**：来源价值评估决定"接入什么"，先于任何代码实施。P0 已冻结。
3. **D1 接入设计评审**：只对 SEC EDGAR 与 EIA 做数据契约、字段映射、失败/修订规则、权利边界与验收标准；
   不写连接器、不改数据库。设计通过后再决定是否实施。
4. **R0 设计冻结**：确认故障处理、发布门禁与阈值，经批准后冻结。
5. **R0 实施**：第一个代码阶段；完成后即可获得"模型故障时不误发"的系统。
6. **S1 连接器框架**在 R1 数据模型确定后实施（需要 `source_id` 绑定与事件归属），可与 R2 并行。
7. R4 依赖 R1（事件时间线）与 R5（指标）；R6 依赖 R0 的失败分类与 R1 的聚类。

| 阶段 | 预计工作量 | 独立交付价值 | 依赖 | 审批门 |
|---|---|---|---|---|
| 设计一致性修订 | 0.5–1 天 | 文档无相互矛盾 | — | G0（本次已完成） |
| S0 审计 | 4–6 天 | 知道哪些来源值得接入、成本与许可边界 | — | G1 |
| D1 SEC/EIA 接入设计 | 1–2 天 | SEC 与 EIA 的数据契约、质量规则与验收标准 | S0 | G-D1（已关闭） |
| R0 设计冻结 | 0.5 天 | 故障处理与发布门禁确定 | D1 | G2 |
| R0 实施 | 3 天 | 模型故障时不发送误导性日报 | 设计冻结 | G3 |
| R1 | 6–8 天 | 可按事件与主张检索、回溯原文 | R0 | G4 |
| S1 连接器 + L0/L1 | 5–7 天 | 官方来源进入管道，A/C 通道有内容 | R1 schema | G5 |
| R2 | 6–8 天 | 报告中的数字结论可核验或被标记 | R1 | G6 |
| R3 | 5–7 天 | 读者看到的是编辑判断后的条目 | R2 | G7 |
| S2 事件/新闻 API | 3–5 天/连接器 | 事件发现覆盖面扩大 | S1 | G5 |
| R4 | 6–8 天 | 每周/每月获得跨期研究 | R1 + R5 | G8 |
| R5 | 7–10 天 | 新闻变化可与官方数据对照 | 独立 | G5/G8 |
| R6 | 5–7 天 + 持续 | 质量变化可被发现 | R0/R1/R2 | G8 |
| S3 学术/技术源 | 2–4 天/连接器 | C 通道有可验证技术证据 | S1 | G5 |
| S4 研究机构/专业媒体 | 视许可而定 | L2/L3 证据与背景 | S1 | G5 |

工期说明：上述为单人次序工作的量级估计，误差约 ±50%，不是交付承诺。S0 结束后按实际来源数量与许可结论重新估算；R5、S2、S3 可并行，缩短总工期。每个阶段的验收以其"独立交付价值"为准，不以"为下一阶段做好准备"作为完成标准。

阶段范围控制（防止过度设计）：

- R1 只做确定性事件关联 + 可定位 fact 的 Claim/Evidence 回填，不做语义聚类，不增加逐篇模型调用。
- R2 只对数值类主张做确定性核验；文本类主张的支持关系留待核验规则稳定后再评估。
- R3 之前不建立 Benchmark Corpus 的全量体系，只保留最小陷阱样本集。
- 每个阶段结束时若发现无法独立交付价值，应缩小范围，而不是引入新的模块。

---

## 4. S0 工作分解（当前阶段，只读）

> 进度（2026-11-01）：S0-1、S0-2、S0-3 已完成，基线已冻结；P0 调查已冻结并通过最终评审
> （`docs/S0_SOURCE_COVERAGE_AUDIT.md` §7）。下一阶段为 SEC EDGAR + EIA 接入设计评审
> （`docs/INTEGRATION_DESIGN_SEC_EIA.md`，G-D1 已关闭）；实施前条件 1–4 完成、条件 5 为 NOT_VERIFIED；
> **SEC/EIA 独立通道第一阶段已获授权（G-D2，2026-11-01，仅数据获取/规范化/存储/质量验证），不包含接入现有
> LLM/评分/日报**；R0 未启动，S0-5 与 P1/P2 未开始。

### 4.1 步骤

| # | 工作 | 方法 | 产出 |
|---|---|---|---|
| S0-1 | 来源盘点 | 只读 SQL + 配置解析；按规范化名称与 `meta.source_id` 双向核对 | 每源：文章数、去重事件数、已分析数、失败数、证据分布、通道归属 |
| S0-2 | 采集能力审计 | 阅读 `freshrss_client.py`、`fulltext.py`、`page_monitor.py`、`datasets.py`；确认超时、重试、配额、robots 行为 | 能力/限制清单 |
| S0-3 | 覆盖缺口分析 | 按 A/B/C 与 L0–L5 交叉统计 | 通道-层级缺口矩阵 |
| S0-3b | 来源价值评估 | 按 §4.3 对每个候选来源做三项独立评价 | 来源价值评分表 |
| S0-4 | 候选来源调研 | 逐项查官方文档，按 access / terms / value / integration 四阶段标注；权利分存储、商业、再分发、历史四项 | 候选来源比较表 + 权利矩阵 + P0 横向覆盖矩阵 |
| S0-5 | 技术栈评估 | 按 §12 表格逐项判断 | 推荐/不推荐清单 |
| S0-6 | 治理与谱系设计 | 定义字段与转载识别规则 | 字段表 + 谱系规则 |
| S0-7 | 指标定义 | 按 PRD §8 细化公式、周期、限制 | 指标定义表 |
| S0-8 | 连接器架构 | 见 §13 | 架构设计（接口、配置、存储、失败隔离） |
| S0-9 | 分批接入计划 | 见 §14 | 批次、复杂度、依赖、许可前置 |
| S0-10 | 输出报告 | 汇总以上 | `docs/S0_SOURCE_COVERAGE_AUDIT.md` |

### 4.2 调研核验模板

每个候选来源必须记录：

```
source_id / 名称 / 类型 / 用途层级
官方文档 URL、条款 URL（访问日期）
认证方式、配额、是否收费、免费套餐限制
历史数据可用性（起始年份、是否可批量下载）
更新频率、数据延迟
许可：存储 / 再发布 / 商业使用
实现复杂度（低/中/高）与依赖
核验状态：verified | docs_only | unverified | needs_approval
```

### 4.3 来源价值评估（三项独立）

每项证据来源必须分别回答以下三个问题，不得合并成一个"来源好不好"的判断：

| 维度 | 问题 | 判定方式 | 反例（不计分的情况） |
|---|---|---|---|
| Coverage | 覆盖什么信息领域、地区与通道？ | 官方说明 + 抽样核验；映射到 L0–L5 与 A/B/C | 挂名"经济"但只发软文 |
| Signal Yield | 在当前采集频率下，能持续产生多少**独立事件**？ | 用样本期（建议 30 天）实际条目估算；R1 前只能给"可识别事件条目"的代理值，并标注 proxy | 同一稿源被多家转载多篇 |
| Evidence Value | 能否提供原始数据、原始公告或可定位证据？ | 抽样检查是否有一手文件/数据接口/正文可定位 | 只有汇总评论，无原始出处 |

评分规则：

- 每项分 `high / medium / low / unknown` 四级，必须附证据说明（文档地址、抽样日期、样本量）。
- **不得用抓取成功率代替 Signal Yield，也不得用文章数量代替 Evidence Value。**
- 首批接入要求：三项均不为 `low`，且至少一项为 `high`；单项突出但其他未知的来源进入观察批，不直接进入生产。
- 评估结论写回来源登记表的 `review_status` 与 `priority`，并注明评估日期与样本期。

### 4.4 S0 退出标准

- 每项外部结论标注为：已验证事实 / 官方文档说明 / 待验证 / 需批准。
- 不得出现"估计的文章数"或"推测的配额"。
- 每个候选来源都有 Coverage / Signal Yield / Evidence Value 三项结论，代理指标必须标注 proxy。
- 工作区只新增文档，不出现代码、数据库、依赖变更。
- 报告获批后才进入 R0 设计冻结。

---

## 5. R0 工作分解（运行可靠性与发布门禁）

> 状态：设计草案，待 S0 结论出来后确认阈值与 HOLD 行为并冻结（G2），冻结前不实施。
> 独立交付价值：模型故障时不再发送误导性日报；失败可归因、可追溯。

### 5.1 根因（2026-11-01）

1. `analyzer._call` 单次调用、无传输重试。
2. `cli.py` 仅在运行开始检查健康，中途不复查、无熔断。
3. `send_decision` 只在"全失败"时拦截。
4. `digest.decision_headline` / `empty_reason` 只处理 `analyzed==0`，部分失败被渲染为"无信号"。
5. 失败记录无原因分类，`runs` 无覆盖率与发布状态。

### 5.2 改造清单

| 文件 | 改动 | 测试 |
|---|---|---|
| `opportunity_radar/analyzer.py` | 连接类错误 3 次退避重试（2/5/10s）；超时最多重试 1 次；4xx 不重试；异常携带 cause 与 attempts | `tests/test_analyzer.py` |
| `opportunity_radar/model_service.py` | 提供运行中健康复查接口（复用 `health_ok`） | `tests/test_model_service.py` |
| `opportunity_radar/cli.py` | 首次传输失败后复查健康；不可达则熔断，剩余文章记 `not_attempted`；覆盖率计算；发布状态判定；HOLD 不发送 | `tests/test_cli.py` |
| `opportunity_radar/digest.py` | 部分失败标题与原因；System Notes 披露覆盖率/失败原因；`_validate_report` 增加披露断言 | `tests/test_digest.py` |
| `opportunity_radar/store.py` | `analysis_failures` 增 `cause`/`attempts`；`runs` 增 `publication_status`/`coverage`/`failed_causes`（ADD COLUMN） | `tests/test_store.py` |
| `opportunity_radar/config.py`、`.env.example` | `OR_LLM_RETRY_ATTEMPTS`、`OR_LLM_RETRY_BACKOFF`、`OR_PUBLISH_MIN_COVERAGE`、`OR_PUBLISH_HOLD_BELOW` | `tests/test_config.py` |
| `opportunity_radar/admin_server.py` | 状态页显示发布状态与覆盖率 | `tests/test_admin_server.py` |
| `tools/e2e_verify.py` | 新增故障注入模式：中途断开、全失败、部分失败 | `tests/test_e2e_verify.py` |

### 5.3 状态矩阵

| 场景 | 判定 | 行为 |
|---|---|---|
| 模型启动时不可用 | 退出 3 | 不发信（现有行为保持） |
| 中途断开，熔断 | HOLD | 不发订阅邮件；本地报告与运行记录保留 |
| 全部失败 | analysis_failed / HOLD | 不发信（现有行为保持并统一） |
| coverage ≥ 0.8 | PASS | 正常发送 |
| 0.5 ≤ coverage < 0.8 | PASS_WITH_LIMITATIONS | 发送并在正文披露 |
| coverage < 0.5 | HOLD | 不发信 |
| 完整运行、无信号 | PASS | 正常发送 |
| 证据门禁未通过（逐条） | 条目 filtered | 运行级不受影响 |

### 5.4 R0 验收

1. 模型不可用时不发送正常日报。
2. 中途断开时熔断，不持续撞连接。
3. 全部分析失败进入 HOLD。
4. 完整运行且无信号仍正常发布。
5. 正常路径无回归（423 项测试全绿）。
6. 所有失败可按原因追溯，运行有覆盖率与发布状态。
7. coverage < 1 时报告必须披露覆盖率与失败原因。

---

## 6. R1 工作分解（Event / Claim / Evidence）

### 6.1 数据模型（附加式）

```sql
-- 事件
events(event_id TEXT PRIMARY KEY, event_key TEXT UNIQUE, event_type TEXT,
       title_norm TEXT, first_seen_at TEXT, last_seen_at TEXT,
       status TEXT, merged_into TEXT, rules_version TEXT, created_at TEXT)
-- 事件-文章
event_articles(event_id TEXT, article_key TEXT, relation TEXT,
               assignment TEXT, confidence REAL, created_at TEXT,
               PRIMARY KEY(event_id, article_key))
-- 证据（独立实体，stable id；一条证据可支撑多条主张）
evidences(evidence_id TEXT PRIMARY KEY, article_key TEXT, source_id TEXT,
          quote TEXT, locator_json TEXT, evidence_kind TEXT,
          source_family TEXT, independence TEXT, created_at TEXT)
-- 主张（核验所需字段在 R1 即入库，R2 只负责判定）
claims(claim_id TEXT PRIMARY KEY, article_key TEXT, event_id TEXT,
       fact_ordinal INTEGER, subject TEXT, predicate TEXT,
       value_num REAL, value_text TEXT, unit TEXT, currency TEXT,
       region TEXT, period TEXT, comparison TEXT, denominator TEXT,
       seasonality TEXT, revision TEXT, kind TEXT, quote TEXT,
       locator_json TEXT, verification_state TEXT, rules_version TEXT,
       created_at TEXT)
-- 主张-证据
claim_evidence(claim_id TEXT, evidence_id TEXT, support TEXT,
               independence TEXT, locator_json TEXT,
               PRIMARY KEY(claim_id, evidence_id))
-- 事件纠错（追加式）
event_corrections(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT,
                  action TEXT, payload_json TEXT, actor TEXT, created_at TEXT)
```

附加列：`articles.source_id`、`articles.connector`、`articles.external_id`。
迁移：`PRAGMA user_version` 递增；迁移前备份数据库；只读路径不迁移。

### 6.2 事件关联策略（保守优先）

原则：**宁可标为 `unknown`，不可错误合并。** 聚合率不是目标，精确率（precision）才是；不得为提高聚合率放宽阈值。

事件定义：同一主体 + 同一次行动/变化 + 同一时间窗。缺任一项即不是同一事件。

分级规则（按顺序执行，命中即停）：

1. 规范 URL 或外部 ID 相同 → `same_story`（无需模型）。
2. 标题规范化完全一致且内容哈希相同 → `same_story`（沿用现有 `event_key` 行为）。
3. 保守规则候选：主体实体集合高度重叠 + 事件类型一致 + 72 小时窗口 + 稀有词重叠超过阈值 → 标记 `candidate`，默认按 `related_not_same` 处理，**不自动合并**。
4. 其他情况 → `unknown`，保持为独立事件。

明确不合并的情形：

- 同一企业的不同公告（投资、财报、人事）。
- 同一政策的不同阶段（宣布、生效、修订）。
- 同一技术成果的不同载体（论文、企业新闻稿、GitHub 发布）→ 记为 `derived_from`，不合并事件。
- 同类事件的连续发生（不同国家同月降息）。

关系类型：`same_story`、`duplicate_wire`、`follow_up`、`background`、`derived_from`、`related_not_same`、`unknown`。

模型判定：仅用于 `candidate` 边界样本，默认关闭；启用时记录模型版本与判定理由，并接受抽检。

人工纠错：合并/拆分写 `event_corrections`，追加式，不覆盖历史。

评估：基准样本上以 precision 为主指标，recall 为观察指标；不设"聚合率提升"作为验收目标。

### 6.3 回填

- 从 `analysis_sections`（kind='fact'，status='located'）先生成 `evidences`（引文 + 定位 + 来源），再生成 Claim 骨架并关联证据。
- 同一引文在去重后只保留一个 `evidence_id`；不同文章中的相同引文视为不同证据（来源不同），由 `source_family`/`independence` 区分。
- v4 旧记录（38 条）不回填 Claim，仅保留原分析。
- 回填幂等：证据以 `(article_key, normalized_quote)` 唯一，Claim 以 `(article_key, fact_ordinal)` 唯一。

### 6.4 来源独立性

- 登记表新增谱系字段（PRD §6.2）。
- `multi_source_coverage` 改为要求 ≥2 个独立来源族；同族或未知不计。
- `EVIDENCE_AND_LANES.md` 的状态说明同步更新。

### 6.5 验收

- ONS 重复条目能聚合；无关标题不误合并。
- 重复运行不产生重复事件/Claim。
- 197 条可定位 fact 全部生成可回溯 Claim。
- 旧日报、旧分析、reviews 不受影响。

---

## 7. R2 工作分解（Evidence Verification）

| 文件 | 改动 |
|---|---|
| `opportunity_radar/schema.py` | 解析 v6：校验 claim 字段的枚举与类型（字段自 R1 起已入库）；不合规降级为偏差，不整篇丢弃 |
| `prompts/analyst.md` | 升级 v7，明确 claim 字段契约与"不能引用即为推断" |
| `opportunity_radar/verify.py`（新增） | 主体归一化、指标枚举、数值容差、单位换算、期间与口径校验、引文支持判定 |
| `opportunity_radar/evidence.py` | 修复 `content_basis` 未读 `retrieval_status`；引文最小信息量门槛；正文留存策略 |
| `opportunity_radar/claims.py`（R1 引入） | 冲突检测、独立性聚合 |
| `opportunity_radar/digest.py` | 已核验/未核验/冲突在报告中分开展示 |

核验状态：`verified` / `rejected` / `conflicted` / `unverifiable` / `pending`。

陷阱样本（必须拒绝）：

- 5% → 5 个百分点。
- 2025 年收入 100 亿 → 2026 年收入 100 亿。
- 季度数据跨年同比误作环比。
- 同一新闻稿转载计为独立证据。
- 无法定位的引文伪装为事实。

验收：陷阱样本全部不通过；未核验主张不进入事实结论；正文/摘要来源不能伪装为正文证据。

---

## 8. R3 工作分解（Editorial Intelligence）

- 评分输出拆为 `signal_score`、`evidence_score`、`editorial_priority`；原 `score` 保留兼容字段。
- 新增 `editorial_decisions` 表：run、条目、优先级、理由、规则版本、时间。
- `source_cap` 只影响分发，不改写评分与优先级。
- 跨期承载：deferred 条目进入待办池，可在后续期次重新评估。
- 解决 ISSUE-001：扩展/映射 `policy_change`、`political_event`；以 100 条样本统计合规率。
- 事件重复抑制：同一事件跨日只保留一条主条目，其余为进展记录。
- 报告披露：分数旁显示解释；高重要性 + 低证据必须显式标注。

---

## 9. R4 工作分解（Multi-period Publication）

| 产物 | 数据来源 | 关键要求 |
|---|---|---|
| Weekly Intelligence | 7 日 events、claims、dataset_observations | 不读日报文本；跨日进展识别；与上周对比 |
| Monthly Research | 专题证据集合 | 研究问题→假设→证据→反面证据→结论→局限 |
| 历史时间线 | events + event_articles | 可回溯到原始文章与定位 |
| 图表 | dataset_observations | 标注来源、分母、时间范围、口径 |

报告类型写入 `runs` 扩展字段与归档 manifest；邮件主题区分。

---

## 10. R5 工作分解（Economic Data Engine）

1. `dataset_observations(dataset_id, period, value, unit, retrieved_at, revision, source_url)`。
2. 修订快照：同一期间保留多条，标记超期/替换关系，不覆盖。
3. 确定性计算模块（YoY、MoM、QoQ、MA、指数变化、百分点变化、滚动波动、历史区间）。
4. 异常检测（阈值与滚动 Z-score，规则化参数）。
5. 图表由数据重新生成（内联 SVG）。
6. 与事件关联：`event_dataset_links` 或 Claim 的 `dataset_id` 引用。
7. 先接入已批准数据集（Eurostat），再按 S0 清单扩展；每个数据集先完成许可核验。

---

## 11. R6 工作分解（Automated Quality & Backtesting）

- Benchmark Corpus 目录与清单：`data/benchmark/`（不入库）或 `tests/benchmark/`（小样本入库）。
- 样本类型与来源见 CLAUDE.md §7.1；每条样本记录预期结果与来源出处。
- 回归运行器：固定模型版本、提示词版本、规则版本，输出指标表。
- 30/90 天回测：基于归档 `items.json` 与数据库快照。
- 版本对比报告：新增通过、新增失败、回归、耗时变化。
- 每周质量报告：来源健康度、失败率、覆盖率、证据通过率；缺失指标标 NOT_MEASURED。

---

## 12. 技术栈评估（S0 §3）

| 工具 | 解决问题 | 是否引入 | 理由 | 建议阶段 |
|---|---|---|---|---|
| httpx | 并发 HTTP、连接池 | 暂不 | `urllib` 已满足顺序请求；并发需求未证实 | S1 复评 |
| tenacity | 通用重试 | 暂不 | R0 用 30 行标准库即可覆盖 | R0 不引入 |
| feedparser | 直接解析 RSS | 暂不 | 订阅由 FreshRSS 管理；直连 Feed 时复评 | S1 复评 |
| trafilatura | 正文抽取 | 暂不 | 当前 `full_text_fetch` 全关；正文许可未核验 | R2 后复评 |
| Scrapy | 大规模爬取 | 不引入 | 来源数量小、许可约束强，框架收益低 | — |
| Playwright | JS 渲染页面 | 暂不 | 仅少数官方页面需要；先以 page_watch 链接监测替代 | S4 复评 |
| DuckDB | 分析型查询 | 暂不 | 当前数据量 SQLite 足够 | R6 复评 |
| sklearn TimeSeriesSplit | 时序交叉验证 | 不引入 | 当前不做预测模型 | — |
| Promptfoo | 提示词评估 | 不引入 | Node 工具链；用 Python 基准运行器替代 | R6 |
| Evidently | 模型漂移监测 | 不引入 | 无在线模型监控需求 | — |
| Pandera | DataFrame 校验 | 不引入 | 项目不使用 DataFrame | — |
| pytest | 测试框架 | 暂不 | 现有 unittest 423 项稳定；迁移无收益 | 复评 |

结论：运行期保持纯标准库；仅引入 uv 作为环境与依赖管理工具（非运行期依赖）。

---

## 13. Source Connector 架构设计

### 13.1 分层

```
config/sources.csv        身份与治理（谁、许可、层级、谱系）
config/connectors.csv     检索配置（怎么取、端点、配额、认证变量名）
opportunity_radar/connectors/
    base.py               Connector 协议与共享工具（限速、超时、robots）
    freshrss.py           现有 FreshRSS Fever API
    json_api.py           通用 JSON API（Eurostat/BEA/BLS/World Bank 等）
    gdelt.py              事件发现
    openalex.py / crossref.py / arxiv.py / github.py
    edgar.py              SEC EDGAR
```

### 13.2 接口

```python
class Connector(Protocol):
    connector_id: str
    source_id: str
    evidence_tier: str        # L0–L5
    rate_limit: RateLimit

    def discover(self, window: Window, limit: int) -> list[RawItem]: ...
    def fetch_body(self, item: RawItem) -> Body | None: ...   # 可选
```

`RawItem` 统一字段：`source_id`、`external_id`、`url`、`title`、`published`、`summary/excerpt`、`language`、`content_hash`、`retrieved_at`、`retrieval_status`、`extra`。

### 13.3 运行时规则

- 逐连接器隔离：单源失败不影响其他源；失败按来源记录。
- 限速：登记表 `max_requests_per_day` + 连接器内最小间隔。
- 许可：`review_status != approved` 的连接器不执行。
- robots：页面类抓取先读 robots.txt，401/403/429 不重试、不绕过。
- 幂等：`article_key = sha256(url)`；`external_id` 作为每源唯一键。
- 存储：文章入库绑定 `source_id`、`connector`、`external_id`；结构化数据进 `dataset_observations`。
- 熔断：复用 R0 的失败原因分类与熔断策略。

### 13.4 与现有代码的衔接（2026-11-01 修订：独立存储方案）

**原方案已废止。** 本节此前写的是"`cli.py` 的抓取段从 `FreshRSSClient` 直连改为连接器调度，
保持 `articles` 入库契约"，与 §13.5 边界 1 直接冲突：新来源一旦写入 `articles`，会经事件去重、
多来源佐证与 `--render-only` 重渲染影响现有日报，并污染 `runs` 的熔断判断。

第一阶段采用**独立通道**：

| 项 | 决策 |
|---|---|
| 运行入口 | 独立 module、独立进程，**不被 `cli.main()` 调用** |
| 数据存储 | **独立 SQLite 文件** |
| 数据表 | 独立 schema / 表，不写 `articles`、`analyses`、`analysis_history`、`analysis_sections`、`runs` |
| 与 `cli.py` 的关系 | 不改动；RSS 抓取段仍是 `FreshRSSClient` |
| 与 `fulltext.py` 的关系 | 不复用 |
| 与 `datasets.py` 的关系 | 字段设计可参考，不复用其运行路径 |
| RSS 日报 | 不接入、不改变 |
| LLM 分析与评分 | 默认不接入、不改变 |

理由：企业财务事实与能源时间序列不是新闻文章。复用 `articles` 模型会强迫它们进入标题哈希去重、
来源独立性与编辑评分体系，既改变现有链路，也无法表达 fact / observation 的结构差异。

### 13.5 独立通道边界（实施前条件 5，2026-11-01）

只读代码审查结论（`docs/INDEPENDENT_CHANNEL_AUDIT_2026-11-01.md`）：

| 断言 | 判定 | 依据 |
|---|---|---|
| A. 现有 RSS → LLM → 评分 → 日报链路不依赖独立来源数据，独立表不会自动进入正常分析与日报 | `PASS` | `digest.py` 无 DB 访问；分析循环只遍历本次抓取的 `articles`；`list_analyses` 只读 `articles`/`analyses` |
| B. 新来源故障与现有 RSS 任务完全隔离 | `NOT_VERIFIED` | 尚无独立通道实现与运行故障测试 |
| **合并** | **`NOT_VERIFIED`** | 未登记 PASS_VERIFIED |

**七项实施边界**

1. 独立表与命名空间：不得写入 `articles`、`analyses`、`analysis_history`、`analysis_sections`、`runs`。
2. 独立入口与独立计划任务，不放在 `cli.main()` 的任何 `try` 块内。
3. 优先使用独立 SQLite 数据库文件；共用时须 `journal_mode=WAL` + `busy_timeout` 并验证并发写。
4. 独立配置，不与 `freshrss_feed_id` 混用。
5. 默认不进入现有 LLM 分析流程，需显式开关。
6. 独立记录运行状态，不写入 `runs`。
7. 不修改 `evidence.py`、`scoring.py`、`config/scoring.toml`。

**与 §13.4 的冲突：已解决（2026-11-01）。** §13.4 已改写为独立存储方案，与边界 1 一致；
原有的"连接器调度 + 保持 `articles` 入库契约"写法已标注废止。第一阶段授权见
`docs/IMPLEMENTATION_AUTHORIZATION_2026-11-01.md`。

运行隔离、并发安全、超时与故障注入属于**实施阶段验收**，不属于本轮已完成事项。

---

## 14. 来源接入分批

| 批次 | 内容 | 前置 | 复杂度 | 说明 |
|---|---|---|---|---|
| S1-a | 连接器框架 + `source_id` 绑定 + 谱系字段 | R1 schema | 中 | 不含新来源 |
| S1-b | L0/L1 官方：Eurostat（已批准）、BEA、ONS、Federal Reserve、BLS、World Bank、IMF、SEC EDGAR | 许可核验 | 中–高 | 优先结构化数据；FRED 需 API key |
| S2 | 事件发现：GDELT 公共接口；Event Registry / NewsAPI 仅评估（免费套餐不得用于生产） | 许可/配额核验 | 中 | 先做只读事件发现，不绕付费墙 |
| S3 | 学术与技术：OpenAlex、Crossref、arXiv、GitHub REST | 条款核验 | 低–中 | 服务 C 通道 |
| S4 | 研究机构与专业媒体：官方 RSS / 公开页面 | 许可核验 | 高 | 不得绕过登录与付费墙；以 RSS 与公开索引为主 |

每一批次开始前必须完成：条款 URL 记录、许可结论、配额与成本、失败与限速设计、`review_status=approved`。

批次顺序服从 S0 审计确认的缺口优先级（`docs/S0_SOURCE_COVERAGE_AUDIT.md` §2.3）：

- P0：中国与亚洲、产业政策与监管、制造业/汽车/机器人/新材料、企业经营与财报、能源。S1-b 的 L0/L1 官方源
  只是其中一部分；中国/亚洲官方门户、亚洲交易所披露、能源与产业协会需要单独成批。
- P1：全球宏观、欧洲（非英国）、AI/半导体/算力/数据中心、学术与技术证据、市场供需。
- P2：咨询与产业研究、工业软件与 CAE、商业机会与用户痛点。P2 不删除现有来源，只暂缓扩展。

不按层级数量或 API 易用性排序；每个批次必须能说明它补上了哪一项此前无法获得的信息。

---

## 15. uv 环境迁移（S0 设计，R0 前后执行）

现状：`.venv` 由 `venv` 创建；`pyproject.toml` 的 `requires-python` 为 `>=3.11`；无 `uv.lock`；未固定 uv 版本。

五个相互独立的对象必须分开记录：

| 对象 | 作用 | 本项目做法 |
|---|---|---|
| Python 版本约束 | 声明可运行的 Python 范围 | `pyproject.toml` 的 `requires-python`；用 `uv python pin` 生成 `.python-version` 记录实际开发版本 |
| uv 版本约束 | 保证 lock 与命令行为可复现 | 在 `docs/OPERATIONS.md` 记录安装方式与版本号；CI 固定同一版本 |
| 依赖锁文件 | 锁定依赖解析结果与来源，**不锁定 Python 解释器** | `uv lock` 生成 `uv.lock` 并入库；即使运行期无第三方依赖也保留，用于固定解析结果与 requires-python |
| 项目虚拟环境 | 实际运行环境 | `uv sync` 创建/更新 `.venv`；保留旧环境用于回退 |
| 缓存目录 | 避免缓存散落、避免污染其他项目 | `UV_CACHE_DIR` 是**进程环境变量**，uv 不读取项目 `.env`；必须在 shell 配置、Windows 计划任务或 CI 中显式设置 |

执行步骤：

1. 安装 uv（用户本机，项目外），不在项目内执行全局 pip。
2. `uv python pin` 记录实际版本（当前开发环境 3.13.14；CI 覆盖 3.11/3.12）。
3. `UV_CACHE_DIR` 指向固定目录（例如 `D:\Project\.uv-cache`）；在 `docs/OPERATIONS.md`、计划任务环境与 CI 中分别设置。`.env.example` 只作说明，不能假设 uv 会自动读取。
4. `uv lock` 生成 `uv.lock`，提交入库。
5. `uv sync` 重建 `.venv`；保留原 `.venv` 一周作为回退。
6. 脚本中的 `.venv\Scripts\python.exe` 改为 `uv run python`；计划任务若无法继承环境变量，应在任务定义中显式设置 `UV_CACHE_DIR` 与 PATH。
7. CI 增加 `uv sync --locked` 与 `uv run python -m unittest`；仍不引入第三方运行期依赖。

验收：全新克隆在设定 `UV_CACHE_DIR` 后仅凭 `uv sync --locked` 可复现环境；`uv --version` 与文档记录一致；运行期依赖仍为空；不使用全局 pip。

注意：`uv.lock` 不等于"锁定 Python 安装版本"，也不保证跨机器使用同一解释器；解释器版本由 `.python-version` 与 `requires-python` 共同约束。

---

## 16. 迁移与回滚

1. 迁移前复制数据库到 `data/archive/opportunity_radar.pre-<version>-<timestamp>.sqlite3`。
2. 单事务执行附加式 DDL；`PRAGMA user_version` 记录版本。
3. 迁移函数幂等；重复执行不重复建表/加列。
4. 只读连接（`--render-only`）不触发迁移。
5. 回滚：停止任务 → 还原备份 → 回退代码。附加式变更允许旧代码忽略新表。

---

## 17. 测试策略

| 层级 | 内容 |
|---|---|
| 单元 | 现有 423 项 + 新增模块；覆盖正常、边界、非法输入 |
| 陷阱样本 | 数值/单位/期间/口径/转载/无定位引文 |
| 故障注入 | 模型断开、全失败、超时、5xx、磁盘失败 |
| 端到端 | `tools/e2e_verify.py` 两次运行模式（正常 + 注入故障） |
| 回归 | 每次迁移与规则变更后重跑全量；归档报告可重渲染 |
| 回测 | 30/90 天固定样本；版本对比 |

要求：每阶段测试必须包含"失败路径"，不得只测成功路径。

---

## 18. 风险登记

| 编号 | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| RK-1 | 模型吞吐低（11 tok/s） | 高 | 运行时长、阶段延期 | 限制新增模型调用；确定性规则优先 |
| RK-2 | 模型服务不稳定 | 中 | 误发布/失败 | R0 重试、熔断、覆盖率门禁 |
| RK-3 | 外部 API 许可不明确 | 高 | 来源无法接入 | S0 逐项核验；默认 blocked |
| RK-4 | 官方来源产出低 | 中 | A 通道内容不足 | 连接器接入；调整配额与频率 |
| RK-5 | 事件聚类误合并 | 中 | 错误情报 | 规则保守；纠错追加记录；基准样本 |
| RK-6 | 旧数据兼容 | 低 | 历史丢失 | 附加式迁移；不虚构 Claim；备份 |
| RK-7 | uv 迁移影响定时任务 | 中 | 运行失败 | 分步切换；保留回退路径 |
| RK-8 | 单人维护的知识负担 | 中 | 文档漂移 | CLAUDE.md 为唯一指导；每阶段更新 |

---

## 19. 审批门

| 门 | 需要批准的内容 | 状态 |
|---|---|---|
| G0 | 设计一致性修订（PRD / 实施计划 / CLAUDE.md 对齐） | 已完成（§21） |
| G1 | S0 审计报告（来源价值评估、许可结论、连接器设计、分批顺序） | 已完成（P0 冻结） |
| G-D1 | SEC EDGAR + EIA 接入设计评审 | 已关闭（2026-11-01，v0.8） |
| G-D2 | SEC/EIA **独立通道第一阶段**实施授权（仅数据获取、规范化、存储、质量验证） | 已批准并完成验收（10/10） |
| G2 | R0 设计冻结（阈值、HOLD 邮件行为、重试策略） | 已冻结（阈值 0.8 / 0.5） |
| G3 | R0 实施 | 已完成，真实模型故障注入验证通过 |
| G4 | R1 数据模型与迁移方案 | 已批准并分批交付（Batch 1–4） |
| G5 | 来源批次接入（逐批，含许可与成本） | 待批准（当前语料覆盖不足是首要缺口） |
| G6 | R2 核验规则与提示词版本 | 待批准 |
| G7 | R3 优先级体系与配额策略 | 待批准 |
| G8 | R4/R5/R6 启动 | 待批准 |

未获批准不得跨阶段实施；不得以"设计已完成"代替实现与验收。

---

## 20. 交付物清单

| 交付物 | 位置 | 状态 |
|---|---|---|
| 设计一致性修订记录 | 本文件 §21 | 已完成 |
| 指导文件 v1.0 + S0 阶段 | `CLAUDE.md` | 已更新 |
| 产品需求文档 | `docs/PRD.md` | 本次新增 |
| 实施计划 | `docs/IMPLEMENTATION_PLAN.md` | 本次新增 |
| S0 审计报告 | `docs/S0_SOURCE_COVERAGE_AUDIT.md` | 第一步已完成（盘点/缺口/重复） |
| R0 实施与测试 | 代码 + `tests/` | 待批准 |
| R1–R6 实施 | 代码 + `tests/` + 文档 | 待批准 |
| 来源接入批次报告 | `docs/SOURCE_CONNECTORS_<批次>.md` | 待 S0 后 |

---

## 21. 设计一致性修订记录（2026-11-01）

本轮只修订文档，不修改代码、数据库或依赖。修订依据是用户对 PRD 与实施计划的一致性审查。

### 21.1 审查指出的问题与处理

| # | 问题 | 原状 | 处理 | 涉及位置 |
|---|---|---|---|---|
| 1 | Claim 与 Evidence 模型不完整 | `claim_evidence` 引用 `evidence_id`，但没有 Evidence 实体；Claim 的核验字段被推迟到 R2 | 新增 `evidences` 表（稳定 ID、引文、定位、来源族、独立性）；Claim 核验所需字段（币种、地区、分母、季调、修订）在 R1 即入库，R2 只负责判定 | PRD §5.3/§6.1；本文件 §6.1/§6.3/§7 |
| 2 | 事件聚类方案不够严谨 | 标题 + 实体 + 72 小时 + 稀有词，隐含"能可靠识别同一事件" | 改为保守分级规则：命中即停；候选默认不合并；明确四类不合并情形；允许 `unknown`；以 precision 为主指标，不设聚合率目标 | 本文件 §6.2 |
| 3 | uv 环境描述不准确 | 称 `uv.lock` 锁定 Python 与工具链；把 `UV_CACHE_DIR` 写入 `.env.example` 即视为生效 | 拆成五个独立对象（Python 版本、uv 版本、锁文件、虚拟环境、缓存目录）；明确 uv 不读取项目 `.env`，需在 shell / 计划任务 / CI 显式设置 | 本文件 §15 |
| 4 | S0 只调研来源，未验证信息价值 | 候选表只覆盖 API 能力与许可 | 增加三项独立评价：Coverage / Signal Yield / Evidence Value；代理指标必须标注；首批接入设门槛 | PRD FR-S9；本文件 §4.3/§4.4 |
| 5 | 存在过度设计风险 | 阶段目标偏向"为后续铺路" | 增加"每个阶段必须独立可用"原则；路线图增加"独立交付价值"列；里程碑按可独立使用的产物重排 | PRD §3 原则 8、§10；本文件 §3 |

### 21.2 审查中发现的其他不一致

| # | 不一致 | 处理 |
|---|---|---|
| 6 | PRD 说 R2 增加 claim 字段，R1 的 SQL 却没有这些字段 | 字段移入 R1；R2 只做校验与判定 |
| 7 | 原先写"S0 与 R0 设计并行"，同时又写"S0 报告批准后进入 R0" | 统一为：设计一致性修订 → S0 → R0 设计冻结 → R0 实施 |
| 8 | "12–16 周"被写成确定工期 | 改为量级估计（误差约 ±50%），S0 结束后重新估算 |
| 9 | 里程碑缺少设计一致性与 R0 冻结 | 新增 M0（一致性）与 M2（R0 设计冻结） |
| 10 | 指标表引用 `claim_evidence`，但没有证据实体 | 指标改以 `claims + evidences` 为数据来源 |

### 21.3 仍需后续解决（不阻塞本轮）

1. R0 阈值（0.8 / 0.5）与 HOLD 邮件行为仍需在 G2 冻结时确认。
2. Signal Yield 在 R1 完成前只能给出代理值，必须标注 proxy。
3. Benchmark Corpus 尚未建立，相关指标保持 NOT_MEASURED。
4. 候选来源的 API 能力、配额与许可全部待 S0 核验；本文件不含未验证结论。

### 21.4 本轮未做的事

- 未修改任何生产代码、数据库、配置或依赖。
- 未创建新的实施阶段，未批准 R0 或 S1。
- 未扩大文档范围：只修订既有 PRD、实施计划与 CLAUDE.md 中相互矛盾的部分。

# 开放工程问题（2026-10-23）

> 这些是 E2 实验中暴露、但**不属于** actionability 字段本身的问题。
> 单独记录、单独验证；不并入评分字段实验，也不通过放宽校验来"解决"。

## ISSUE-001 模型输出的 `category` 枚举覆盖不足

**状态**：Open · 影响：每条这类文章整轮分析失败 · 优先级：高

**证据**（三轮一致，非随机）：

| 条目 | 原文 | 模型输出 `category` | 轮次 |
|---|---|---|---|
| `r019` | 英国 AI 部长表态 | `policy_change` | 1/2/3 全部失败 |
| `r034` | 以色列政治 | `political_event` | 1/2/3 全部失败 |

`policy_change` 与 `political_event` 语义上都是合理的分类，但不在
`schema.CATEGORIES = {customer_pain, small_business, market_change, service_opportunity, distribution, other, unknown}` 内，
因此 `parse_model_json` 抛 `Invalid category`，重试后仍失败，整条被丢弃。

**为什么不能靠放宽 schema 解决**：分类枚举是评分与路由的输入，随意接受新值会让未知类别静默进入通道；
但把语义正确的输出判为失败，也会系统性丢失政策/政治类内容——这正是当前信源结构想补的部分。

**下一步（择一，需单独评审）**：

1. 扩展枚举（例如增加 `policy_change`、`political_event`），同步修改提示词、评分映射、测试与历史兼容；
   需重新跑基线，确认不会改变既有条目的通道分布。
2. 在提示词中要求"无法归入现有类别时使用 `market_change` 或 `other`，并在 uncertainties 说明原因"，
   然后统计 100 条样本的合规率与人工映射质量。
3. 若推理服务支持受约束解码（grammar/JSON schema），在服务端约束枚举；仍需保留应用层校验。

**跟踪指标**：合规率、因 `category` 失败的比例、按来源/主题的失败分布。**不得**与 actionability 的 AUC 混在一起报告。

## ISSUE-002 排序改进与展示量脱节

**状态**：Open · 影响：读者实际看到的内容 · 优先级：中

**证据**：

- A 通道离线复核：importance 的 AUC 0.782，总分 0.718；但 `priority` 精确率只有 38.5%。
- 第二轮：24 条达到 watch/priority，`source_cap` 只放行 7 条；3 条可行动被延后，1 条噪声（足球）进入展示。
- 实验中的配额模拟同样显示：Top-13 的 5 条可行动，配额后只剩 1–2 条。

**含义**：即使排序变好，配额策略仍决定读者看到什么。不能把"排序指标提升"直接当作"读者体验提升"。

**下一步**：独立的受控验证——固定候选池与展示量，比较不同排序规则在**展示后**的可行动条数；
配额调整按产品目标（覆盖面 vs 深度）单独决策，不与评分改动捆绑。

## ISSUE-003 事件级重复尚未识别

**状态**：部分解决（R1 Batch 1–4，2026-11-01）· 影响：计数、priority 名额 · 优先级：中

**证据**：

- ONS 零售销售在第二轮出现两条（"September 2026" 与 "September 2026 time series"），标题不同、URL 不同，
  现有按 URL 与规范化标题的去重没有合并。
- NYT 的同一篇 PHP 报道同时出现在 Business 与 Technology 栏目，按 URL 去重后只保留一条，属侥幸。

**现状**：R1 已建立事件实体，规则为"规范化 URL 相同"或"规范化标题相同且在 72 小时内"；日报按事件
合并卡片，同事件的其他报道列在卡片下。P0 Batch 3 增加了 `event_candidate` 候选关联：标题相似、
共享实体、共享证据句子、事件类型与时间窗口综合判断；强候选必须有标题之外的信号，只有标题相似
最多是弱候选，候选不自动合并。真实数据 117 events / 117 articles 只得到 1 个同来源族弱候选，
没有强候选、跨来源族独立佐证或真实转载样本。仍待解决的是：

- 标题差异较大但确属同一事件的情况（需要实体或事件类型判定）；
- 事件级归并未接入评分与配额——`priority` 名额仍按文章计数；
- `multi_source_coverage` 证据状态仍按 `source_name` 计数（同一机构多个栏目会算作多个），未改用来源族/独立来源单元计数；改动会影响评分与证据状态，需单独批准。

事件级重复不再"完全没有识别"，但也不是彻底解决。

## ISSUE-004 主张流水线 N2/N3/N5 语义与组装

**状态**：主要部分已解决（Batch 16，2026-11-02）；**N0–N5 影子路线冻结，以下为已知限制** · 影响：影子 Claim 的准确率与召回 · 优先级：中

**冻结判断**：本 ISSUE 的未解决项不阻碍当前 N0–N5 影子 Claim 路线冻结。不启动 Batch 17，
不为追求参考集满分继续修改 N2/N3，不重跑 50 篇；后续如需生产启用，必须单独立项并经过 G6。

**已解决**：

- N2 GDP subject、贸易 predicate、`$0.1bn` economic relevance：Batch 15 修复，N2 指标
  21/21 disposition、20/21 subject、19/21 predicate、21/21 economic。
- N3 rate/change、period_change、3.8%、输出预算：Batch 14 修复。
- N5 终点 level：Batch 16 只改 N5，将 `$105.6bn` 的终点 level 折回 change；Claim 18→17，
  严格精确率 17/17、正文严格召回 17/18，语义（relationship_type+comparison）精确率 16/17；
  `endpoint_level_merged=1`、`endpoint_level_independent=0`、`endpoint_level_ambiguous=0`。
  独立 level、不同数值 level、rate/level 保留。

**仍未解决**：

- Google `$500bn` predicate 为 `google`（参考 `market_value`）；Intel `20%` subject `intel`
  （参考 `intel shares`）、predicate `stock_price`（参考 `share_price`）。两者 title-only，
  N5 以 `title_only_evidence` 拒绝。
- BEA Personal Income 的 `0.2%`（DPI）仍缺 N3 关系，N5 标 `relationship_unassigned`；
  这是 N3 遗漏，不在 N5 批次范围。
- GDP `2.2%` comparison 仍为 unknown（参考 annual_rate），annual_rate 未跨句延续。
- N5 语义召回 16/18，低于 Batch 12 的 17/18，原因就是上述 0.2% 漏关系。
- N2/N3 语义准确率仍只有 10 篇人工参考，不能外推到 50 篇；temperature=0 也不保证跨运行稳定。

**下一步**：单独评估 N3 对 0.2% DPI 的遗漏；title-only 的 Google/Intel 语义问题不通过硬编码修复；
N5 的 endpoint 规则只在 evidence containment 明确时生效，后续如出现多 change 包含同一 level，
保留 ambiguous。

**跟踪指标**：N2 disposition/subject/predicate/economic_relevance、N3 type/direction/comparison、
N5 严格与 relationship_type+comparison 语义口径、endpoint 合并/独立/ambiguous、重复 Claim、
误合并；必须同时报告分母与是否使用人工参考，不得外推到 50 篇。

## ISSUE-005 B 种子身份、日报展示与人工复核不可完全重建

**状态**：部分解决（Batch 12，2026-11-03）；身份与复核持久化仍开放 · 影响：B→Opportunity 映射与复核 · 优先级：中

**现象**：

- 生产库 schema v5 有 65 个 B 分析，但 B 文章只有 0 个实体 mention；`buyer_type` 是分类器提示，
  不是已识别买方。`pain_point` 是模型分析文本，不是已确认问题，因此 65 个候选的
  `canonical_key_candidate` 都为空，`canonical_key_status` 为 `blocked_missing_confirmed_problem`。
- `daily_display` 只能重放存储的 `scoring.status`；source cap 依赖一次运行中的其他 item，
  不能从数据库重建。当前映射中 5 个候选仅按 priority/watch 状态“可进入”，不能声称已经展示。
- `review_status` 只是 `b-candidates` 的输出字段，尚未持久化；没有人工接受/拒绝/要求补证记录，
  也没有 Opportunity 创建入口。65 个候选全部保持 `pending`。

**为什么不能直接解决**：

- 用标题、`summary_zh` 或 `pain_point` 生成 canonical key 会把模型文本当成已确认需求。
- 用 `buyer_type` 或来源名称当买方会制造未经证据支持的买方身份。
- 自动把重复簇合并会绕过人工复核，违反保守合并原则。

**Batch 12/13 进展**：新增 manifest 驱动的 `b-review validate|preview|apply`，只能在唯一 allowlist 的隔离 v9 库中显式创建；
创建与 links/首条 revision 同事务，初始状态固定 `signal_detected`，生产路径、硬链接、符号链接、路径穿越、
allowlist 外 v9 和 v5 目标均被拒绝。当前生产清单 65 个候选全部为 pending/none；`review_mode=ai_assisted`
只是筛选建议，不是人工批准，AI 创建申请默认被拒绝。仍然没有持久化 review_status，也没有自动确认
subject/problem/buyer；下一步是设计追加式 review 表，并在人工核对身份后再启用创建。

**跟踪指标**：身份完整数、canonical key 候选数、人工复核状态分布、疑似重复簇、每次运行的
`source_cap_replayed` 标记；必须同时报告 65 个候选的分母，不得把“可进入”写成“已展示”。

## 记录约定

- 每个问题单独验证、单独合并；不把多个变量放进同一轮实验。
- 失败与未执行项保留原状，不因主流程通过而改写成 PASS。
- 相关背景：`docs/archive/ACTIONABILITY_EXPERIMENT_RESULTS_2026-10-23.md`、`docs/archive/A_LANE_SCORING_REVIEW_2026-10-23.md`、
  `docs/archive/E2E_ROUND2_RESULTS_2026-10-23.md`。

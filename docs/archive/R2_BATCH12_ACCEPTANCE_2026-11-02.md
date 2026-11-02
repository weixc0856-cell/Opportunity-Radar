# R2 Batch 12（50 篇真实 RSS 影子运行）— 验收记录

日期：2026-11-02
结论：50 篇真实 RSS 样本全部完成 N0–N5；10 篇人工参考集完成。50 篇共 257 个 N1 候选、
51 个 claim_value、42 条 r2-v4 影子 Claim，257/257 候选有唯一处置，契约 50/50 通过。
人工参考集上：N1 召回 21/21、N2 disposition 21/21、N5 正文 Claim 召回 17/18（严格）、
标题-only 拒绝 3/3；N3 期间关联 0/18，N5 有 2 组语义重复 Claim。
**影子 Claim 不是已核实事实；50 篇的 42 条 Claim 中有 40 篇没有人工标注，不能报告精确率或召回率。**

规格：本批任务书；固定样本清单：`R2_BATCH12_SAMPLE_2026-11-02.md`；
人工参考集：`R2_BATCH12_REFERENCE_2026-11-02.md`；现行契约：`docs/CLAIM_PIPELINE.md`。

---

## 1. 固定样本

- 来源：生产 RSS 业务库 `data/opportunity_radar.sqlite3`（只读）与 FreshRSS 当前池。
- 快照：数据库 2,994,176 字节，mtime `2026-11-02T00:16:16Z`，user_version 5，文章 126；
  FreshRSS 池 567 篇；选择时间 `2026-11-02T00:40:29Z`。
- 可用性：126 篇库内文章中有 46 篇的 FreshRSS 当前正文与库内 `summary_hash` 完全一致；
  9 篇正文已更新（保留双哈希）；其余 71 篇已不在当前 FreshRSS 池或正文不足 200 字符，未用重复文章补足。
- 选中：**50 篇唯一 URL/唯一内容哈希/唯一标题**；46 篇精确匹配 + 4 篇内容更新。
- 选择规则：全部精确匹配文章 + 按数字密度排序的更新文章补足 50；不选 SEC/EIA 独立库；
  不重新抓取网页；样本清单哈希 `37f527638cc40ef9a43f9906308e26d0685384ecde188cc2e082210f9e08f267`。
- 来源分布：BBC Business 4、BBC Technology 8、BEA News 3、HN Ask 2、HN Show 2、
  NVIDIA Newsroom 4、NYT Business 2、NYT Technology 5、OpenAI Community 1、ParaView 8、
  SALOME 1、SimScale 8、preCICE 2。
- 数字密度（每千字符数字字符数）：最小 11.08、中位 54.12、最大 143.85；包含数字密集与稀疏、
  新闻/政府统计/企业/技术论坛/社区帖子。
- 清单与 URL 见 `R2_BATCH12_SAMPLE_2026-11-02.md`；正文与双哈希在本地
  `data/claim-pipeline/batch12/sample.json` / `manifest.json`。

## 2. 10 篇人工参考集

独立于 N2/N3 输出，按原文标题与 RSS 正文建立；详见 `R2_BATCH12_REFERENCE_2026-11-02.md`。

- 10 篇：BEA 个人收入/贸易/GDP；BBC Google $500bn、BBC 科技支出 $1tn；
  NYT Intel 20%/$16.5bn；NYT Anthropic（无经济数字）；NVIDIA Vera Rubin（无数字）；
  OpenAI 功能请求（URL 数字）；SimScale 技术求助（URL 数字）。
- 标注 21 个带单位/百分号的数字表达；其中 18 个有正文证据并应生成 Claim；
  3 个是标题-only（Google $500bn、BBC $1tn、Intel 20%），应被 N5 以 `title_only_evidence` 拒绝。
- 未标注范围：URL/图片 id、版本号、引用编号、裸整数；不计入 N1 召回分母，但用于检查
  N2/N5 是否错误地当成经济数字。

### 2.1 分层指标（仅这 10 篇，不外推）

| 指标 | 结果 |
|---|---|
| N1 候选召回（21 个标注数字） | **21/21（100%）** |
| N2 disposition（claim_value 且 resolved） | **21/21（100%）** |
| N2 subject 语义正确 | 20/21（95.2%） |
| N2 predicate 语义正确 | 19/21（90.5%） |
| N2 subject+predicate 同时正确 | 18/21（85.7%） |
| N2 对照组的误报 claim_value | 1（NVIDIA NVL72 → `vehicle_count`；N4/N5 未组装） |
| N3 有关系的标注数字 | 21/21（100%） |
| N3 relationship_type 完全一致 | 20/21（95.2%） |
| N3 direction 完全一致 | 20/21（95.2%） |
| N3 comparison 完全一致 | 18/21（85.7%） |
| N3 period 与原文一致（18 个明确期间的正文 Claim） | **0/18（0%）** |
| N5 assembled Claims | 21 |
| 正文应生成 Claim 的召回（严格 subject/predicate） | 17/18（94.4%） |
| 正文应生成 Claim 的召回（仅按数值/单位/关系） | 18/18（100%） |
| N5 Claim 精确率（严格，重复与 subject 错误计错） | 18/21（85.7%） |
| N5 去重后的唯一 Claim 精确率 | 18/19（94.7%） |
| 标题-only 拒绝 | 3/3 |
| 对照组生成的 Claim | 0 |
| Claim 证据定位 | 21/21（100%） |
| r2-v4 契约校验 | 21/21 |

### 2.2 典型案例

- **正确**：BEA 贸易 `$105.6bn` 的 change/level 两条 Claim 关系、方向和证据各自独立；
  BEA 个人收入 `0.2 percent at a monthly rate` 得到 `monthly_rate`；Intel 20% 标题-only 被拒绝。
- **N2 错误**：
  - Intel `$16.5 billion` 的 subject 为 `revenue` 而不是 `intel`（指标被当成了主体）；该 Claim 仍被
    N5 接受，是本次最明确的语义错误。
  - Google `$500bn` 的 subject/predicate 为 `google value`/`google_value`，参考为 `google`/`market_value`。
  - Intel `20%` 的 predicate 为 `plunge_rate`，方向词进入了指标名；标题-only 已被 N5 拒绝。
  - NVIDIA `NVL72` 的 URL/型号数字被 N2 标为 `claim_value` / `vehicle_count`（对照组误报），
    N4 `ambiguous_numeric`，N5 未生成 Claim。
- **N3 错误/缺口**：
  - 18 个正文 Claim 的期间全部未关联，`period_raw` 为空；N4/N5 没有补造。BEA 标题/正文明确有
    September/July/August/third quarter，说明是 N3 漏记而非原文缺失。
  - GDP `2.2 percent` 的 `annual_rate` 没有从上一句的 "annual rate" 延续，comparison 落为 unknown。
  - DPI `0.2 percent` 被判为 `rate`（参考为 change）；这是分类口径差异，语义上可讨论。
- **N5 缺陷**：
  - 2 组语义重复 Claim：trade `$105.6bn` 的 change 与 comparison 关系、GDP `3.4%` 的 change 与
    comparison 关系生成相同 r2-v4 字段；N5 去重键包含 `relationship_type`，因此没有去重。
  - Intel revenue 的 subject 错误没有被 N5 的契约校验发现（字段齐全，语义错误）。
- **输入边界**：多篇 RSS 摘要只有标题/导语，NVIDIA/BBC/Anthropic 等正文没有经济数字；URL/图片
  编号成为 N1 候选。当前最大瓶颈是 RSS 正文长度，而不是数字扫描器。

## 3. 50 篇 N0–N5 分层统计

### A. N0 / N1

| 指标 | 数值 |
|---|---:|
| N0 成功 / 失败 | 50 / 0 |
| N1 成功 / 失败 | 50 / 0 |
| N1 原子候选 | 257 |
| expression_groups | 31 |
| unclassified_numeric | 53 |
| 数字字符未覆盖 | 0 |
| 候选类型 | currency 17、scalar 130、date 14、percentage 9、period 11、identifier 12、magnitude 1、unclassified_numeric 53、quantity 6、time 3、ordinal 1 |
| N1 原文偏移还原 | 所有段落/句子 `text[start:end]` 与 N1 测试一致；50 篇 coverage.uncovered = 0 |

N1 在 10 篇人工参考集上召回 **21/21**；50 篇没有逐篇人工数字标注，不能对其余 40 篇报告召回率。
257 个候选中只有 26 个是显式金额/百分比（17 currency + 9 percentage）；130 个 scalar 和 53 个
unclassified 多来自 URL、图片 id、版本号和技术参数，说明当前样本的 RSS 摘要不是数字密集型经济文本。

### B. N2

| 指标 | 数值 |
|---|---:|
| claim_value | 51 |
| context_only | 169 |
| non_claim | 31 |
| ambiguous | 2 |
| unresolved | 4 |
| missing_result | 1（`model_omitted_candidate`，程序补 unresolved） |
| success / partial / failed | 43 / 7 / 0 |
| 模型批次 / 调用 | 71 / 71 |
| prompt / completion tokens | 98,276 / 21,032 |
| JSON 重试 | 0 |
| 节点耗时 | 2,396.8s（最慢 69.7s） |

N2 在 10 篇参考集上 disposition 21/21；subject 语义 20/21、predicate 19/21、两者同时 18/21。
主要错误见 §4。N2 把版本号、年龄、技术参数等非经济数字判为 `claim_value` 的情况在 50 篇中可见
（例如 pySMESH `5.1`、OpenGL `25.3`、`opacity = 0.5`、`died at 101`），这是当前 Claim 精确率的
最大来源；这些文章没有人工标注，故只报告案例，不给出精确率。

### C. N3

| 指标 | 数值 |
|---|---:|
| 关系 | 54 |
| 类型 | change 14、level 30、comparison 3、rate 4、range 3 |
| assigned / ambiguous / unresolved | 50 / 0 / 1 |
| success / partial / blocked / failed | 40 / 10 / 0 / 0 |
| 模型批次 / 调用 | 18 / 18 |
| prompt / completion tokens | 38,537 / 4,907 |
| JSON 重试 | 0 |
| 节点耗时 | 744.6s（最慢 110.3s） |
| 关系带 period 候选或 period_raw | **0 / 54** |
| 多关系候选（同一候选出现在多条关系） | 4 |

N3 在 10 篇参考集上：有关系 21/21；type 20/21；direction 20/21；comparison 18/21；
**period 0/18**。BEA 标题/正文明确有 September/July/August/third quarter，N3 没有关联，
N4/N5 也没有补造。GDP `2.2 percent` 的 `annual_rate` 未从上一句延续。

### D. N4

| 指标 | 数值 |
|---|---:|
| 标准化记录 | 56 |
| normalized / partially_normalized | 32 / 17 |
| invalid_relationship（range） | 4 |
| ambiguous_numeric | 2 |
| missing_semantics | 1 |
| unsupported_unit / unresolved | 0 / 0 |

- 金额均保留 value、unit、scale、currency 分离；没有发现重复数量级换算或擅自补单位。
- `%` 与 `pp` 分开；50 篇中 percentage_point 未产生错误 Claim。
- period/baseline 未补造；17 条 partial 主要来自 period 缺失和 comparison unknown。
- range 关系按 r2-v4 表达能力不足被标 invalid_relationship（4 条记录），没有强行组装。

### E. N5

| 指标 | 数值 |
|---|---:|
| input_candidates | 257 |
| accepted_candidates | 37 |
| assembled_claims | 42 |
| context_only | 169 |
| non_claim | 31 |
| rejected | 11 |
| ambiguous | 4 |
| unresolved | 4 |
| relationship_unassigned | 1 |
| normalization_failed | 0（所有标准化失败归入 rejected/unresolved/ambiguous） |
| duplicate_claim（当前键） | 0 |
| 语义重复组 / 多余 Claim | **3 / 3** |
| 契约校验通过文章 | 50/50 |
| 证据定位 Claim | 42/42 |
| 无证据 Claim | 0 |

42 条 Claim 分布在 17 篇文章；33 篇没有生成 Claim（没有 claim_value、N2 unresolved/ambiguous、
title-only、range 或标准化失败）。所有 257 个候选都有唯一处置，`coverage_complete = true`。
不能生成 Claim 的原因：title-only 7、range 4、N2 unresolved 4、candidate 无数值 2、
ambiguous numeric 2、无关系值 2、N2 ambiguous 2（同一条目可能同时出现在 rejected/unresolved 列表）。

语义重复：trade `$105.6bn` 的 change/comparison、GDP `3.4%` 的 change/comparison、
SimScale `0.4` 的 comparison/level 生成相同 r2-v4 字段；N5 去重键包含 `relationship_type`，
因此未按 Claim 字段去重。这是本批发现的确定性缺陷，未在测量过程中修改。

50 篇的 42 条 Claim 只有 10 篇有人工参考；**不报告 50 篇总体精确率或召回率**。
人工参考集的严格指标见 §2.1。

## 4. 错误分类与根因

| 类别 | 数量/案例 | 根因 |
|---|---|---|
| N1 未发现标注数字 | 0/21（10 篇参考） | — |
| N1 把 URL/版本/编号当经济数字 | 53 unclassified、130 scalar 中的多数 | RSS 摘要含大量 URL/图片 id；N1 按“发现所有数字”设计，不判断经济意义 |
| N2 未识别候选 | 1 `model_omitted_candidate` | 模型漏掉一个候选；程序补 unresolved，未静默丢弃 |
| N2 主体错误 | Intel `$16.5bn` subject=`revenue`，应为 intel | 模型把指标当作主体；N5 契约只检查字段存在，不检查语义 |
| N2 指标错误 | Google `google_value`、Intel `plunge_rate` | 指标名混入主体/方向词；谓词守卫只覆盖部分方向词 |
| N2 非经济数字误判为 claim_value | pySMESH `5.1`、OpenGL `25.3`、`opacity=0.5`、`died at 101` | N2 没有“经济相关性”门；契约不区分经济/技术数值 |
| N3 期间缺失 | **0/54 关系带 period，参考集 0/18** | 模型未引用 context_only 期间；无确定性期间关联；N4/N5 遵守不补造 |
| N3 比较口径错误/缺失 | GDP `2.2%` annual_rate→unknown；DPI `0.2%` rate vs change | 跨句上下文未延续；rate/change 分类口径差异 |
| N3 模型漏处置 | 1 `model_said_assigned_without_a_relationship` | 模型自称 assigned 但未给出关系；程序显式 unresolved |
| N4 单位/数量级错误 | 未发现（10 篇参考与 50 篇 Claim 抽查） | — |
| N5 语义重复 Claim | 3 组/3 条（trade 105.6、GDP 3.4、SimScale 0.4） | 去重键包含 `relationship_type`，相同 r2-v4 字段未去重 |
| N5 主语错误未拦截 | Intel revenue | 契约校验只保证字段结构，不验证语义 |
| 契约表达能力不足 | range 4 条被拒；baseline/direction 仅在 trace | r2-v4 无 range/baseline/direction 字段；未改契约 |

### 根因与优先级

1. **输入边界（最高）**：RSS 摘要经常只有标题/导语；50 篇中只有 26 个显式金额/百分比。多篇
   NVIDIA/BBC/Anthropic 正文没有经济数字，URL/图片 id 成为主要数字来源。任何下游节点都无法
   恢复未进入 RSS 摘要的正文数字。
2. **N2 经济相关性（高）**：N2 的契约是“数值主张”，不是“经济主张”；版本号、年龄、技术参数
   可以合法通过。要提升 Claim 精确率，需要独立的“经济相关性/可交易性”判断，而不是继续改
   N2 的总提示词。
3. **N3 期间关联（高）**：54 条关系全部无 period；这是系统性缺口。需要明确的期间候选引用规则
   或确定性期间关联（在原文明确时），并保持不补造原则。
4. **N5 去重键（中）**：应只按 r2-v4 Claim 字段去重，`relationship_type` 只进入 trace。
5. **N2 主体/指标（中）**：Intel revenue、Google predicate、Intel 20% predicate 是模型错误；
   需要固定样本和提示词/守卫迭代，不在本批修改。
6. **契约表达（中）**：range/baseline/direction 的表示不足；修改 r2-v4 需单独审批，不在本批。

本批没有在运行过程中修改 N2/N3 提示词、规则或节点版本；以上是测量结论与后续建议。

## 5. 生产隔离

- 样本选择只读生产库；节点结果只写 `data/claim-pipeline/node_runs.sqlite3` 与运行目录；
  未写生产 claims/analyses 表，未改评分、日报、邮件、R0 门禁，未启用 v7，未触碰 SEC/EIA 库。
- 影子 Claim 未暴露给订阅用户；不是已核实事实。

## 6. Git

本批提交在 `feat/r2-batch12-shadow-50`；PR、CI 与合并结果见最终执行报告。

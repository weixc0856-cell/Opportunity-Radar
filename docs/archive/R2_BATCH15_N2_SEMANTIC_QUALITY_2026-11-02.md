# R2 Batch 15（N2 主体与谓词语义）— 验收记录

日期：2026-11-02
基线：`main` 合并 Batch 14 后的提交 `287c177`（包含 `58dda36`）
分支：`feat/r2-batch15-n2-semantic-quality`
结论：N2 在 10 篇人工参考集上从 20/21 disposition、17/21 subject、16/21 predicate、
20/21 economic_relevance 提升到 **21/21、20/21、19/21、21/21**；GDP subject、贸易 predicate 与
`$0.1bn` economic relevance 三个目标案例均修复。N5 严格精确率 18/18、正文严格召回 17/18，
高于 Batch 14 的 15/18 与 14/18；但按 relationship_type + comparison 同时匹配的语义口径是
16/18 与 16/18，仍有未被严格指标覆盖的重复/口径问题。

本批只改 N2；N0/N1 使用 Batch 14 固定输入，N3/N4/N5 代码与提示词不变。未重跑 50 篇，
未改 r2-v4、生产链路、评分、日报或数据库。

---

## 1. 根因

### 1.1 GDP subject

原文先写 `real gross domestic product (gdp)`，后文用 `real gdp`。模型分别输出：

- `real gross domestic product (gdp)`（保留括号缩写）；
- `real gdp`（使用缩写）。

两者是同一指标的不同文本表达，但 N2 没有文档内的缩写规范化。修复：

- 从文档本身提取 `full phrase (acronym)` 与 `acronym (full phrase)`；
- 用缩写字母与全称单词的首字母匹配得到 expansion（`gdp` → `gross domestic product`）；
- 去掉 subject 末尾的括号缩写和所有格 `'s`；
- 保留 `subject_raw`（模型原始输出）和 `normalized_acronym` 偏差；
- 没有硬编码 GDP；`gross national product (gnp)` 在夹具中独立展开为
  `gross national product`。

### 1.2 贸易 predicate

模型对 `$12.8bn` 输出 `deficit_amount`（Batch 14）或 `deficit_increase`（Batch 15 的一次运行），
对 `$31.0bn` 输出 `surplus`。这些是泛化/局部 measure，不是具体的 `goods_deficit` /
`services_surplus`。原文是：

`The goods deficit increased $12.8 billion in August to $136.6 billion.`

修复：

- predicate 含 `amount/rate/value/level/total` 泛化词时，用 subject 的 measure slug 重建；
- predicate 只剩一个词且是 subject 单词的真子集时（`deficit` ⊂ `goods deficit`，
  `surplus` ⊂ `services surplus`），用 subject slug 重建；
- 多词且具体的 predicate（`trade_deficit`）不被拆成完整 subject slug；
- 保留 `predicate_raw`、`predicate_source` 和偏差；
- 不根据金额大小推断指标，不使用 `$12.8bn` 特例。

### 1.3 `$0.1bn` economic relevance

Batch 14 的模型理由是 “less than $0.1 billion is a comparison threshold”，因此判为
`context_only / non_economic`。完整原文是：

`The services surplus increased less than $0.1 billion in August to $31.0 billion.`

同句已有经济主体 `services surplus` 和变化动词 `increased`，所以这个 bounded amount 仍然是
同一指标的变化额。修复分两层：

1. 提示词：bounded quantity 在经济从句中仍是 economic claim value；subject/measure 不清楚时用
   ambiguous；
2. 程序：仅当同句恰好有一个 economic claim_value 时，才把 bounded amount 提升为 claim_value，
   复制该 subject/predicate；多个 subject → ambiguous；没有经济 claim → 不提升。没有按货币符号
   或金额大小推断。

最终运行中模型直接输出 `claim_value/economic`（`promoted_bounded_amounts=0`）；单变量
`relevance_program` 实验在模型仍判 context_only 时成功提升 1 条，证明程序回退可用。

## 2. 单变量实验

固定输入：Batch 14 的 N0/N1，10 篇参考集。基线为 Batch 14 固定 N2（`n2-v2`）。
N2 参数：Qwen3-30B-A3B、temperature 0、max_tokens 1600。

| # | 变量 | 文章 | disposition | subject | predicate | economic |
|---|---|---|---|---:|---:|---:|
| 0 | Batch 14 基线 | 10 篇 | 20/21 | 17/21 | 16/21 | 20/21 |
| 1 | subject 规范化（程序） | BEA GDP | 2/2 | 2/2 | 2/2 | 2/2 |
| 2 | predicate 规范化（程序） | BEA Trade | 5/6 | 5/6 | 5/6 | 5/6 |
| 3 | economic relevance 提示词 | BEA Trade | 6/6 | 6/6 | 3/6 | 6/6 |
| 4 | economic relevance 程序提升 | BEA Trade | 6/6 | 6/6 | 6/6 | 6/6 |
| 5 | 最终组合（提示词 + 三个程序规则） | 10 篇 | **21/21** | **20/21** | **19/21** | **21/21** |

说明：

- 实验 1 只开 subject 规则；GDP 3.4/2.2 都变为 `real gross domestic product`，`subject_raw` 保留。
- 实验 2 只开 predicate 规则；`$12.8bn` 从 `deficit_increase/amount` 变为 `goods_deficit`；
  `$0.1bn` 仍是 context_only。
- 实验 3 只改提示词；`$0.1bn` 成为 economic claim，但模型在同轮把 `$31.0bn` predicate 写成
  `surplus`，说明提示词不能替代 predicate 规范化。
- 实验 4 用 `n2-v2` 提示词 + bounded promotion；6/6 全对，`promoted_bounded_amounts=1`。
- 实验 5 是最终 `n2-v3`：prompt hash `91325af3db2d64fb`，24 批，40,437 prompt /
  8,679 completion tokens，1,127.5 秒；规则源码 hash `b77ba7fd429eecde`。

实验文件在本地 `data/claim-pipeline/batch15/`；历史 Batch 12/13/14 结果未覆盖。

## 3. Batch 12 / 13 / 14 / 15 对比

### N2（10 篇人工参考集）

| 指标 | Batch 12 | Batch 13 | Batch 14 | Batch 15 |
|---|---:|---:|---:|---:|
| disposition | 21/21 | 20/21 | 20/21 | **21/21** |
| subject | 20/21 | 17/21 | 17/21 | **20/21** |
| predicate | 19/21 | 16/21 | 16/21 | **19/21** |
| economic_relevance | 未设字段（参考均为 economic） | 20/21 | 20/21 | **21/21** |

### N5（同一 n5-v2；10 篇参考集）

| 指标 | Batch 12 | Batch 13 | Batch 14 | Batch 15 |
|---|---:|---:|---:|---:|
| Claim 数 | 21 | 17 | 18 | 18 |
| 严格精确率（value/unit/subject/predicate） | 18/21（85.7%） | 14/17（82.4%） | 15/18（83.3%） | **18/18（100%）** |
| 正文严格召回 | 17/18（94.4%） | 13/18（72.2%） | 14/18（77.8%） | **17/18（94.4%）** |
| 严格 + relationship_type + comparison | 未单列 | 未单列 | 14/18 | **16/18** |
| title-only 拒绝 | 3/3 | 3/3 | 3/3 | 3/3 |

**不要把 18/18 当作完整语义精确率。** Batch 15 的贸易 `$105.6bn` 同时有 change（period_change）
与 level 两条 Claim，严格指标按 value/subject/predicate 都算正确，但 level 是多余的；
按 relationship_type + comparison 同时匹配，精确率和召回都是 16/18。Batch 12 的严格指标同样
包含重复 Claim，跨批比较必须看口径。

## 4. 逐项案例

| 案例 | 参考 | Batch 14 | Batch 15 |
|---|---|---|---|
| GDP `3.4%` subject | real gross domestic product | real gross domestic product (gdp) | **real gross domestic product**（raw 保留） |
| GDP `2.2%` subject | real gross domestic product | real gdp | **real gross domestic product**（raw 保留） |
| 贸易 `$12.8bn` predicate | goods_deficit | deficit_amount | **goods_deficit**（raw 保留） |
| 贸易 `$0.1bn` | claim_value / economic / services surplus / services_surplus | context_only / non_economic | **claim_value / economic / services surplus / services_surplus** |
| 贸易 `$31.0bn` predicate | services_surplus | services_surplus | **services_surplus** |
| Google `$500bn` predicate | market_value | market_value | `google`（仍错误；title-only 被 N5 拒绝） |
| Intel `20%` subject/predicate | intel shares / share_price | intel's shares / price | `intel` / `stock_price`（仍错误；title-only 被 N5 拒绝） |

`$0.1bn` 的 N2 证据为：

`the services surplus increased less than $0.1 billion in august to $31.0 billion.`

N5 生成了 `services_surplus`、0.1、USD billion、2026-08 的 Claim；N3/N4/N5 未修改。

## 5. 失败与未解决

- **N2 subject 20/21**：Intel `20%` 的 subject 为 `intel`，参考为 `intel shares`。这是 title-only
  数字，N5 仍以 `title_only_evidence` 拒绝；本批不针对单个案例硬编码。
- **N2 predicate 19/21**：Google `$500bn` 为 `google`（参考 `market_value`）；Intel `20%` 为
  `stock_price`（参考 `share_price`）。两者都是 title-only，未生成 Claim。
- **N5 语义口径**：贸易 `$105.6bn` 的 level Claim 与 change Claim 都保留，因为 comparison 不同；
  严格指标不惩罚它，但语义指标计为多余。N5 的语义去重键包含 comparison，本批不修改 N5。
- **N5 召回 17/18**：BEA Personal Income 的 `0.2 percent`（DPI）没有 N3 关系，N5 标
  `relationship_unassigned`；N2 已判 claim_value，这是 N3 的遗漏，不在本批范围。
- **GDP `2.2%`** 的 comparison 仍为 unknown，参考 annual_rate；annual_rate 未跨句延续。
- N2/N3 语义准确率仍只有 10 篇人工参考，不外推；temperature=0 也不保证跨运行稳定。

## 6. 测试与生产隔离

- 全量 **872 项通过**。
- 新增：文档内缩写展开（含独立 `gnp` 夹具）、所有格、泛化/局部 predicate、bounded amount
  提升、单变量实验基线。
- 未修改 N1/N3/N4/N5 代码或提示词；未改 r2-v4；未写生产 claims/analyses；未改评分、日报、
  邮件、R0 门禁；SEC/EIA 未触碰；v7 未启用；G6 未批准；影子 Claim 不是已核实事实。

## 7. Git

分支 `feat/r2-batch15-n2-semantic-quality`；提交、PR、CI 与合并状态见最终执行报告。

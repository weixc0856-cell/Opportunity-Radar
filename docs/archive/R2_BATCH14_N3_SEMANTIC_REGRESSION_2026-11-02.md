# R2 Batch 14（N3 语义回归定向修复）— 验收记录

日期：2026-11-02
基线：`main` 合并 Batch 13 后的提交 `a1a6bba`（包含 `b3d8a20`）
分支：`feat/r2-batch14-n3-semantic-regression`
结论：N3 rate/change 与 period_change 的参考集指标已恢复并略高于 Batch 12；`3.8 percent` 在
固定输入下由模型关系或一次覆盖重试分配，未用程序默认补关系。N5 仍低于 Batch 12，原因是固定
N2 输入中的 GDP subject、贸易 `$12.8bn` predicate 与 `$0.1bn` context_only，不在本批修改范围。

本批只改 N3 及其输出预算工具；未重跑 N0/N1/N2，未重跑 50 篇，未改 r2-v4、N4/N5 实现或生产链路。

---

## 1. 根因

### 1.1 rate 与 change

旧提示词同时写了：

- “percentage is the rate … give monthly_rate/annual_rate to the percentage”；
- “A parenthetical percentage … use relationship_type=change and comparison=unknown”。

两条规则在 `0.2 percent at a monthly rate` 上直接冲突。Batch 13 的模型因此输出
`change/increase/monthly_rate`（类型是 change，comparison 又带 monthly_rate）；`0.5 percent`
没有 rate 短语时又被输出为 `rate/not_applicable/unknown`。这是提示词歧义，不是百分号或 predicate
能单独判断的问题。

修复分两层：

1. 提示词按“本句措辞”分类：显式 rate 短语、无 rate 短语的百分比变化、命名 rate/ratio 三类；
2. 程序只对模型已经产出的关系做确定性分类纠正，不创建新关系：
   - 金额后的括号百分比 + 显式 rate 短语 → `rate` + `monthly_rate/annual_rate/quarterly_rate` +
     `not_applicable`；
   - 无 rate 短语的百分比变化 → `change` + `unknown` + increase/decrease；
   - 命名 rate/ratio 且无移动 → `rate` + `level` + `not_applicable`；
   - “increased at an annual rate of 3.4 percent” 有移动、无金额括号 → 保持 `change` +
     `annual_rate` + `increase`。

### 1.2 period_change 与 unknown

旧提示词只有 `comparison` 枚举，没有把 `from … to …`、`up from …`、`to <new level>` 与
`period_change` 绑定；模型在贸易文章输出 `unknown`，后来又输出 `month_over_month`。修复：

- 提示词给出 `from $92.8 billion in July to $105.6 billion in August` 和
  `increased $12.8 billion in August to $136.6 billion` 两个正例；
- 明确 `month_over_month` 只在原文出现 “month over month / month-on-month / MoM” 时使用；
- 明确单个变化金额、没有 earlier value/from/to 时是 `unknown`，不是 `period_change`；
- 程序规则只把 `level + period_change` 改为 `level`，并清除没有期间线索的
  `change + period_change`。

### 1.3 `3.8 percent` relationship_unassigned

固定 N1/N2 下，`3.8 percent` 的 N2 是 `claim_value/resolved`。根因是 **N3 模型输出遗漏**：
Batch 13 的批次 2 只有这一个 claim_value，模型仍只返回 `candidate_dispositions: assigned` 而没有
关系；同一 prompt、同一输入在另一次运行中能返回
`rate/not_applicable/level`，并带原文 “the personal saving rate … was 3.8 percent” 证据。

加重因素：批次窗口里包含其他批次的 claim_value 候选，模型会把输出用在它们身上（随后被
`not_in_batch` 拒绝）。修复：

- payload 给每个候选加 `in_batch`，提示词明确只有 `in_batch=true` 的候选属于本批；
- 初始批次后统计“模型声称 assigned 但没有关系”的候选，做 **一次** 聚焦重试，只把缺失候选
  作为 `claim_value_ids` 再问模型；仍缺失则保持 unresolved；
- 程序不补 level/rate，不伪造证据。

本批一次运行（`exp-final5-personal.jsonl`）中覆盖重试找回了 1 个候选；最终 10 篇运行中模型直接
产出 3.8 的关系，`coverage_retries=0`。两种结果都保留，说明该遗漏是模型不稳定性，不是程序拒绝。

### 1.4 输出预算

BEA Personal Income 的 Batch 13 首个 N3 批次 completion 为 1929 tokens；`--n3-tokens 1400`
导致两个批次 JSON 截断。默认值检查与修复：

- `tools/run_n2_n3.py` 默认已是 2400；
- `tools/run_n4_n5.py` 默认从 1400 改为 2400（只用于查找同一 N3 参数）；
- `LocalAnalyzer.complete_detailed` 记录 `finish_reason`；`JsonRunner` 透传；
- N3 在 `finish_reason=length`，或没有 finish_reason 且 completion 达到 max_tokens 时，把批次标为
  `invalid_output`，写 `token_limit_reached=true`；即使 JSON 恰好可解析也不接受为 success；
- 有限预算，可配置；不通过无限增加 token 解决。

实测：

| 预算 | BEA Personal Income | 结果 |
|---:|---|---|
| 2400（默认） | 3 批 completion 1132 / 1082 / 429 | 无截断，9/9 关系 |
| 1400 | 3 批 completion 1132 / 1082 / 164 + 覆盖重试 345 | 无截断，9/9 关系；说明新 prompt 已缩短输出 |
| 200（强制） | 两个初始批次 + 重试均 JSON 截断 | `invalid_output`，节点 partial，不误标 success |

## 2. 实验

固定输入：Batch 12 的 10 篇参考集；N0/N1/N2 使用 Batch 13 冻结结果
（`data/claim-pipeline/batch14/fixed-input.json`）。只重跑 N3。Batch 13 结果保存在
`data/claim-pipeline/batch14/control-batch13/`。

| # | 变量 | 文章 | 结果 |
|---|---|---|---|
| 1 | `n3-v2` 基线（Batch 13） | 10 篇 | type 17/21、direction 17/21、comparison 14/21；0.2 change、0.5 rate、3.8 缺失 |
| 2 | rate/change 提示词（仅提示词） | BEA Personal Income | 9 条关系；type 7/9、direction 7/9、comparison 6/9；0.2 仍为 rate/level，0.5 仍为 rate；单独不足 |
| 3 | comparison 提示词（仅提示词） | BEA Trade | 8 条关系；comparison 5/6（缺 `$0.1` 是 N2 context_only）；`$105.6`/`$12.8` 均为 period_change |
| 4 | batch scope 提示词（仅提示词） | BEA Personal Income | 9 条关系；3.8 分配 rate/level，但 rate/change 仍不稳定；未单独采用 |
| 5 | 最终 `n3-v3`：提示词 + 程序规则 + in_batch + 覆盖重试 | 10 篇 | 21 条关系、10 批；type 20/21、direction 20/21、comparison 18/21；period 11/18 |

实验记录在本地 `data/claim-pipeline/batch14/exp-*.jsonl` 与对应 `.log`；每条节点输出含
prompt/schema hash、模型参数、批次 token、finish_reason 与状态。

最终运行：`n3-v3`、prompt `n3-prompt-v3`、prompt hash `444d379b2b286441`、schema `n3-schema-v2`、
model Qwen3-30B-A3B-Instruct-2507-Q4_K_M、temperature 0、max_tokens 2400。
10 篇 21 条关系，10 批，44,817 prompt / 5,058 completion tokens，591.9 秒；无 invalid_output；
程序修正 rate 4 条、comparison 3 条。

## 3. Batch 12 / 13 / 14 对比（10 篇人工参考集）

| 指标 | Batch 12 | Batch 13 | Batch 14 |
|---|---:|---:|---:|
| N3 有关系 | 21/21 | 19/21 | 20/21 |
| relationship_type | 20/21 | 17/21 | **20/21** |
| direction | 20/21 | 17/21 | **20/21** |
| comparison | 18/21 | 14/21 | **18/21** |
| period（18 个正文 Claim） | 0/18 | 11/18 关联；9/18 格式化 | **11/18 关联；9/18 格式化** |
| N5 Claim 数 | 21 | 17 | 18 |
| N5 严格精确率 | 18/21（85.7%） | 14/17（82.4%） | 15/18（83.3%） |
| N5 正文严格召回 | 17/18（94.4%） | 13/18（72.2%） | 14/18（77.8%） |
| title-only 拒绝 | 3/3 | 3/3 | 3/3 |

N3 三项回到 Batch 12 基线；N5 仍低于 Batch 12，原因不在 N3 关系类型，而在固定 N2 输入：

- 贸易 `$0.1 billion` 被 N2 判为 context_only/non_economic，N3 没有候选可建关系；
- 贸易 `$12.8 billion` 的 predicate 为 `deficit_amount`，参考为 `goods_deficit`；
- GDP `3.4%` subject 为 `real gross domestic product (gdp)`、`2.2%` 为 `real gdp`，参考为
  `real gross domestic product`。

本批不修改 N2，N5 使用同一 `n5-v2`，所以这些结构通过但语义不正确的 Claim 保留并计错。

## 4. 逐项案例

| 案例 | 参考 | Batch 13 | Batch 14 |
|---|---|---|---|
| `0.2 percent at a monthly rate` | rate / not_applicable / monthly_rate | change / increase / unknown | **rate / not_applicable / monthly_rate** |
| `0.2 percent`（DPI，括号无 rate） | change / increase / unknown | change / increase / unknown | **change / increase / unknown** |
| `0.5 percent`（PCE，无 rate） | change / increase / unknown | rate / not_applicable / unknown | **change / increase / unknown** |
| `3.8 percent`（personal saving rate） | rate / not_applicable / level | 无关系（unresolved） | **rate / not_applicable / level** |
| 贸易 `$105.6bn` | change / increase / period_change | change / increase / unknown | **change / increase / period_change** |
| 贸易 `$12.8bn` | change / increase / period_change | change / increase / unknown | **change / increase / period_change** |
| 贸易 `$0.1bn` | change / increase / unknown | N2 context_only，无关系 | 仍无关系（N2 固定输入） |
| GDP `3.4%` | change / increase / annual_rate | change / increase / annual_rate | **change / increase / annual_rate** |
| GDP `2.2%` | change / increase / annual_rate | change / increase / unknown | change / increase / unknown（annual_rate 未跨句延续） |
| BBC `$1tn` | level / not_applicable / unknown | level / not_applicable / level | level / not_applicable / level（title-only） |

`3.8%` 的关系证据为原文 `the personal saving rate … was 3.8 percent`，N3 evidence_start/end
可在 N0 原文定位；没有用程序默认 level/rate 补造。

## 5. period 与 N5 回归

- period：11/18 正文 Claim 关联期间；11/18 `period_raw` 与参考一致；9/18 有可格式化 `period`。
  与 Batch 13 相同，没有因 rate/comparison 修复而回退。无年份月份/季度仍保持 raw、`period` 为空；
  跨句不搬期间。
- 证据定位：20/21 个参考数字的关系可回到 N0 原文；唯一缺失是 `$0.1`（N2 context_only，无关系）。
  所有已生成的 N3 关系 `evidence_located=true`，最终 18 条 Claim 证据全部可定位。
- N5：18 条 Claim，18 条原始/唯一，0 重复、0 方向冲突；接受候选 17。语义精确率/召回见 §3；
  不使用结构通过代替语义正确。贸易 `$92.8bn` 的 revision 关系因无 baseline 被程序标为 unresolved，
  不再生成额外 revision Claim；该值的 level 关系保留 `revision=revised`。

## 6. 测试

- 全量 **866 项通过**。
- 新增：rate/change 四类规则、comparison 三类规则、revision baseline guard、覆盖重试、
  finish_reason/completion cap 的 invalid_output 标记。
- 未修改 N1/N2/N4/N5 代码或提示词；`analyzer.py` / `semantic_common.py` 只增加 finish_reason
  元数据透传。

## 7. 生产隔离

未写生产 claims/analyses；未改评分、日报、邮件、R0 门禁；SEC/EIA 库未触碰；v7 未启用；
G6 未批准；影子 Claim 不是已核实事实。

## 8. Git

分支 `feat/r2-batch14-n3-semantic-regression`；提交、PR、CI 与合并状态见最终执行报告。

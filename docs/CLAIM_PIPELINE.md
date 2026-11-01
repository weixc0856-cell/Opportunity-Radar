# 主张提取流水线（N0–N5）

版本：3.0 · 2026-11-02
定位：规定"文章 → 主张"这条链路怎么拆、每个节点的输入输出契约、失败语义、留存方式与验收方式。
现状：**N0–N3 已实现；N4–N5 未开始。** 生产提示词仍是 v6，v7 仍是影子，切换判定仍是
**NOT READY**，生产启用需 G6 批准。

- N0/N1 契约见本文件 §4–§5，验收见 `docs/archive/R2_BATCH8_ACCEPTANCE_2026-11-01.md`。
- N2/N3 契约见本文件 §6–§7 与 `docs/archive/R2_BATCH9_N2_N3_SPEC_2026-11-02.md`，
  验收见 `docs/archive/R2_BATCH9_N2_N3_ACCEPTANCE_2026-11-02.md`。

---

## 1. 为什么拆

一条提示词同时完成"读文章、找数字、判断主体/指标、判断变化口径、生成 Claim"时，出错无法
定位，只能反复改总提示词。拆分后的规则：**每个节点只解决一种问题。上一个节点交付确定的数据，
下一个节点只处理这些数据，不重新猜测上一个节点已经完成的事情。**

N0、N1、N4、N5 是确定性程序；N2、N3 使用本地模型，输出是待核验材料，不是事实。

## 2. 输入边界

输入是**本系统实际拿到的文本**：FreshRSS 标题与 RSS 正文（正文抓取关闭）。
- 生产分析器有 12,000 字符上限；N0 不受该限制，离线工具以 `max_content=0` 读取完整正文。
- 流水线的召回上限等于这段文本。
- N0 的 canonical text 与 `schema._normalize` 一致；N1 偏移与证据定位器同源。

## 3. 节点

| 节点 | 角色 | 只回答一个问题 | 输出 | 状态 |
|---|---|---|---|---|
| N0 | 程序 | 文本是什么，每段每句在什么位置 | 规范化文档、段落/句子 ID、偏移、哈希 | 已实现 `article_text.py` |
| N1 | 程序 | 有哪些数字表达，文本声明了哪些关系 | 原子候选 + 复合表达组 | 已实现 `numeric_candidates.py` |
| N2 | 本地模型 | 这个数字描述谁、什么指标、是否构成主张 | 每个候选的 disposition/subject/predicate/证据 | 已实现 `n2_semantic.py` |
| N3 | 本地模型 | 数字之间是什么关系 | 水平/变化/比较/区间/修订/份额/比率 | 已实现 `n3_relationships.py` |
| N4 | 程序 | 数值如何规范化 | 数值、数量级、币种、单位、期间、比较口径 | 未开始 |
| N5 | 程序 | 候选是否都被处理、Claim 是否可定位 | r2-v4 主张 + 未处理候选清单 | 未开始 |

## 4. N0 文章标准化（`n0-v1`）

输入：`article_id` / `source_id` / `title` / `content` / `content_format` / `language` /
`source_url`；兼容现有文章对象的 `title` + `summary`。

输出：`document_id`、`content_hash`、`text_hash`、`text`（标题 + 正文）、`body_start`、
`paragraphs[]`（`p0001`…）、`sentences[]`（`s0001`…）、`offset_unit=unicode_codepoint`、
`offset_convention=half_open`、`ruleset`、`content_truncated`、`stats`。

规则：`text[start:end]` 精确还原；N0 自身不截断；HTML 标签转空格、实体解码、引号/空白折叠、
小写；数字表达式不改写；段落按块级标签（HTML）或空行（纯文本）切分；句子按 `.!?。！？` 切分，
数字中的点与常见缩写不断句。无标题也无正文 → `ValueError`。

## 5. N1 数字候选（`n1-v1`）

输入 N0 输出。输出 `candidates[]` + `expression_groups[]` + `statistics`。

- 原子类型：`percentage`、`percentage_point`、`currency`、`quantity`、`scalar`、`date`、
  `period`、`ratio`、`unclassified_numeric`；另有明确状态 `magnitude`、`time`、`ordinal`、
  `identifier`。
- 候选字段：`candidate_id`（content hash + 版本 + 类型 + 位置 + 原文）、`raw_text`、
  `start/end`（N0 全文位置）、`sentence_id`/`paragraph_id`、`context`、`detection_method`、
  `detection_status`、`value/scale/unit/currency/temporal/flags/cues`、`related_candidates`。
- 复合表达：`range` / `from_to` / `increase_decrease` / `comparison` /
  `temporal_comparison`，只引用原子 ID。
- 不变量：每个十进制数字字符恰好属于一个原子（`statistics.coverage.uncovered` 为空）；
  不乘数量级；左端最长、相邻不合并；相同输入与规则得到相同 ID。
- `RULESET` 源码哈希随输出保存并进入缓存键。

## 6. N2 数字候选语义（`n2-v1`）

### 输入与批次

N0 文档 + N1 输出。程序按候选位置构造句子窗口（候选所在句完整 + 前后各一句，预算 3500 字符），
每批默认 4 个候选，一次模型调用。候选不跨 title/body，且每个候选只属于一批。

### 输出

`candidate_interpretations[]`：`candidate_id`、`disposition`、`subject`、`predicate`、
`predicate_raw`、`predicate_source`、`kind`、`reason`、`evidence_sentence_ids`、
`evidence_quote`、`evidence_start/end/field`、`status`、`deviations`。
另有 `batches[]`、`statistics`、`model`、`input_hash`、Prompt/Schema 版本与哈希、`status`。

- `disposition`：`claim_value` / `context_only` / `non_claim` / `ambiguous` / `unresolved`。
- `kind`：r2-v4 的枚举，**禁止 `system_inference`**。
- `status`：`resolved` / `ambiguous` / `unresolved`。

### 程序校验

每个输入候选恰好一个结果；缺失补 `unresolved`，重复/额外记录并忽略；枚举非法降级；
`claim_value` 缺 subject/predicate、证据无法定位、字段超长 → `unresolved`（原文保留，不截断）；
`predicate` 含方向/关系词时用 subject 规范化替换并记 `relationship_leak`，原值入 `predicate_raw`。

## 7. N3 数字关系（`n3-v1`）

### 输入

N0 + N1 + N2 输出。N2 `status` 不是 `success`/`partial` 时返回 `blocked`，不调用模型。
只对 N2 `claim_value` 且 `resolved` 的候选建立数值关系；`context_only` 可作期间/基准上下文；
`non_claim` 不得引用。

### 输出

`relationships[]`：`relationship_id`（程序生成）、`relationship_type`、`value_candidate_ids`、
`baseline_candidate_ids`、`period_candidate_ids`、`comparison_period_candidate_ids`、
`denominator_candidate_ids`、`related_expression_ids`、`direction`、`comparison`、
`seasonality`、`revision`、`period_raw`、`evidence_sentence_ids`、`evidence_quote`、
`evidence_start/end/field`、`status`、`reason`、`deviations`。
另有 `candidate_dispositions[]`（每个 claim_value 的 assigned/ambiguous/unresolved）与统计。

- `relationship_type`：`level` / `change` / `comparison` / `range` / `revision` / `share` /
  `rate` / `unknown`。
- `comparison` / `seasonality` / `revision` 严格使用 r2-v4 枚举。

### 程序校验与守卫

ID/枚举/证据校验；`value_candidate_ids` 为空的关系丢弃；`non_claim` 引用拒绝；
每个 claim_value 必须有处置；比较口径只在原文出现对应措辞且紧邻该数值时接受，否则改为
`unknown`/`level` 并记偏差（`not_stated` / `attached_to_other_candidate`）；
`change` 不得用 `comparison=level`；`period_raw` 必须能回到原文。

## 8. 留存与缓存

`pipeline_store.py` 独立、追加式 SQLite（默认 `data/claim-pipeline/node_runs.sqlite3`）：
article_id、document_id、content_hash、node_name、node_version、input_hash、output_hash、
execution_status、executed_at、params_json、tools_json、output_json。
`INSERT OR IGNORE`；失败运行带状态标记，不占成功键。

- N2 输入哈希包含 N0/N1 哈希、节点/Prompt/Schema 哈希、规则源码哈希（`RULESET`）、模型与参数。
- N3 输入哈希包含 N2 稳定哈希（排除 `seconds`/`batches`）、规则源码哈希（`RULESET`）、
  模型与参数；N2 内容或规则变化自动使 N3 失效。
- 规则源码哈希（`RULESET`）和 Prompt/Schema 哈希进入各自输入键。

## 9. Microsoft Recognizers-Text

第八批实测（PyPI 1.0.2a2，需 `emoji==1.7.0`）：无 datetime 包、无 percentage/percentage-point
识别器；`$92.8bn` 丢失数量级，`USD 12.8 billion` 丢失币种，`FY2025` 无结果；36 个样本上规则
覆盖 36/36、识别器 33/36、组合新增 0。**不引入**；自定义规则为唯一运行路径。
对比脚本：`tools/eval_numeric_tools.py`。

## 10. 与 r2-v4、v7、G6 的关系

- N0–N3 不改动 `claim_contract.py`（r2-v4）、`verify.py`（r2-v2）、`units.py`、生产提示词、
  评分与门禁。
- N4/N5 未实现：当前不产出 r2-v4 Claim，也不能声称完成文章到 Claim 的完整链路。
- v7 未启用；生产仍是 v6；G6 未批准。

## 11. 已知限制

1. 输入是标题 + RSS 正文，不是全文。
2. N2/N3 是模型判断；程序只保证引用、枚举、覆盖与比较口径的确定性守卫。
3. 比较口径守卫基于措辞与最近候选，覆盖不了所有自然语言变体；无法判断时保留 `unknown`。
4. N1 括号数字标 `ambiguous`；N3 不把 ambiguous 当确认数值。
5. 修订/季节调整只接受原文明确措辞；模型可能漏记，统计中体现为 `unknown`。
6. 模型指纹未知（llama.cpp 不提供 GGUF 内容哈希）；`seed`/`top_p` 未发送。
7. N2 精确率/语义准确率没有全量人工基准；覆盖率不是语义准确率。

## 12. 运行

```
python tools/run_n1.py --limit 50
python tools/run_n2_n3.py --limit 50 --n3-limit 15
python tools/run_n2_n3.py --fixture data/claim-pipeline/n2n3-fixtures.json
python tools/run_n2.py --limit 20
python tools/run_n3.py --limit 20
python tools/eval_numeric_tools.py
```

`run_n2_n3.py` 先跑 N2，再对前 N 篇有 claim_value 的文章跑 N3；复用已留存结果；
输出 `data/claim-pipeline/<时间戳>/`（`n2n3.jsonl`、`summary.json`、`summary.md`）。
不写生产库、不改日报、不改生产分析器。

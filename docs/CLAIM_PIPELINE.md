# 主张提取流水线（N0–N5）

版本：4.0 · 2026-11-02
定位：规定"文章 → 主张"这条链路怎么拆、每个节点的输入输出契约、失败语义、留存方式与验收方式。
现状：**N0–N5 已实现，形成离线影子链路；Claim 仍是影子 Claim，不是已核实事实。**
生产提示词仍是 v6，v7 仍是影子，切换判定仍是 **NOT READY**，生产启用需 G6 批准。

- N0/N1：`docs/archive/R2_BATCH8_ACCEPTANCE_2026-11-01.md`
- N2/N3：`docs/archive/R2_BATCH9_N2_N3_SPEC_2026-11-02.md`、`R2_BATCH9_N2_N3_ACCEPTANCE_2026-11-02.md`
- N4/N5：`docs/archive/R2_BATCH10_N4_N5_SPEC_2026-11-02.md`、`R2_BATCH10_N4_N5_ACCEPTANCE_2026-11-02.md`

---

## 1. 原则

每个节点只解决一种问题。上一个节点交付确定的数据，下一个节点只处理这些数据，不重新猜测
上一个节点已经完成的事情。N0、N1、N4、N5 是确定性程序；N2、N3 使用本地模型，输出是
待核验材料。N5 只写影子 Claim，不写生产表，也不把模型判断标记为已核实事实。

## 2. 输入边界

输入是 FreshRSS 标题与 RSS 正文（正文抓取关闭）。生产分析器有 12,000 字符上限，N0 不受该限制；
离线工具以 `max_content=0` 读取完整正文。流水线的召回上限等于这段文本。

## 3. 节点

| 节点 | 角色 | 输出 | 状态 |
|---|---|---|---|
| N0 | 程序 | 规范化文档、段落/句子 ID、偏移、哈希 | 已实现 |
| N1 | 程序 | 原子候选 + 复合表达组 | 已实现 |
| N2 | 本地模型 | 每个候选的 disposition/subject/predicate/证据 | 已实现 |
| N3 | 本地模型 | 水平/变化/比较/区间/修订/份额/比率关系与候选处置 | 已实现 |
| N4 | 程序 | 数值/单位/数量级/币种/期间/baseline 标准化记录 | 已实现 |
| N5 | 程序 | 候选完整处置 + r2-v4 影子 Claim | 已实现 |

## 4. N0 / N1（确定性头）

- N0：`document_id`、`content_hash`、`text`（标题+正文）、`paragraphs`/`sentences`（稳定 ID、
  全文与原始偏移）、`offset_unit=unicode_codepoint`、`offset_convention=half_open`；不截断、
  不改写数字。
- N1：原子类型 `percentage`、`percentage_point`、`currency`、`quantity`、`scalar`、`date`、
  `period`、`ratio`、`unclassified_numeric`（另有 `magnitude`/`time`/`ordinal`/`identifier`）；
  复合表达 `range`/`from_to`/`increase_decrease`/`comparison`/`temporal_comparison`；
  每个十进制数字字符恰好属于一个原子；不计算最终数值。

## 5. N2 / N3（本地模型）

- N2：批次 = 候选所在句完整 + 相邻句（预算 3500 字符，默认 4 个候选）；每个候选恰好一个
  `claim_value`/`context_only`/`non_claim`/`ambiguous`/`unresolved`；`claim_value` 必须有
  subject/predicate 与可定位逐字引文；predicate 关系泄漏由程序用 subject 重建。
- N3：只对 N2 `claim_value` 且 resolved 的候选建关系；`context_only` 可作期间/基准；
  `non_claim` 拒绝；N2 未成功 → `blocked`；每个 claim_value 必须有处置；比较口径必须原文出现
  且紧邻该数值；revision/seasonality 只在原文出现时保留。
- 批次记录：`input_chars`、`output_chars`、`prompt_tokens`、`completion_tokens`、`seconds`、
  `parse_retry`、`candidate_count`/`claim_value_count`、`context_chars`；工具汇总最慢批次、
  重试次数与 token 总量，用于区分请求、生成、JSON 修复和持久化耗时。

## 6. N4 数值标准化（`n4-v1`）

输入 N0/N1/N2/N3。输出 `normalized_records[]`：

- `value`（原文数值，不乘数量级）、`unit`（基单位）、`scale`（billion/million/…）、
  `currency`、`unit_string`（供 r2-v4，如 `USD billion`、`million vehicles`）、`unit_family`；
- `raw_value`/`raw_unit`/`raw_scale`；`comparison`/`seasonality`/`revision`/`direction`；
- `period`/`period_raw`/`period_candidate_ids`；`baseline`/`baseline_candidate_ids`；
  `denominator`；`source_candidate_ids`/`source_relationship_ids`；证据与 N2 解释引文；
- `status`：`normalized` / `partially_normalized` / `unsupported_unit` / `ambiguous_numeric` /
  `missing_semantics` / `invalid_relationship` / `unresolved`。

规则：数量级与币种不重复乘入；`%` 与 `pp` 不同；无单位不赋予经济单位；未知单位明确标记；
括号数字不擅自取负（记 `parenthesized_sign_not_inferred`）；`range`/`unknown` 关系不可组装；
缺失 period/baseline 保持空并记录；每个 claim_value 必须有记录（无关系 → `missing_semantics`）。
N4 不调用模型、不补造关系。

## 7. N5 完整性门禁与 Claim 组装（`n5-v1`）

输入 N0–N4。输出：

- `claims[]`：r2-v4 字段（`subject/predicate/kind/value_num/value_text/unit/unit_raw/scale/
  currency/period/period_raw/comparison/seasonality/revision/denominator/region/quote`），
  外加 `claim_id`、`status=accepted`、`deviations`、`trace`（候选、关系、N4 记录、证据定位、
  N2 subject/predicate、direction、baseline）。
- `candidate_dispositions[]`：每个 N1 候选一个处置——`claim_accepted`/`context_only`/`non_claim`/
  `ambiguous`/`unresolved`/`relationship_unassigned`/`normalization_failed`/`rejected`/
  `used_as_context`。
- `rejected_items[]`、`unresolved_items[]`、`coverage_statistics`、`contract_validation`、
  `duplicates`、`status`。

组装规则：subject/predicate/kind 来自 N2；数值/单位/数量级/币种来自 N4；关系/方向/比较/期间/
baseline 来自 N3，只用明确提供的信息。证据必须回到 N0 原文；标题单独证据 → 拒绝
`title_only_evidence`；缺 subject/predicate、value 非数值、单位/币种未知、期间非法、证据缺失 → 拒绝；
重复 Claim 只保留一条。契约校验把所有 payload 交给 `claim_contract.parse_claims`，全部通过才算有效。
coverage_complete 要求处置数与 N1 候选数相等且唯一；统计中分别给出 `input_candidates`、
`accepted_candidates` 与 `assembled_claims`，Claim 数量不是成功指标。一个候选可以参与多个
N3 关系并产生多条 Claim，因此 assembled_claims 可以大于 accepted_candidates。

`status`：N2 未成功 → `blocked`；覆盖不完整 → `failed`；所有候选为 claim_accepted/context_only/
non_claim/used_as_context 且 N4 `success` → `success`；否则 `partial`（缺失期间/比较口径等偏差
在 Claim 中可见，不伪装成完整成功）。

## 8. 留存与缓存

`pipeline_store.py` 独立、追加式 SQLite（默认 `data/claim-pipeline/node_runs.sqlite3`）：
article_id、document_id、content_hash、node_name、node_version、input_hash、output_hash、
execution_status、executed_at、params_json、tools_json、output_json。`INSERT OR IGNORE`；
失败运行带状态标记，不占成功键。

- N2/N3 输入哈希含上游哈希、Prompt/Schema 哈希、规则源码哈希、模型与参数。
- N4 输入哈希含 N0–N3 稳定哈希、N4 版本、规则源码哈希、`units.py` 源码哈希。
- N5 输入哈希含 N0–N4 稳定哈希、N5 版本、r2-v4 版本与契约源码哈希、规则源码哈希。
- 时间/耗时/重试次数不进入稳定哈希；N3 依赖 N2 稳定哈希，N5 依赖 N4 稳定哈希。
- 查找使用 `find_latest`：失败/超时/非法输出不阻止后续成功结果被复用；
  仅有指标代码变化导致输入哈希不同时，可用相同 `document_id` 复用已成功结果。

## 9. Microsoft Recognizers-Text

第八批实测（1.0.2a2，需 `emoji==1.7.0`）：无 datetime 包、无 percentage/percentage-point
识别器；`$92.8bn` 丢失数量级，`USD 12.8 billion` 丢失币种，`FY2025` 无结果；36 个样本上规则
覆盖 36/36、识别器 33/36、组合新增 0。**不引入**；自定义规则为唯一运行路径。

## 10. 与 r2-v4、v7、G6 的关系

- N0–N5 不改动 `claim_contract.py`（r2-v4）、`verify.py`（r2-v2）、生产提示词、评分与门禁。
- 第十批对 `units.py` 只做了追加式 count/duration 单位族补充（`5 million vehicles` 的直接阻断），
  没有修改既有单位、换算或核验规则。
- N5 产出的是 r2-v4 影子 Claim，尚未进入生产 Claim 表、日报或 `verify.py`；不是已核实事实。
- v7 未启用；生产仍是 v6；G6 未批准。

## 11. 已知限制

1. 输入是标题 + RSS 正文，不是全文。
2. N2/N3 是模型判断；程序只保证引用、枚举、覆盖、比较口径与单位结构的确定性守卫。
3. 已处理的 BEA 文章 N3 没有关联期间，N4/N5 保持 `period_missing`，没有补造；因此 N4/N5 为 partial。
4. 修订/季节调整只接受原文明确措辞；模型漏记时保持 unknown。
5. 标题单独证据被拒绝；固定夹具中缺少 N2 留存的文章不会产生 Claim。
6. N2/N3 语义准确率没有全量人工基准；候选覆盖率、处置完整性与 Claim 数量都不是语义准确率。
7. 七个夹具已完成 N0–N5；50 篇真实语料影子运行仍未完成，不能把夹具结果当作真实语料通过率。
8. v7 与 G6 未推进。

## 12. 运行

```
python tools/run_n1.py --limit 50
python tools/run_n2_n3.py --limit 50 --n3-limit 15
python tools/run_n4_n5.py --limit 50
python tools/run_n4_n5.py --fixture data/claim-pipeline/n2n3-fixtures.json --limit 2
python tools/run_n4.py --limit 20
python tools/run_n5.py --limit 20
python tools/eval_numeric_tools.py
```

N4/N5 工具默认复用已留存 N0–N3；N2/N3 缺失时记录 missing，不调用模型。
输出 `data/claim-pipeline/<时间戳>/`（JSONL、summary.json、summary.md），不写生产库。

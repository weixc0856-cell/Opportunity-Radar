# R2 第十一批（多关系组装核查 + 七夹具覆盖）— 验收记录

日期：2026-11-02
结论：多关系组装经真实数据核查正确；五个缺失夹具的 N2/N3 已补齐；**七个夹具全部完成 N4/N5**，
共 **31 个已接受候选、36 条 r2-v4 影子 Claim**，49 个 N1 候选全部有唯一处置，
契约校验 36/36。未调用生产链路；影子 Claim 不是已核实事实。

规格：`R2_BATCH11_FIXTURES_2026-11-02.md`；现行契约：`docs/CLAIM_PIPELINE.md`。

---

## 1. 任务 A：`$105.6bn` 多关系组装核查（BEA International Trade）

### 1.1 三个计数

| 计数 | 数值 |
|---|---:|
| N1 candidate | 8 |
| 已接受 candidate（`claim_accepted`） | 6 |
| 最终 assembled Claim | 7 |

N2：6 个 `claim_value` + 2 个 `context_only`。N3：7 条关系（change 3、level 4）。
N4：7 条标准化记录（normalized 4、partially_normalized 3）。N5：6 个候选被接受，
`$105.6bn` 参与 change 与 level 两个关系，因此产生 2 条 Claim。

### 1.2 同一候选的两条 Claim

| 项 | Claim A | Claim B |
|---|---|---|
| Claim ID | `c_ab9e5cfe3bd18e4f` | `c_bb1b7f0f5e65f13d` |
| relationship_id | `r81e4b669e2de5ede` | `r8bc8f19abb41e546` |
| N4 record | `n4_5ed402254962f087` | `n4_ef4a3c0aca9a506b` |
| relationship_type | change | level |
| direction | increase | not_applicable |
| comparison | period_change | level |
| value / unit / scale / currency | 105.6 / USD / billion / USD | 105.6 / USD / billion / USD |
| subject / predicate / kind | u.s. goods and services trade deficit / trade_deficit / fact | 同左 |
| evidence | 267–291，body | 267–291，body |
| quote | `$105.6 billion in august` | 同左 |

结论：
- 同一 N1 candidate 允许关联多个 N3 relationship；N4 为每个组合生成独立记录；N5 生成独立 Claim。
- 两条 Claim 的关系类型、方向、比较口径和来源 ID 各自独立，不是重复事实。
- 证据分别可回到 N0；subject/predicate/kind 来自 N2，未由 N4/N5 改写。
- 同一关系重复出现时 N5 去重（`duplicate_claim`）；本次 trade 没有重复关系。

## 2. 任务 B：五个夹具 N2/N3 补齐

### 2.1 运行前留存

| 夹具 | N0 | N1 | N2 | N3 |
|---|---|---|---|---|
| bea-gdp | 有 | 有 | **缺** | **缺** |
| nyt-intel | 有 | 有 | **缺** | **缺** |
| nyt-obamacare | 有 | 有 | **缺** | **缺** |
| edges | 有 | 有 | **缺** | **缺** |
| multi-metric | 有 | 有 | **缺** | **缺** |

只运行缺失的 N2/N3；N0/N1 由留存复用。真实模型运行（Qwen3-30B-A3B，temperature 0，
json_schema）：

| 夹具 | N2 状态 | N1 候选 | claim_value | context | non_claim | ambiguous | N3 状态 | 关系 |
|---|---|---|---:|---:|---:|---:|---|---:|
| bea-gdp | partial | 4 | 2 | 2 | 0 | 0 | success | 4 |
| nyt-intel | success | 2 | 2 | 0 | 0 | 0 | partial | 2 |
| nyt-obamacare | partial | 3 | 2 | 1 | 0 | 0 | success | 2 |
| edges | partial | 19 | 10 | 4 | 4 | 1 | partial | 11 |
| multi-metric | success | 3 | 3 | 0 | 0 | 0 | partial | 3 |

N2 合计 31 个候选、19 个 claim_value、7 context、4 non_claim、1 ambiguous；
N3 合计 22 条关系、19/19 claim_value 有处置、0 unresolved、证据定位 100%。

### 2.2 批次效率（实际指标）

| 节点 | 批次 | prompt tokens | completion tokens | JSON 重试 | 节点耗时 | 平均/最慢批次 |
|---|---:|---:|---:|---:|---:|---|
| N2 | 12 | 15,666 | 3,424 | 0 | 590.7s | 49.2s / 98.8s（bea-gdp，1,446/329） |
| N3 | 8 | 20,194 | 4,158 | 0 | 674.8s | 84.3s / 141.3s（edges，4,644/896，input 9,401 字符） |

诊断：
- 耗时主要来自模型 prompt 处理与生成，不在 JSON 修复（0 次重试）或持久化（N4/N5 为 0.0s）。
- 每个候选只进入一个批次；上下文只在相邻句窗口重叠，没有重复候选或重复模型调用。
- `edges` 的 N3 最慢，因为 19 个候选带来 4,644 prompt tokens 和 9,401 输入字符；这是上下文需要，
  没有通过降低语义要求削减。
- 串行调用，没有增加并发。

### 2.3 恢复与缓存

- 重跑五夹具 N2/N3：**N2 复用 5/5、N3 复用 5/5**，本次模型调用 **0**、token 0；
  已成功节点没有因重跑被覆盖。
- 七夹具 N4/N5 重跑：**N4 复用 7/7、N5 复用 7/7**，Claim 36、覆盖完整、契约通过。
- `find_latest` 跳过 failed/invalid_output/model_unavailable/timeout/schema_error；
  `find_latest_document` 仅在 `document_id` 相同（正文未变）时用于指标代码变化后的复用。
- 强制重跑使用 `retry` 参数键追加记录；失败结果使用失败状态键，不占用标准成功键。

### 2.4 运行问题与修复

第一次补齐运行全部失败：`semantic_common.JsonRunner` 使用 `time` 但缺少导入，
错误为 `NameError: name 'time' is not defined`；未写入任何节点结果。
已补导入并新增 `tests/test_semantic_common.py`（detailed 指标、plain 回退、JSON 重试），
第二次运行完成上述结果。

## 3. 任务 C：七个夹具 N4/N5

| 夹具 | N1 | N2（claim/context/non_claim/ambiguous） | N3 关系 | N4 状态 | N5 处置 | Claim | 拒绝/未决 |
|---|---|---|---|---:|---|---:|---|
| bea-personal | 10 | 9/1/0/0 | change5 level1 rate3 | 4 norm / 5 partial | 9 accepted / 1 context | 9 | — |
| bea-trade | 8 | 6/2/0/0 | change3 level4 | 4 norm / 3 partial | 6 accepted / 2 context | 7 | — |
| bea-gdp | 4 | 2/2/0/0 | change2 comparison2 | 4 partial | 2 accepted / 2 context | 4 | — |
| nyt-intel | 2 | 2/0/0/0 | change1 level1 | 1 norm / 1 partial | 1 accepted / 1 rejected | 1 | title_only_evidence |
| nyt-obamacare | 3 | 2/1/0/0 | change2 | 2 partial | 2 accepted / 1 context | 2 | — |
| edges | 19 | 10/4/4/1 | change3 comparison1 level3 range1 rate1 revision2 | 4 norm / 7 partial / 2 invalid | 8 accepted / 4 context / 4 non_claim / 2 rejected / 1 ambiguous | 10 | range×2、duplicate_claim、n2_ambiguous |
| multi-metric | 3 | 3/0/0/0 | change3 | 3 partial | 3 accepted | 3 | — |
| **合计** | **49** | **34/10/4/1** | **38** | **13 norm / 25 partial / 2 invalid** | **31 accepted / 10 context / 4 non_claim / 3 rejected / 1 ambiguous** | **36** | 见下 |

计数说明：
- **49 个 N1 候选**全部有唯一处置；`coverage_complete = true`。
- **31 个已接受候选**，**36 条 Claim**：5 个候选参与多个关系（trade `$105.6bn`；GDP 3.4%/2.2%；
  edges 3.4%/3.8%），因此 Claim 数大于接受候选数。
- **3 个 rejected 处置**：edges 的区间（2 个候选，r2-v4 无区间字段）、Intel 的标题 20%
  （`title_only_evidence`）。另有 1 条 `duplicate_claim` 记录，该候选的另一个关系已生成 Claim
  （处置仍为 accepted）。
- **1 个 ambiguous**：edges 中无法明确归属的数字；没有伪造成 Claim。
- **0 个 unresolved Claim**；N4 所有非 normalized 记录都有明确状态。

### 3.1 重点检查

- **change 与 level**：trade 的 `$105.6bn` 同时有 change 与 level 两条 Claim（见 §1）；
  N5 没有把它们合并，也没有互相覆盖。
- **percentage 与 percentage_point**：edges 的 `2 percentage points` 为 unit `pp`；
  其他百分比为 `%`。
- **monthly_rate**：只在 bea-personal 的 `0.2 percent at a monthly rate` 出现；
  GDP 的 `annual rate` 来自原文；其余没有擅自生成月度率。
- **无单位数字**：没有给 scalar 补经济单位；`5 million vehicles` 保留 vehicles/million。
- **period/baseline**：所有 Claim 的 period 为空（N3 未关联期间），N4/N5 没有补造；
  baseline 只出现在 N3 明确提供的 from-to 关系中。
- **partial 输入**：N2/N3 partial 的夹具仍保留可用 Claim，并把 title-only、range、duplicate、
  n2_ambiguous 列入拒绝/未决原因。
- **契约**：36/36 Claim 通过 `claim_contract.parse_claims`；证据全部可回到 N0。

### 3.2 质量指标说明

- 本批的“31 个接受候选 / 36 条 Claim / 49 个处置”是**处置完整性与组装结果**，
  不是 Claim 精确率，也不是 N2/N3 语义准确率。
- 影子 Claim 尚未经 `verify.py` 或人工事实核验；不得表述为已核实事实。
- 固定夹具结果不是 50 篇真实语料的通过率。

## 4. 测试

- 新增 8 项：`test_semantic_common.py`（3）、N2 批次指标（1）、N5 单候选多关系（1）、
  `find_latest`（2）、`find_latest_document`（1）。
- 全量 **840 项通过**。

## 5. 生产隔离

- 本批工具未写生产库、RSS/SEC/EIA 库。核验时生产库为 articles 126 / analyses 117 /
  claims 220 / evidences 220。与 Batch 10 的 117/108 相比，差异来自计划任务在
  2026-11-02T00:00Z 独立执行的日报运行（run 15，status=success，20 篇/10 篇分析，PASS），
  不是本批写入；claims 仍为 220。
- 未修改 r2-v4、`verify.py`、生产提示词、评分、R0 门禁、日报与邮件。
- 本批对 `analyzer.py` 只增加 `complete_detailed()` 与 `_post_response()`，生产 `analyze()`
  仍走 `_post()` 并返回同样的 content；`semantic_common`、`pipeline_store`、N5 统计字段为离线节点改动。
- 影子 Claim 未写生产 Claim 表；v7 未启用；G6 未批准。

## 6. Git

本批提交在 `feat/r2-batch11-fixtures`；PR、CI 与合并结果见最终执行报告。
未把 `data/` 运行产物提交到 Git。

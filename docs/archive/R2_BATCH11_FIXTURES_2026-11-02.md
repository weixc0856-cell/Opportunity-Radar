# R2 第十一批：多关系组装核查与七夹具 N2/N3 覆盖 — 实施规格

日期：2026-11-02
状态：本文件记录本批的实现与验收契约；执行结果见
`R2_BATCH11_FIXTURES_ACCEPTANCE_2026-11-02.md`。

---

## 1. 范围

本批不重构 N0–N5、不修改 r2-v4、不启用 v7、不接入生产链路。只做：

1. 核查 N4/N5 对“一个 N1 候选参与多个 N3 关系”的组装（重点 BEA Trade `$105.6bn`）。
2. 补齐五个夹具（bea-gdp、nyt-intel、nyt-obamacare、edges、multi-metric）缺失的 N2/N3 留存。
3. 七个夹具完成 N4/N5，并记录候选处置、Claim、原因与契约结果。

## 2. 任务 A：多关系组装核查

区分三个计数：N1 candidate 数、已接受 candidate 数、assembled Claim 数。
N5 `coverage_statistics` 明确提供：

- `input_candidates`：N1 原子数。
- `accepted_candidates`：处置为 `claim_accepted` 的候选数。
- `assembled_claims`：最终 r2-v4 影子 Claim 数。

同一候选允许参与多个 N3 关系；N4 为每个有效 candidate-relationship 组合生成独立记录；
N5 为每条记录生成 Claim，保留各自的 `relationship_id` 与 `n4_record_id`。
重复的**同一关系**只保留一条 Claim；不同关系（如 change 与 level）不去重。
证据必须分别能回到 N0；subject/predicate/kind 来自 N2，value/unit/scale/currency 来自 N4，
关系/方向/比较/期间来自 N3。若实现正确，只补测试与说明，不修改组装逻辑。

## 3. 任务 B：补齐 N2/N3 留存

先查留存：五个夹具已有 N0/N1，缺 N2/N3；不得重跑已成功的 N0/N1。
使用 `tools/run_n2_n3.py --fixture ... --article-id ...` 只运行缺失节点；已成功节点由
`find_latest` 复用，失败/超时/非法输出不阻止后续成功结果被复用。

### 批次指标

N2/N3 批次记录：`input_chars`、`output_chars`、`prompt_tokens`、`completion_tokens`、
`seconds`、`parse_retry`、`candidate_count`/`claim_value_count`、`context_chars`、状态与错误。
工具汇总：批次总数、prompt/completion tokens、重试次数、平均与最慢批次（含 article_id）。

### 恢复与缓存

- `PipelineStore.find_latest`：同一输入哈希下返回最新的可用结果，跳过 failed / invalid_output /
  model_unavailable / timeout / schema_error。
- `find_latest_document`：只有指标代码变化导致输入哈希不同、但 `document_id` 相同（正文未变）时，
  允许复用已成功结果；不得用于正文变化。
- 强制重跑（`--no-reuse`）使用新的参数键追加记录，不覆盖历史；失败结果使用失败状态键，
  不占用标准成功键。
- N2 候选复用前检查当前 N1 候选 ID 是否全部被缓存解释覆盖；N3 复用前检查
  `n2_output_hash`；N4/N5 复用前检查各自 `input_hash`。
- 不降低语义要求、不增加并发；按本地 llama.cpp 的实际处理能力串行调用。

## 4. 任务 C：七夹具 N4/N5

七个夹具：bea-personal、bea-trade、bea-gdp、nyt-intel、nyt-obamacare、edges、multi-metric。
复用 Batch 10 的 N4/N5，不重写节点。记录每篇的：

- N1 candidate 数/类型；
- N2 disposition；N3 relationship 类型/状态；
- N4 标准化状态；N5 候选处置；
- Claim 数、不能生成 Claim 的原因；
- 证据定位与 r2-v4 契约校验。

重点检查：change/level 区分、percentage/percentage_point 区分、monthly_rate 只由原文明确支持、
无单位数字不补单位、缺失 period/baseline 不补造、一个 candidate 多关系正确组装、
partial 输入保留可用 Claim 并列出未完成项。

## 5. 边界

不修改 r2-v4、生产 v6/v7 提示词、评分、日报、邮件、R0 门禁；不写生产 Claim 表；
不修改 RSS/SEC/EIA 生产数据；不引入新框架。所有结果写入独立节点留存与运行目录。
节点成功率、候选处置完整性与 Claim 准确率是三种不同指标，不得混报。

# R2 第九批（N2 + N3 语义与关系识别）— 验收记录

日期：2026-11-02
结论：**N2、N3 已实现，程序校验与单元/集成测试完成；真实本地模型在两篇 BEA 文章上完成 N2/N3。**
固定样本中的 BEA 个人收入与国际贸易文章已完成 N2/N3；GDP、Intel、Obamacare 与边界样本的
N3、以及 50 篇真实语料影子运行未完成，原因见 §7（本地模型吞吐）。
N4/N5 未实现；v7 未启用；G6 未批准。

规格：`R2_BATCH9_N2_N3_SPEC_2026-11-02.md`；现行契约：`docs/CLAIM_PIPELINE.md`。

---

## 1. 交付范围

- **N2**：`opportunity_radar/n2_semantic.py`（`n2-v1`），对每个 N1 原子给出
  `claim_value` / `context_only` / `non_claim` / `ambiguous` / `unresolved`，并附 subject、
  predicate、kind、理由、证据句与逐字引文。
- **N3**：`opportunity_radar/n3_relationships.py`（`n3-v1`），给出 level/change/comparison/
  range/revision/share/rate 关系，并对每个 N2 `claim_value` 给出 assigned/ambiguous/unresolved。
- **共享层**：`opportunity_radar/semantic_common.py`（批次构造、JSON 校验/修复、证据定位、
  `JsonRunner`、状态、模型元数据）。
- **工具**：`tools/run_n2_n3.py`（统一入口）、`tools/run_n2.py`、`tools/run_n3.py`。
- **测试**：`tests/test_n2_semantic.py`（17）、`tests/test_n3_relationships.py`（17）、
  `tests/test_n2_n3_pipeline.py`（3）。

未做：N4、N5；生产 Claim 写入；v7 启用；G6。

## 2. 契约要点

完整契约见规格与 `docs/CLAIM_PIPELINE.md` §6–§7。要点：

- N2 批次：候选所在句完整 + 前后各一句，字符预算 3500，每批默认 4 个候选；不跨 title/body；
  一个候选只属于一个批次；模型不接收整篇文章。
- N2 枚举：`disposition` 五类；`kind` 使用 r2-v4 枚举且禁止 `system_inference`；
  `status` resolved/ambiguous/unresolved。
- N3 只对 N2 `claim_value` 且 `status=resolved` 的候选建立数值关系；`context_only` 可作期间/
  基准上下文；`non_claim` 不得引用；N2 未成功时 N3 返回 `blocked`，不调用模型。
- N3 枚举严格使用 `claim_contract.py`；`relationship_id` 由程序生成。
- 模型：llama.cpp + `Qwen3-30B-A3B-Instruct-2507-Q4_K_M`；temperature 0.0；
  `response_format`（json_object + schema）；N2 max_tokens 1600、N3 1400（最终验收运行）；
  seed/top_p 未发送；模型指纹记录为 unknown。

## 3. 程序校验

N2：每个输入候选恰好一个结果；缺失补 unresolved；重复/额外候选记录并忽略；枚举非法降级；
`claim_value` 缺 subject/predicate、证据无法定位、字段超长 → unresolved（原文保留，不截断）；
predicate 含方向/关系词 → 用 subject 规范化替换，原值保存为 `predicate_raw` 并记
`relationship_leak`。

N3：ID/表达组/枚举/证据校验；`value_candidate_ids` 为空的关系丢弃；non_claim 引用拒绝；
每个 claim_value 必须有处置；比较口径只在原文出现对应措辞且紧邻该数值时接受，否则改为
unknown/level 并记 `not_stated` / `attached_to_other_candidate`；`change` 不得用
`comparison=level`；revision/seasonality 只有原文出现对应措辞时才保留；`period_raw` 必须
能回到上下文。

## 4. 真实模型运行

### 4.1 BEA 个人收入（完整 RSS 正文，最终代码）

数据：`data/claim-pipeline/fixtures-final-code/n2n3.jsonl`（最终代码，N3 max_tokens 1400；
更早的 `fixtures-key` 与 `fixture-smoke` 作为对照）。
N2：10 个候选 → 9 个 `claim_value` + 1 个 `context_only`，全部 resolved；subject/predicate 示例：
`personal_income`、`disposable_personal_income`、`personal_consumption_expenditures`、
`personal_saving`、`personal_saving_rate`；证据引文全部可定位。
N3：9 条关系（change 5、rate 3、level 1），9 个 assigned、0 个 unresolved；
9/9 证据定位。

关键案例：

| 数值 | N2 | N3 |
|---|---|---|
| 0.2 percent at a monthly rate | personal_income | rate，**monthly_rate** |
| $54.5 billion | personal_income | change，increase，comparison=unknown（程序拒绝了误挂的 monthly_rate） |
| 0.5 percent | personal_consumption_expenditures | rate，comparison=level（原文未声明月度率） |
| 3.8 percent | personal_saving_rate | rate，comparison=level（原文未声明年度率） |

同文 `september 2026` 被 N2 标为 `context_only`，但 N3 未把它关联为 period 候选，
`period_raw` 为空。这是模型漏记，统计与处置中可见，程序没有凭上下文补造期间。

### 4.2 BEA 国际贸易（N2）

N2：8 个候选 → 6 个 `claim_value` + 2 个 `context_only`，全部 resolved（最终代码运行，
status=success，3 批，覆盖 8/8，证据全部可定位）。
五个关键数字均被识别到正确主体：

| 数值 | subject | predicate |
|---|---|---|
| $92.8 billion | u.s. goods and services trade deficit | trade_deficit |
| $105.6 billion | u.s. goods and services trade deficit | trade_deficit |
| $12.8 billion | goods deficit | goods_deficit |
| $136.6 billion | goods deficit | goods_deficit |
| $0.1 billion | services surplus | services_surplus |

### 4.3 BEA 国际贸易（N3）

最终代码运行（`fixtures-final-code`，N3 max_tokens 1400）：6 个 `claim_value` 全部得到处置，
7 条关系（change 3、level 4），assigned 6、ambiguous 0、unresolved 0；证据定位 7/7；
节点 status=partial（存在程序守卫偏差）。

| 关系 | 数值 | 结果 |
|---|---|---|
| deficit 变化 | $105.6bn | change，increase，period_change |
| deficit 水平 | $92.8bn / $105.6bn | level，comparison=level |
| goods deficit | $12.8bn / $136.6bn | change + level |
| services surplus | $0.1bn / $31.0bn | change + level |

未达成的点（如实记录）：
- 本次运行没有给出 revision 关系；更早的 `fixtures-key` 运行给出过 `relationship_type=revision`
  （quote `in july (revised)`），但 revision 枚举仍为 unknown。两次都没有由程序按机构惯例补造。
- 没有把 `from $92.8bn to $105.6bn` 建成 baseline/from_to 关系。
- 没有把 `august 2026` 关联为 period 候选；`period_raw` 为空。
这些都是模型漏记，统计与处置中可见。

### 4.4 真实语料影子运行

本次**未完成** 50 篇 FreshRSS 池影子运行。实际完成的是 §4.1–§4.3 的两篇 BEA 真实文章
（个人收入、国际贸易）的 N2 与 N3。
未继续批量运行的原因：本地 llama.cpp 在 N3 长批次上出现异常慢的 prompt 处理
（观察到一个请求数分钟仅推进数百 token），同一时段最小调用仍为 1 秒；这是模型吞吐/资源限制，
不是配置或权限错误。为避免把部分运行描述为全量通过，已停止批量运行。

因此：
- 不报告"50 篇通过"或任何全量影子指标。
- 已处理文章的指标在 §4.1–§4.3 中逐项列出；候选覆盖率不是语义准确率。
- 已处理的真实文章确实覆盖了第五/六批的五个关键数字。

## 5. 测试

- 新增 37 项：N2 17、N3 17、节点组合 3。
- 覆盖：未知/缺失/重复候选；非法枚举；证据无法定位；claim_value 字段缺失；超长字段不截断；
  predicate 关系泄漏；模型失败；空候选；批次不跨字段；每候选只进一批；N2 失败阻断 N3；
  non_claim 不得作 value；空 value 丢弃；每个 claim_value 有处置；多关系；比较口径误挂/
  未声明/change=level；revision/seasonality 未声明；period 不在上下文；N3 缓存随 N2 变化、
  忽略时间字段；relationship_id 确定性；N1 留存复用。
- 全量：**803 项通过**。

## 6. 缓存与留存

复用 `pipeline_store.py`；N2/N3 输入哈希包含 N0/N1 哈希、Prompt/Schema 哈希、规则源码哈希、
模型与生成参数；N3 额外包含 N2 稳定哈希（排除 `seconds`/`batches`）。失败运行不占成功键。
N2 内容或规则变化会使 N3 失效；时间/重试次数不进入 N3 缓存键。

## 7. 未完成与阻塞

1. **50 篇真实语料影子运行未完成**：本地 llama.cpp 在 N3 批次上出现长时间 prompt 处理
   （观察到一个请求数分钟仅推进数百 token），同一时段的最小调用仍为 1 秒，说明是长上下文/
   语法约束下的吞吐问题，不是网络或配置缺失。为避免把部分运行描述为全量通过，已停止该运行；
   实际完成的文章与节点见 §4。
2. **GDP / Intel / Obamacare / boundary 固定样本的 N3 未完成**；N2 计划与夹具已就绪，
   可在模型吞吐恢复后重跑。
3. **N2/N3 语义准确率没有全量人工基准**；候选覆盖率不等于语义准确率。
4. **模型指纹未知**；seed/top_p 未发送。
5. N4/N5 未实现：不产出 r2-v4 Claim，不声称完成文章到 Claim 的完整链路。

## 8. 生产隔离

- 未写生产数据库、RSS 库、SEC/EIA 库；未修改 `claim_contract.py`、`verify.py`、`units.py`、
  生产提示词、评分、R0 门禁、日报与邮件。
- `analyzer.py` 只增加了可选的 `temperature` 参数（默认 0.2）与 `complete()` 方法；
  `analyze()` 的请求体与默认行为不变，生产路径未切换。
- N2/N3 只写独立的 `data/claim-pipeline/node_runs.sqlite3` 与本批运行目录。
- v7 未启用；生产仍是 v6；G6 未批准。

## 9. Git

本批提交在 `feat/r2-batch9-n2-n3`；PR、CI 与合并结果见最终执行报告。
未把 `data/` 运行产物、模型文件或密钥提交到 Git。

# R2 第十批（N4 + N5）— 验收记录

日期：2026-11-02
结论：**N4、N5 已实现，使用已留存的 N2/N3 结果端到端生成 r2-v4 影子 Claim，未调用模型。**
两篇 BEA 真实文章完成 N0–N5；固定夹具中 5 篇因没有 N2/N3 留存被明确记为 missing。
N4/N5 状态为 partial（缺失期间/比较口径在 Claim 偏差中可见），不是失败。
v7 未启用；G6 未批准；未写生产 Claim 表。

规格：`R2_BATCH10_N4_N5_SPEC_2026-11-02.md`；现行契约：`docs/CLAIM_PIPELINE.md`。

---

## 1. 实现文件

| 文件 | 内容 |
|---|---|
| `opportunity_radar/n4_normalization.py`（`n4-v1`） | 确定性数值、单位、数量级、币种、期间、baseline、关系类型标准化；失败状态 |
| `opportunity_radar/n5_assembly.py`（`n5-v1`） | 候选完整处置、r2-v4 契约组装、证据定位、重复防护、契约校验 |
| `tools/run_n4_n5.py` / `run_n4.py` / `run_n5.py` | 复用已留存 N0–N3；无模型调用；JSONL/summary |
| `tests/test_n4_normalization.py`（16）、`tests/test_n5_assembly.py`（13） | 单位/数量级/币种、失败状态、完整性、契约、缓存 |

## 2. 端到端结果（两篇 BEA 真实文章，已留存 N2/N3）

| 指标 | 数值 |
|---|---|
| 文章 | 2 |
| N1 候选 | 18 |
| N2 claim_value | 15 |
| N2 context_only | 3 |
| N4 标准化记录 | 16（personal 9、trade 7） |
| N4 normalized / partially_normalized | 8 / 8 |
| N4 失败记录 | 0 |
| N5 合格影子 Claim | **16** |
| 候选处置 | claim_accepted 15、context_only 3 |
| 覆盖完整 | **是（18/18 唯一处置）** |
| r2-v4 契约校验 | **16/16 通过** |
| rejected / unresolved | 0 / 0 |
| 模型调用 | **0** |
| 缓存复用 | N4 2/2、N5 2/2（相同输入重跑） |

### 2.1 BEA Personal Income（9 条 Claim）

- `$54.5 billion`：value 54.5、unit USD、scale billion、currency USD；comparison=unknown，
  **没有继承 monthly_rate**；期间为空并记 `period_missing`。
- `0.2 percent at a monthly rate`：value 0.2、unit %，**comparison=monthly_rate**。
- `0.5 percent`：comparison=unknown，**没有被擅自解释为月度率**。
- `3.8 percent`：relationship_type=rate、comparison=level，**没有被擅自解释为年度率**。
- 证据回到 N0 原文；title-only 证据未出现。
- Claim 偏差：`period_missing`、`comparison_unknown`、`parenthesized_sign_not_inferred`
  （N1 的括号数字，N4 不擅自取负）。

### 2.2 BEA International Trade（7 条 Claim）

| 数值 | unit / scale / currency | 关系 |
|---|---|---|
| $92.8 billion | USD / billion / USD | level |
| $105.6 billion | USD / billion / USD | change + level（同值参与两个关系） |
| $12.8 billion | USD / billion / USD | change |
| $136.6 billion | USD / billion / USD | level |
| $0.1 billion | USD / billion / USD | change |
| $31.0 billion | USD / billion / USD | level |

未补造：N3 没有建立 `from $92.8bn to $105.6bn` 的 baseline/from_to，N4/N5 未创建；
N3 没有关联 `august 2026`，Claim 的 period 为空并记 `period_missing`；`$92.8bn` 的引文含
`(revised)`，但 N3 的 revision 为 unknown，N4/N5 未按机构惯例补造。

## 3. 候选处置完整性

N5 以 N1 全部 18 个候选为基准：

- 15 个 claim_value 全部成为 `claim_accepted`（15 个候选产生 16 条 Claim；$105.6bn 同时是
  change 的当前值和 level 的数值，产生两条不同关系 Claim）。
- 3 个 context_only（两个 `august 2026`、一个 `september 2026`）。
- 0 个 non_claim、ambiguous、unresolved、relationship_unassigned、normalization_failed、rejected。
- 覆盖完整，Claim 数量没有被当作成功指标。

## 4. 固定夹具

7 个夹具中：
- `bea-personal`、`bea-trade`：完成 N4/N5（§2）。
- `bea-gdp`、`nyt-intel`、`nyt-obamacare`、`edges`、`multi-metric`：**N2 留存缺失**，
  工具明确记录 `missing=n2`，未调用模型补跑，未生成 Claim。

因此本批没有把固定夹具表述为真实语料通过率；N4/N5 的行为由单元测试和两篇真实文章验证。
边界样本（区间、百分点、负数、无单位、未知单位、括号、title-only）由 `test_n4_normalization`
与 `test_n5_assembly` 覆盖。

## 5. 测试

- 新增 29 项：N4 16、N5 13。
- N4：金额/数量级/币种、USD 代码、5 million vehicles、百分比与百分点、负数、括号、
  区间不可组装、未知单位、currency conflict、缺失期间/基准、unknown 关系、missing semantics、
  N2 失败、稳定 ID/哈希。
- N5：r2-v4 字段与谱系、context/non_claim 不生成 Claim、title-only 证据拒绝、缺 predicate 拒绝、
  重复关系去重、未知单位拒绝、N2 partial 保留 Claim、N2 unresolved 不生成 Claim、N2 失败 blocked、
  空候选成功、Claim ID 与 N5 哈希随 N4 变化。
- 全量：**832 项通过**。

## 6. 缓存与留存

- N4 输入哈希包含 N0/N1/N2/N3 稳定哈希、节点版本、规则源码哈希、`units.py` 源码哈希。
- N5 输入哈希包含 N0–N4 稳定哈希、节点版本、r2-v4 版本与契约源码哈希、规则源码哈希。
- 时间/耗时/重试次数不进入稳定哈希；失败运行不占成功键。
- 重跑验证：N4 复用 2/2、N5 复用 2/2；N4/N5 输出记录写入独立 `pipeline_store.py`。

## 7. units.py 的追加式变更

`5 million vehicles` 是规格要求的 N4 案例。`units.py` 原先没有 count/duration 单位族，N5 走
r2-v4 会误报 `unknown_unit`。本批只追加 count/duration 名词到 `UNIT_FAMILY`；没有修改既有单位、
换算或核验规则，没有引入跨族换算。全量测试通过。

## 8. 生产隔离

- 未写生产数据库、RSS 库、SEC/EIA 库；生产库计数未变：articles 117 / analyses 108 /
  claims 220 / evidences 220。
- 未修改 `claim_contract.py`（r2-v4）、`verify.py`（r2-v2）、生产提示词、评分、R0 门禁、
  日报与邮件；本批未修改 `analyzer.py`。
- N4/N5 只写 `data/claim-pipeline/node_runs.sqlite3` 与本批运行目录。
- 影子 Claim 不是已核实事实；v7 未启用；G6 未批准。

## 9. Git

本批提交在 `feat/r2-batch10-n4-n5`；PR、CI 与合并结果见最终执行报告。
未把 `data/` 运行产物提交到 Git。

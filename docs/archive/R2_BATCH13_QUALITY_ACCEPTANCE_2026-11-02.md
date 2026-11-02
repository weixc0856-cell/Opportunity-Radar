# R2 Batch 13（质量修复）— 验收记录

日期：2026-11-02
基线：`main` 提交 `47815f580da8a68b436cf90349d48d9470e02859`
结论：完成 N2 经济相关性、N3 期间关联、N5 语义去重三组定向修复，并将 N1/N4 的期间表达与证据
链路补齐。受影响的 10 篇案例与 10 篇人工参考集全部用新版本重跑；**没有重跑 50 篇全量**。
修复有效，但真实参考集出现新的语义回退：N3 rate/comparison 与个别 N2 disposition 不如 Batch 12。
这些回退没有被隐藏，列在 §7。

规格：本批任务书；现行契约：`docs/CLAIM_PIPELINE.md`；基线测量：`R2_BATCH12_ACCEPTANCE_2026-11-02.md`。

---

## 1. 范围

- 只重跑受影响节点及其下游：N1 → N2 → N3 → N4 → N5。
- 受影响案例 10 篇：BEA 个人收入/贸易/GDP；pySMESH 5.1；GUI opacity；Cyril 年龄；
  NVIDIA NVL72；Intel 20%/$16.5bn；Google $500bn；SimScale 复现求助。
- 为保持人工参考集完整，额外重跑 Batch 12 参考集中不在上述列表的 4 篇：BBC $1tn、
  NYT Anthropic、OpenAI 功能请求、SimScale anomalous。合计 14 篇。
- 不写生产 claims/analyses、不改评分/日报/邮件/R0 门禁、不启用 v7、不触碰 SEC/EIA 库；
  影子 Claim 不是已核实事实。

## 2. 版本与代码

| 节点 | 版本 | 变更 |
|---|---|---|
| N1 | `n1-v2` | 新增 `third quarter of 2026`、`second quarter` 等文字季度；新增 `in September` 等无年份月份期间；方向关系组不再由纯期间候选构成 |
| N2 | `n2-v2` | 新增必填 `economic_relevance`（economic / non_economic / uncertain）；non_economic 的 claim_value 程序降为 non_claim，uncertain 降为 ambiguous；补全 plunge/surge/jump 等方向词清理 |
| N3 | `n3-v2` | payload 提供全文档期间候选与 `period_hints`；允许引用文档级期间候选；确定性同句/标题同月补期间；期间证据定位；无年份不补年；跨句不搬期间 |
| N4 | `n4-v2` | 期间证据 `period_evidence_quote/start/end/field`、`period_source`；无年份的月/季度保留 `period_raw` 但 `period` 为空 |
| N5 | `n5-v2` | 按 r2-v4 语义字段去重，`relationship_type`/id 只进 trace；合并保留全部关系、N4 记录、期间、baseline 与证据；重复项独立于 rejected；方向冲突不合并 |

## 3. N2 经济相关性

14 篇合计：

| 指标 | Batch 12（旧） | Batch 13（新） |
|---|---:|---:|
| claim_value | 32 | 20 |
| context_only | 48 | 57 |
| non_claim | 9 | 27 |
| N2 unresolved | 2 | 2 |

目标案例：

| 案例 | 旧 | 新 |
|---|---|---|
| pySMESH 5.1.0 | claim_value（latest release/version） | context_only / non_economic |
| GUI opacity=0.5 | claim_value（opacity/opacity_value） | context_only / non_economic |
| Cyril died at 101 | claim_value（age） | context_only / non_economic |
| NVIDIA NVL72 | claim_value（vehicle_count） | non_claim / non_economic |
| SimScale 0.4 | claim_value（lift coefficient） | non_claim / non_economic |
| Intel `$16.5 billion` | subject=`revenue` | subject=`intel`，predicate=`revenue` |
| Google `$500bn` | subject=`google value`，predicate=`google_value` | subject=`google`，predicate=`market_value` |
| Intel `20%` | predicate=`plunge_rate` | predicate=`price`；subject 仍为 `intel's shares`，不是参考集的 `intel` |

pySMESH、GUI、Cyril、NVIDIA、SimScale 不再生成 Claim；Google 与 Intel `$16.5bn` 的语义错误修复。
Intel `20%` 是 title-only，N5 仍拒绝。

## 4. N3 期间关联

| 文章 | 旧 | 新 |
|---|---|---|
| BEA 个人收入 | 0/9 关系有 period | 5/12；`$54.5bn`、`0.2%`、`$113.0bn` → `2026-09`；`$52.7bn`、`$113.1bn`、`0.5%`、`$911.1bn` 所在句没有期间，保持空 |
| BEA 贸易 | 0/9 | 7/7；`$92.8bn` → `july`（raw）；`$105.6bn`、`$12.8bn`、`$136.6bn`、`$0.1bn`、`$31.0bn` → `august 2026` |
| BEA GDP | 0/3 | 2/2；`3.4%` → `third quarter of 2026`（`2026-Q3`）；`2.2%` → `second quarter`（raw，`period` 为空） |
| Intel `$16.5bn` | 0 | `third quarter`（raw，文章未给年份） |
| 10 篇参考集正文 Claim | **0/18** | 11/18 关联期间；11/18 `period_raw` 与参考一致；9/18 有可格式化 `period` |

期间由程序补齐 15 条（`period_source=program`），模型主动引用 0 条。无年份月份/季度保留 raw、
不推断年份，因此 `july`、`second quarter`、`third quarter` 的 `period` 为空；跨句不搬期间，因此
BEA 个人收入第三句的数字仍无期间。这两点是有意的保守行为，不是漏记。

## 5. N5 语义去重

14 篇合计：**22 条原始组装 Claim → 17 条唯一 Claim；合并 5 条；方向冲突 0**。

| 案例 | 旧 | 新 |
|---|---|---|
| BEA 贸易 `$105.6bn` | change 与 comparison 两条相同 r2-v4 字段 | 合并为 1 条；trace 保留 2 个 relationship_id、2 个 n4_record_id、2 条证据；level 关系因 comparison 不同仍独立 |
| BEA 个人收入 `0.2%` 等 | change/comparison/rate 多条 | 4 条合并；trace 保留全部关系与证据 |
| BEA GDP `3.4%` | change 与 comparison 两条 | 本次 N3 只产出 1 条关系，无重复 |
| SimScale `0.4` | comparison/level 两条重复 | N2 已判 non_economic，不再生成 Claim |
| 方向冲突 | — | 0；规则保留两个相反具体方向的 Claim 并写 `direction_conflict`，本批未出现 |

`duplicates[]` 与 `rejected_items[]` 分离；重复项不再混入拒绝原因。`raw_assembled_claims`、
`assembled_claims`、`duplicate_claims`、`direction_conflicts` 均进入覆盖统计。

## 6. 10 篇人工参考集（仅这 10 篇，不外推）

| 指标 | Batch 12 | Batch 13 |
|---|---|---|
| N1 候选召回 | 21/21 | 21/21 |
| N2 disposition（claim_value 且 resolved） | 21/21 | **20/21** |
| N2 subject 语义正确 | 20/21 | **17/21** |
| N2 predicate 语义正确 | 19/21 | **16/21** |
| N3 有关系 | 21/21 | **19/21** |
| N3 relationship_type | 20/21 | **17/21** |
| N3 direction | 20/21 | **17/21** |
| N3 comparison | 18/21 | **14/21** |
| N3 period（18 个正文 Claim） | 0/18 | **11/18 关联；11/18 raw；9/18 格式化** |
| N5 唯一 Claim 精确率（严格 subject/predicate） | 18/19（去重后） | **14/17（82.4%）** |
| N5 正文 Claim 召回（严格） | 17/18 | **13/18** |
| title-only 拒绝 | 3/3 | 3/3 |

新增/保留的错误见 §7。N5 精确率分母改为唯一 Claim；旧值 18/19 是 Batch 12 去重后的口径。
本批没有对 50 篇全量重新计算总体精确率或召回率。

## 7. 未解决问题

1. **N3 rate/comparison 回退**：BEA 个人收入 `0.2 percent at a monthly rate` 被 N3 判为
   change/increase/unknown（参考为 rate/not_applicable/monthly_rate）；`0.5 percent` 被判为
   rate（参考为 change）；贸易 `$105.6bn`/`$12.8bn` 的 comparison 为 unknown（参考
   `period_change`）。这是 `n3-v2` 提示词/模型行为变化，程序没有强制覆盖。
2. **N3 召回**：`3.8 percent` 未获得关系，N5 标为 `relationship_unassigned`；`$0.1 billion`
   被 N2 判为 context_only/non_economic（"less than" 被当成 threshold），N5 没有 Claim。
   这两条是参考集召回从 17/18 降到 13/18 的主要原因。
3. **N2 语义**：GDP `3.4%` subject 为 `real gross domestic product (gdp)`、`2.2%` 为 `real gdp`
   （参考 `real gross domestic product`）；贸易 `$12.8bn` predicate 为 `deficit_amount`
   （参考 `goods_deficit`）；Intel `20%` subject 仍为 `intel's shares`。N5 只做结构校验，无法拦截。
4. **期间覆盖**：只关联同句期间或标题同月；BEA 个人收入第三句没有期间，按“跨句不搬”保持空。
   无年份的 `july`、`second quarter`、`third quarter` 按“不补年”保留 raw、`period` 为空。
5. **输出预算**：BEA 个人收入 9 个 claim_value 在 `--n3-tokens 1400` 下两个批次
   `invalid_output`（JSON 截断）；用 2400 重跑后得到 12 条关系。默认回归命令需要注意这个上限。
6. **N2/N3 语义准确率仍只有 10 篇人工参考**，不能外推到 50 篇；本轮的回退也说明 temperature=0
   不等于跨提示词稳定。

## 8. 测试

- 全量 **854 项通过**（Batch 12 为 840）。
- 新增/更新：N1 文字季度与无年份月份；N2 non_economic/uncertain 降级、plunge 方向词；
  N3 标题同月补年、无年份保留 raw、跨句不搬、多个不同期间不共享；N4 期间证据与无年份 raw；
  N5 语义合并、重复项独立、方向冲突、同数不同期不合并。
- 回归运行：14 篇文章，N2/N3 真实模型；N4/N5 确定性；旧结果保留在 Batch 12 目录，新结果在
  `data/claim-pipeline/batch13/`（本地，未入库）。

## 9. 生产隔离

- 只读生产 RSS 样本；节点结果只写 `data/claim-pipeline/node_runs.sqlite3` 与 Batch 13 运行目录。
- 未写生产 claims/analyses；未改评分、日报、邮件、R0 门禁；SEC/EIA 独立库未触碰；v7 未启用；
  G6 未批准。
- 影子 Claim 不是已核实事实；N5 的合并只影响影子输出。

## 10. Git

本批提交在 `feat/r2-batch13-quality`；PR、CI 与合并结果见最终执行报告。

# R2 Batch 16（N5 关系语义与重复组装）— 验收记录

日期：2026-11-02
基线：`main` 合并 Batch 15 后的提交 `dc4a7cc`（包含 `28908a1`）
分支：`feat/r2-batch16-n5-semantic-assembly`
结论：把“变化关系的终点 level”与“独立 level 陈述”区分开。贸易 `$105.6bn` 的 level Claim
被折回 change Claim，Claim 总数 18→17，严格精确率保持 18/18→17/17（100%），正文严格召回
保持 17/18；`relationship_type + comparison` 语义精确率从 16/18 提升到 16/17。没有误合并
独立 level，也没有损失 change Claim。

本批只改 N5；固定 Batch 15 的 N0/N1/N2/N3/N4 结果，仅重跑 N5。未重跑 50 篇，未改 N0–N4、
r2-v4、生产链路、评分、日报或数据库。

---

## 1. 根因

Batch 15 的 N5 语义去重键包含 `comparison`：

- `$105.6bn` 的 change 关系 comparison=`period_change`；
- 同值的 level 关系 comparison=`level`；
- 两条 Claim 的 subject/predicate/value/unit/scale/currency/period 完全相同，只有 comparison
  和 relationship_type 不同，因此没有被现有的 `_merge_claims` 合并。

检查 N4 证据：

- change N4 证据：`the deficit increased from $92.8 billion in july (revised) to $105.6 billion in august`（205–291）；
- level N4 证据：`to $105.6 billion in august`（264–291）。

level 证据是 change 证据的严格子区间，且同 subject/predicate/value/period。它不是独立 level
陈述，而是变化关系的目的端。N5 之前把“关系字段不同”等同于“事实不同”，这是根因。

## 2. N5 关系组装规则

新增 `n5-v3` 的 endpoint-level 规则：

1. 两条 Claim 必须同 subject、predicate、kind、value_num、unit、scale、currency、period、
   seasonality、revision、denominator、region；
2. 一条关系的类型包含 `change` 或 `comparison`，另一条是纯 `level`；
3. level 的 N4 证据必须是 change 的 N4 证据的**严格子区间**（同一 field），或严格子串；
4. 只有恰好一条 change 包含该 level 时才合并；多条包含 → ambiguous，不合并；
5. level 证据在 change 证据之外 → 独立 level，保留；
6. 合并保留两边的 `relationship_ids`、`n4_record_ids`、`evidence_items`、`merged_from`；
   被合并的 level 写入 `duplicates[]`，reason=`endpoint_level_of_change`，不进入 rejected；
7. 同值不同关系但证据独立、或不同数值的 level，不进入该规则。

这与“按数值/subject/predicate 简单去重”不同：只有 evidence containment 证明是端点时才合并。

## 3. 修改前后逐项案例

### `$105.6bn`

Batch 15：

| Claim | comparison | relationship | evidence |
|---|---|---|---|
| `c_38a…` | period_change | change | `to $105.6 billion in august` |
| `c_9c0…` | level | level | `to $105.6 billion in august` |

Batch 16：只保留 `c_ee0…`，trace：

- `relationship_types=['change','level']`
- `relationship_ids` 两条
- `n4_record_ids` 两条
- `endpoint_level_merged=true`
- `duplicates` 1 条，reason=`endpoint_level_of_change`

### 保留的独立 level

- 贸易 `$92.8bn` level（July 独立值）保留；
- 贸易 `$136.6bn` level（结果值，change 的 value 是 `$12.8bn`）保留；
- 贸易 `$31.0bn` level 保留；
- 3.8% 的 rate/level 关系保留；
- 独立证据的 level 夹具保留（测试 `test_an_independent_level_is_not_folded`）。

### 不同数值

`$12.8bn` change 与 `$136.6bn` level 的 `value_num` 不同，不触发规则（测试
`test_a_level_with_a_different_value_is_not_folded`）。

## 4. Batch 12–16 指标对照

| 指标 | Batch 12 | Batch 13 | Batch 14 | Batch 15 | Batch 16 |
|---|---:|---:|---:|---:|---:|
| N5 Claim 数 | 21 | 17 | 18 | 18 | **17** |
| 严格精确率（value/unit/subject/predicate） | 18/21（85.7%） | 14/17（82.4%） | 15/18（83.3%） | 18/18（100%） | **17/17（100%）** |
| 正文严格召回 | 17/18（94.4%） | 13/18（72.2%） | 14/18（77.8%） | 17/18（94.4%） | **17/18（94.4%）** |
| relationship_type + comparison 精确率 | 未单列 | 未单列 | 14/18 | 16/18（88.9%） | **16/17（94.1%）** |
| relationship_type + comparison 召回 | 未单列 | 未单列 | 14/18 | 16/18（88.9%） | **16/18（88.9%）** |
| 重复 Claim 数 | 2（21→19） | 5（22→17） | 0 | 0 | **1（endpoint level）** |
| 误合并独立关系 | — | — | — | — | **0** |
| endpoint_level_independent / ambiguous | — | — | — | — | **0 / 0** |
| title-only 拒绝 | 3/3 | 3/3 | 3/3 | 3/3 | **3/3** |
| 证据定位 | 21/21 | — | 18/18 | 18/18 | **17/17** |

严格指标的分母随 Claim 数变化；`16/17` 与 `16/18` 不能直接当作“提升 1 条”，但精确率从
88.9% 到 94.1% 是同一语义口径下的改善。正文严格召回保持 17/18，没有因为删除 level 而损失
有效 change。

## 5. 误合并与漏合并

- **误合并**：0。独立 level、不同数值 level、rate/level 都保留；最终 `endpoint_level_independent=0`、
  `endpoint_level_ambiguous=0`（固定参考集中没有需要保留的同值独立 level）。
- **漏合并**：固定参考集中 `$105.6bn` 已合并；没有其他同值 change+level 证据包含对。
- **未解决**：BEA Personal Income 的 `0.2%`（DPI）仍缺 N3 关系，N5 标
  `relationship_unassigned`，这是 N3 遗漏；GDP `2.2%` comparison 仍为 unknown（参考 annual_rate）；
  Google/Intel title-only 的 N2 语义错误仍存在。
- N5 语义口径 16/18 召回仍低于 Batch 12 的 17/18，原因就是上述 `0.2%` 漏关系。

## 6. 测试与生产隔离

- 全量 **875 项通过**。
- 新增：endpoint level 折回、独立 level 保留、不同数值 level 不合并；trace 保留两条关系/N4 记录。
- 未修改 N0/N1/N2/N3/N4 代码或提示词；未改 r2-v4；未写生产 claims/analyses；未改评分、日报、
  邮件、R0 门禁；SEC/EIA 未触碰；v7 未启用；G6 未批准；影子 Claim 不是已核实事实。
- 未重跑 50 篇；未修改人工参考答案。

## 7. Git

分支 `feat/r2-batch16-n5-semantic-assembly`；提交、PR、CI 与合并状态见最终执行报告。

# R2 第二批（v7 影子提示词、冲突展示、核验质量审计）— 验收记录

日期：2026-11-01
状态：v7 **仅影子运行**；核验与冲突报告**只在数据库副本上运行**；生产提示词（v6）、评分与发布门禁未改。

---

## 1. v7 提示词

`prompts/analyst_v7.md`（VERSION 7）在 v6 之上增加 `claims` 数组，逐字段约定：

| 字段 | 约定 |
|---|---|
| `value_num` | 只在正文给出数字时填写；没有数字就留空 |
| `unit` | `%` 与 `pp` 必须按原文区分；货币写代码；物理单位按原文 |
| `period` | `YYYY` / `YYYY-MM` / `YYYY-MM-DD` / `YYYY-Qn` / `起/止`；原文没有就留空，**不得用发布日期代替** |
| `comparison` | level / yoy / qoq / mom / period_change / pp_change / share / unknown；"rose" 不等于同比 |
| `kind` | fact / source_interpretation / system_inference / hypothesis / forecast / opinion |
| `quote` | 逐字引文 |

规则与 v6 相同（不猜测、不虚构、区分事实与推断），另外要求：数字无单位时不补单位，百分比与百分点不互换。

## 2. 影子运行

方法：副本库 + 真实 FreshRSS 池 + 与 v6 分析相同的文章；用 `LocalAnalyzer(system=...)` 注入 v7 提示词，
不写数据库，结果落 `data/r2-shadow/<时间戳>/`。工具：`tools/shadow_v7.py`。

| 项 | v6 | v7 |
|---|---|---|
| 文章 | 8（同一批） | 8 |
| 成功 | 8 | **7**（1 篇 JSON 解析失败） |
| 事实条数 | 21 | 23 |
| 可定位引文 | 21 | 23 |

v7 失败的那篇是输出在第 126 行被截断（`JSONDecodeError`）。分析器的重排重试没有覆盖影子路径，
生产路径有；这提示 v7 输出更长、截断风险更高。

### 2.1 结构化主张

| 项 | 数值 |
|---|---|
| 主张总数 | 13（每篇 1.86） |
| 引文可定位 | **13 / 13** |
| 带数值 | 8 |
| 带单位 | 2 |
| 带期间 | 3 |
| 带比较口径 | 2 |
| 数值+单位+期间齐全 | **2** |
| 契约偏差 | 3 |

偏差明细：

- `revision: "advance_estimate"` ×2（模型写出了词表外的修订状态；语义合理，词表未覆盖）
- `period: "1997-2024"` ×1（区间不是受支持的期间格式）

出现过的单位只有 `%`，类型有 `fact` 与 `forecast`。完全结构化的两条来自 BEA GDP 新闻：
`Real GDP growth 3.4% / 2026-Q3 / year_over_year` 与 `2.2% / 2026-Q2 / year_over_year`。

### 2.2 可核验性对照

把 13 条 v7 主张写入副本库后运行核验：

| 主张来源 | 条数 | verified | unverifiable |
|---|---|---|---|
| v6 骨架主张 | 220 | **0** | 220 |
| v7 影子主张 | 13 | **2** | 11 |

其中 11 条不可核验的原因是**没有单位或没有期间**——模型按契约留空，而不是猜。这正是规则想要的行为，
也说明「结构化输出」与「可核验」之间还差一步：需要正文本身给出单位与期间。

## 3. 冲突进入展示

- `verify --conflicts` 输出双方数值、单位、期间、修订状态、来源与证据定位（含 accession）。
- 日报与 HTML 增加「数据冲突（记录，不判定对错）」区块，数据来自**本库**的 `claim_conflicts`；
  RSS 库当前为空，区块不出现。
- 分类：两侧申报状态不同（original / amendment / subsequent_comparative / revised）记为 `restatement`，
  否则 `unclassified`。
- 新增：同一主体+指标+期间+单位、数值相同但比较口径不同 → `comparison_basis_differs`。

真实数据示例（摄取库，114 组中的一组）：

```
· COCA COLA CO · capex · 2017-01-01/2017-12-31 · USD（restatement）
   - 1750000000.0 USD · 修订状态 subsequent_comparative · 来源 sec-edgar · 证据 ev-b2cd…（0000021344-19-000039）
   - 1675000000.0 USD · 修订状态 original              · 来源 sec-edgar · 证据 ev-b410…（0000021344-18-000008）
```

不覆盖旧值，不判定哪个正确。

## 4. 核验质量审计

`verify --audit` 按检查项统计「执行了多少、通过多少、跳过了多少」。

摄取库（2,753 条全部 verified）：

| 检查 | 通过 | 失败 | 跳过 |
|---|---|---|---|
| value_in_quote | 2,753 | 0 | 0 |
| unit | 2,753 | 0 | 0 |
| period | 2,753 | 0 | 0 |
| comparison | 0 | 0 | **2,753** |

发现：

1. **`comparison` 检查从未执行**：结构化来源的主张不声明比较口径，所以它是"跳过"而不是"通过"。
   审计单独列出（`verified_with_skipped_check: {comparison: 2753}`），不把它算进通过。
2. `verified_without_any_pass = 0`：没有出现"什么检查都没通过却判为 verified"的情况。
3. `verified_with_missing_field = 0`：verified 里没有缺数值、单位或期间的主张。
4. **新增规则**：声明了数值但没有单位的主张不再判为 verified，改为 `unverifiable`
   （依据 `value_without_unit`）。一个数不能和有单位的数比较。

RSS 库（220 条）：全部 `unverifiable`，审计显示 `structured_fields` 跳过 220 次——
骨架主张没有任何可核验字段，这一点在审计里是显式记录，不是默认通过。

## 5. 测试

| 项 | 数值 |
|---|---|
| 新增 | 冲突分类、比较口径冲突、冲突文本、审计四项、HTML 冲突块、digest 冲突段（共 13 项） |
| 全量 | **686 项通过**（R2 第一批后 673） |

## 6. 限制

1. **v7 未启用**：生产提示词仍是 v6；影子运行只在副本上进行。
2. **v7 单篇解析失败率 1/8**：输出更长，截断风险上升；生产路径的重排重试能覆盖，但需要实测。
3. **结构化率受语料限制**：8 篇里只有 1 篇是带数字与期间的官方发布；论坛帖没有可结构化的量。
4. 影子运行只覆盖 8 篇，不足以给出字段准确率；需要更大样本（G6 之后的评估批次）。
5. 冲突只在单库内检测；RSS 与 SEC/EIA 分库，跨库冲突未覆盖。

## 7. G6 待确认的增量事项

1. v7 提示词是否进入生产（本批只做了影子）。
2. 词表扩展：`revision` 是否需要 `advance_estimate`（或映射到 `preliminary`）；`period` 是否需要区间格式。
3. 「有数值无单位 → unverifiable」这条规则是否接受。
4. v7 输出截断的处理：是否提高 `max_tokens` 或让影子路径复用重排重试。
5. 冲突是否应出现在日报（当前只在同库有数据时出现；SEC 冲突走独立报告）。

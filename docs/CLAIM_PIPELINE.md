# 主张提取流水线（N0–N5）

版本：1.0 · 2026-11-01
定位：规定"文章 → 主张"这条链路怎么拆、每个节点的输入输出契约、失败语义与验收方式。
现状：**N0、N1 已实现并在 567 篇真实语料上验证；N2–N5 未开始。**
生产提示词仍是 v6，v7 仍是影子，切换判定仍是 **NOT READY**，启用需 G6。

---

## 1. 为什么拆

原来的做法是一条提示词同时完成：读懂文章、找到数字、判断主体与指标、判断变化口径、
生成完整 Claim。本地模型在一个任务上出错时，无法判断错在哪个环节，只能反复改总提示词。

拆分后的规则只有一条：**每个节点只解决一种问题。上一个节点交付确定的数据，下一个节点只处理
这些数据，不重新猜测上一个节点已经完成的事情。**

N0、N1、N4、N5 是确定性程序；只有 N2、N3 需要语义理解，交给本地模型。模型节点的输出永远是
"待核验材料"，不是事实。

## 2. 输入边界（必读）

这条流水线的输入是**本系统实际拿到的文本**：FreshRSS 提供的标题与摘要。
正文抓取（`full_text_fetch`）全部关闭，N0 没有全文可以标准化。

因此：

- 流水线的召回上限等于这段文本的召回；任何节点都不能超出它。
- N0 的 canonical text 与 `schema._normalize` 完全一致，N1 报告的偏移与证据定位器
  （`schema._locate`）报告的偏移是同一种偏移。
- "文章里的数字"在本系统里指"标题与摘要里的数字"。没有进 RSS 摘要的数字，本流水线看不见，
  也不会被伪装成看见。

## 3. 节点

| 节点 | 角色 | 只回答一个问题 | 输出 | 状态 |
|---|---|---|---|---|
| N0 | 程序 | 这篇文章的文本是什么，每段每句在什么位置 | 规范化文章对象（文本、段落、句子、raw 偏移、哈希） | **已实现** `article_text.py` |
| N1 | 程序 | 文本里出现了哪些数字表达 | 数字候选清单（唯一 ID、类别、原始表达、位置） | **已实现** `numeric_candidates.py` |
| N2 | 本地模型 | 这个数字描述的是谁、什么指标、是否构成主张 | 每个候选的主体/指标/理由/置信度 | 未开始 |
| N3 | 本地模型 | 这些数字之间是什么关系 | 水平/变化、同比/环比、方向、口径、修订、比较基准 | 未开始 |
| N4 | 程序 | 数值如何规范化 | 数值、数量级、币种、单位、期间、比较口径 | 未开始 |
| N5 | 程序 | 候选是否都被处理、Claim 是否可定位 | r2-v4 主张 + 未处理候选清单 | 未开始 |

N2 与 N3 必须分开：让模型一次完成"主体 + 指标 + 变化关系 + 期间 + 比较口径"，出错时无法定位
是主体识别错还是口径判断错；拆开后，每个模型节点有固定输入、固定 Schema、固定测试样本。

## 4. 已实现节点的契约

### N0 文章标准化（`opportunity_radar/article_text.py`，版本 `n0-v1`）

输入：`{'title': str, 'summary': str}`（也接受带同名属性的文章对象）。
输出：

| 字段 | 含义 |
|---|---|
| `text` | canonical text：去标签、解实体、折叠引号、折叠空白、小写；与 `schema._normalize` 相同 |
| `fields.title` / `fields.summary` | 每个字段的文本、`global_start`、`characters` |
| `segments[]` | 段落：`field`、`start`/`end`（字段内偏移）、`global_start`/`global_end`、`raw_start`/`raw_end`、`text` |
| `sentences[]` | 句子：同上，另含所属段落 `segment` |
| `source_hash` | 原始 title + summary 的 SHA-256 |
| `text_hash` | canonical text 的 SHA-256 |
| `stats` | 字符数、段落数、句子数 |

- 偏移以 canonical text 为准；`raw_span(field, start, end)` 把任意片段映射回原始 HTML。
- 段落按块级标签切分（`p/div/br/li/table/...`），空段落丢弃。
- 句子边界是确定性规则：数字中的点（`92.8`）与常见缩写（`u.s.`、`e.g.`）不断句。
  这是启发式，不是句法分析。
- 失败语义：没有任何标题或摘要时抛 `ValueError`，不产出空对象；空字段直接不出现
  （例如只有标题的文章没有 `summary` 字段）。

### N1 数字候选发现（`opportunity_radar/numeric_candidates.py`，版本 `n1-v1`）

输入：N0 输出。
输出：`{'version', 'source_hash', 'text_hash', 'candidates': [...], 'stats': {...}}`。

每个候选：

| 字段 | 含义 |
|---|---|
| `id` | 文章内唯一、按 `(title, summary)` 顺序与位置递增（`c0001`…） |
| `field` / `start` / `end` | 所在字段与 canonical text 偏移 |
| `global_start` / `global_end` | 在全文中的偏移 |
| `raw_start` / `raw_end` | 回到原始 HTML 的偏移 |
| `raw` | canonical text 的精确切片，如 `$92.8 billion`、`0.2 percent`、`2026-11-01` |
| `category` | `money` / `percent` / `percentage_point` / `quantity` / `magnitude` / `date` / `period` / `time` / `ratio` / `range` / `ordinal` / `identifier` / `bare` / `embedded` |
| `number_raw` | 数字本身，未乘数量级 |
| `value` | 按原样解析的数值（`54.5`，不是 `54 500 000 000`）；日期/期间/标识符为 `null` |
| `scale` / `scale_factor` | `billion` / `1e9`；中文 `亿`、`万` 保留原词 |
| `unit` / `unit_family` / `currency` | 数量级之外的基单位；`%` 与 `pp` 不同族 |
| `temporal` | 日期/期间的确定结构（year/month/day/quarter/range） |
| `flags` | 如 `parenthesized`（不加符号，留给下游判断）、`currency_conflict` |
| `sentence` / `segment` | 所属句子与段落 |
| `context` / `cues` | 前后文与词法线索（方向词、比较措辞），带偏移 |
| `status` | 恒为 `candidate`；N2–N5 才改变处置 |

规则：

- **nothing disappears**：每个十进制数字字符都属于且只属于一个候选。词内数字（`covid19`、
  `v2.0`）、URL 参数、编号都会成为候选（`embedded` / `identifier`），不会静默消失。
  `stats.coverage.uncovered` 必须为空；`m²` 的 2 是单位指数，不计为数字。
- **nothing is computed**：`$92.8 billion` 是 `value=92.8, scale=billion`，不是 `92.8e9`；
  数量级拆分、币种与单位选择留给 N4。
- 扫描是 leftmost-longest：同一位置取最长匹配，与已接受候选重叠的匹配被丢弃。
- 失败语义：找不到数字是合法结果（候选为空）；输入不是 N0 对象则抛 `ValueError`。
- 同一文本重复运行得到逐字节相同的输出（候选、ID、偏移、哈希）。

## 5. 未实现节点的契约草案（N2–N5）

这些是下一步的设计约束，不是已实现的行为。

- **N2 主体与指标**：输入是 N1 候选及其句子；每个候选必须得到 `bound` / `not_a_claim` /
  `uncertain` 之一与理由。`uncertain` 不等于丢弃。输出固定 Schema，由 llama.cpp 的
  JSON Schema 约束结构；Schema 只保证格式，不保证语义。
- **N3 变化关系**：只判断数字之间的关系（水平/变化、同比/环比、月度率/年度率、增/减、
  原始/修订、比较基准）。判断不了就保留原始表达并标 `unknown`，不得猜测。
- **N4 数值规范化**：数值解析、数量级、币种、单位、期间、比较口径的规范化计算。
  模型不参与计算，也不得改写原始数值。
- **N5 一致性与组装**：检查每个候选都有最终状态、每条主张都有证据定位、数值与原文一致、
  无重复与错误关联；最后映射到 r2-v4 契约，交给 r2-v2 核验。

## 6. 版本化与中间结果

每个节点记录：输入哈希、输出、节点版本；模型节点另记模型版本与文件哈希、Prompt / Schema 版本、
生成参数、耗时与错误。

已实现的部分：N0 输出 `source_hash` 与 `text_hash`；N1 输出携带两者与自身版本，可判断
"同一文本、同一节点版本是否得到同一结果"。**尚未实现**按文章哈希留存各节点中间结果的存储层；
在 N2 落地前，中间结果只写 JSONL（`tools/run_n1.py`），不进生产库。

确定性来自：结果可追溯、输入输出可复现、失败有明确状态、下游不覆盖上游结果。模型节点即使固定
temperature 与 seed，也不能把语义判断当作数学意义上的确定结论。

## 7. 与 R2 契约、v7 提示词的关系

- N0/N1 不改动 `claim_contract.py`（r2-v4）、`verify.py`（r2-v2）、生产提示词或评分门禁。
- N5 组装出的主张必须符合 r2-v4，才能进入 r2-v2 核验；N4 的数量级/单位拆分规则与
  `units.py` 的 `scale` / `unit` 区分一致。
- v7 提示词与影子运行保持不变；N2/N3 若接入，属于提示词与契约变更，仍在 G6 之下。

## 8. 已知限制

1. **只有标题与摘要**（见 §2），不是全文。
2. **拼写出来的序数不是数字候选**：`third quarter` 只留下 `2026` 这个 period 候选；
   数字形式的 `3rd quarter 2026` 才会被识别为一个 period。
3. **单位歧义不解决**：`5m` 会被记为 `metres`，`$` 会被记为 `USD`（CAD/AUD 无法从词法区分），
   `元` 没有映射到币种。这些都只是候选，N2/N4/N5 必须复核，不能直接当结论。
4. **N1 的类别是词法判断**：`3:30` 是 `time` 而不是 `ratio`，`312 to 119` 是 `range`，
   但词法无法判断它们是否重要。
5. **精确率没有人工基准**：基准只标注了"应该找到的数字"，没有标注"哪些候选是噪声"，
   因此 N1 的精确率是 **NOT_MEASURED**，不能对外声称。
6. **N2–N5 未实现**：流水线目前只到"候选清单"，没有主体、关系、标准化与组装。

## 9. 如何运行

```
python tools/run_n1.py --limit 50
python tools/run_n1.py --limit 600 --benchmark data/r2-shadow/benchmark.json
```

工具只读：从 FreshRSS 取文章，运行 N0、N1，把候选写到 `data/claim-pipeline/<时间戳>/`
（`n1.jsonl`、`summary.json`、`summary.md`）。不写生产库，不调用模型。
`--benchmark` 用手工标注的数字计算召回；未标注的口径会单独计数，不会被当成命中或遗漏。

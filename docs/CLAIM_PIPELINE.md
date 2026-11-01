# 主张提取流水线（N0–N5）

版本：2.0 · 2026-11-01
定位：规定"文章 → 主张"这条链路怎么拆、每个节点的输入输出契约、失败语义、留存方式与验收方式。
现状：**N0、N1 已实现并在 567 篇真实语料上验证；N2–N5 未开始。**
生产提示词仍是 v6，v7 仍是影子，切换判定仍是 **NOT READY**，启用需 G6。

本版按第八批规格（`docs/archive/R2_BATCH8_N0_N1_SPEC_2026-11-01.md`）重写了 N0/N1 契约：
候选偏移改为 N0 全文位置，候选类型与规格对齐，新增原子/复合表达分层、节点留存与识别器实测。

---

## 1. 为什么拆

原来的做法是一条提示词同时完成：读懂文章、找到数字、判断主体与指标、判断变化口径、
生成完整 Claim。本地模型在一个任务上出错时，无法判断错在哪个环节，只能反复改总提示词。

拆分后的规则只有一条：**每个节点只解决一种问题。上一个节点交付确定的数据，下一个节点只处理
这些数据，不重新猜测上一个节点已经完成的事情。**

N0、N1、N4、N5 是确定性程序；只有 N2、N3 需要语义理解，交给本地模型。模型节点的输出永远是
"待核验材料"，不是事实。

## 2. 输入边界（必读）

流水线的输入是**本系统实际拿到的文本**：FreshRSS 提供的标题与正文（RSS 摘要/正文）。
正文抓取（`full_text_fetch`）全部关闭，N0 没有全文可以标准化。

- 生产分析器对正文有 12,000 字符的上限；那是生产分析的选择，不是 N0 的输入限制。
  离线工具以 `max_content=0` 读取完整正文，N0 本身不截断，并在输出中记录 `content_truncated`。
- 流水线的召回上限等于这段文本；没有进 RSS 的数字，本流水线看不见，也不会被伪装成看见。
- N0 的 canonical text 对 HTML 输入与 `schema._normalize` 一致；N1 的偏移是 N0 全文偏移，
  与证据定位器的偏移同源，但 N5 仍应按引文重新定位。

## 3. 节点

| 节点 | 角色 | 只回答一个问题 | 输出 | 状态 |
|---|---|---|---|---|
| N0 | 程序 | 这篇文章的文本是什么，每段每句在什么位置 | 规范化文档（全文、段落、句子、偏移、哈希、版本） | **已实现** `article_text.py` |
| N1 | 程序 | 文本里出现了哪些数字表达，它们之间是什么关系 | 原子候选 + 复合表达组 | **已实现** `numeric_candidates.py` |
| N2 | 本地模型 | 这个数字描述的是谁、什么指标、是否构成主张 | 每个候选的主体/指标/理由/置信度 | 未开始 |
| N3 | 本地模型 | 这些数字之间是什么关系 | 水平/变化、同比/环比、方向、口径、修订、比较基准 | 未开始 |
| N4 | 程序 | 数值如何规范化 | 数值、数量级、币种、单位、期间、比较口径 | 未开始 |
| N5 | 程序 | 候选是否都被处理、Claim 是否可定位 | r2-v4 主张 + 未处理候选清单 | 未开始 |

N2 与 N3 必须分开：一次完成"主体 + 指标 + 变化关系 + 期间 + 比较口径"时，出错无法定位；
拆开后每个模型节点有固定输入、固定 Schema、固定测试样本。

## 4. N0 文章标准化（`opportunity_radar/article_text.py`，`n0-v1`）

### 输入

```json
{"article_id": "...", "source_id": "...", "title": "...", "content": "...",
 "content_format": "html|text", "language": "...", "source_url": "..."}
```

也接受现有文章对象（`title` + `summary`）；`summary` 视为正文，`content_format` 默认 `html`。
复用现有文章模型，不新建文章实体。

### 输出

| 字段 | 含义 |
|---|---|
| `document_id` | `sha256(n0 版本 + content_hash)`；同一内容同一版本稳定 |
| `article_id` / `source_id` / `source_url` / `language` / `content_format` | 输入元数据 |
| `normalization_version` / `ruleset` | 节点版本与规则源码哈希 |
| `content_hash` | `sha256(title + \0 + content)` |
| `text_hash` | `sha256(text)` |
| `title` | 原始标题（未规范化，便于展示与回溯） |
| `text` | 可搜索全文：标题 + 正文，规范化后 |
| `body_start` | 正文在 `text` 中的起点（无标题时为 0） |
| `paragraphs[]` | `paragraph_id`（`p0001`…）、`field`、`start/end`、`field_start/field_end`、`raw_start/raw_end`、`text` |
| `sentences[]` | `sentence_id`（`s0001`…）、`paragraph_id`、`field`、`start/end`、`text` |
| `offset_unit` | `unicode_codepoint` |
| `offset_convention` | `half_open`（`text[start:end]` 精确还原） |
| `content_truncated` | 调用方声明的上游截断标志 |
| `stats` | 字符数、段落数、句子数、正文字符数 |

### 必须保证的行为

- **原文可追溯**：段落与句子满足 `text[start:end] == record["text"]`；偏移是 Unicode code point，
  半开区间。`raw_start/raw_end` 映射回原始 HTML/文本。
- **不破坏数字定位**：HTML 标签转空格、实体解码、引号折叠、空白折叠、小写；数字表达式本身
  不被改写（`0.2 percent` 仍是 `0.2 percent`，`$92.8bn` 仍是 `$92.8bn`）。
- **正文完整**：N0 不截断；`text` 覆盖调用方提供的全部正文。
- **段落与句子**：HTML 按块级标签切段，纯文本按空行切段；句子按 `.!?。！？` 切分，
  数字中的点（`92.8`）与常见缩写（`u.s.`、`e.g.`）不断句。这是确定性规则，不是句法分析。
- **不做语义改写**：不合并不同段落，不做单位换算，不生成 Claim。
- **稳定性**：相同内容、相同版本、相同参数产生一致输出。
- **失败语义**：没有标题也没有正文时抛 `ValueError`，不产出空文档。

## 5. N1 数字候选（`opportunity_radar/numeric_candidates.py`，`n1-v1`）

### 输入

N0 输出。N1 不访问生产数据库，不读取 facts，不调用模型。

### 原子候选类型

规格要求的类型：`percentage`、`percentage_point`、`currency`、`quantity`、`scalar`、
`date`、`period`、`ratio`、`unclassified_numeric`。本项目另有明确状态：
`magnitude`（带数量级但无单位，如 `5 million`）、`time`（`3:30`）、`ordinal`（`3rd`）、
`identifier`（电话、引用编号、`10-K`、`Form 8-K`、长数字串）。

### 原子候选字段

| 字段 | 含义 |
|---|---|
| `candidate_id` | 由 content hash、N1 版本、类型、全文位置、原文内容确定的哈希 |
| `candidate_type` | 上表类型 |
| `raw_text` | N0 全文的精确切片 |
| `start` / `end` | N0 全文位置（Unicode code point，半开） |
| `field_start` / `field_end` | 在 title/body 字段内的位置（内部切片用） |
| `sentence_id` / `paragraph_id` | 对应 N0 的句子与段落 |
| `context` / `context_start` / `context_end` | 所在句子及全文位置 |
| `number_raw` | 数字本身，未乘数量级 |
| `value` | 按原样解析的数值（`54.5`，不是 `54 500 000 000`）；日期/期间/标识符为 `null` |
| `scale` / `scale_factor` | `billion` / `1e9`；中文 `亿`、`万` 保留原词 |
| `unit` / `unit_family` / `currency` | 单位与币种；`%` 与 `pp` 不同族 |
| `temporal` | 日期/期间/时间的确定结构 |
| `flags` | `parenthesized`、`currency_conflict`、`scientific` |
| `cues` | 句子内的方向/比较词，带全文位置；N1 只记录，不解释 |
| `detection_method` | `regex`（识别器未接入时） |
| `detection_status` | `detected` / `unclassified` / `ambiguous` |
| `related_candidates` | 同一复合表达中的其他候选 ID |

### 复合表达组 `expression_groups[]`

| 类型 | 识别规则 | 例 |
|---|---|---|
| `range` | 两个原子之间是 `–`、`—` 或 `-` | `2.1–2.5%` |
| `from_to` | 两个原子之间是 `to`（前有 `from`）或 `from`（前有 `to`） | `from 3.2% to 3.8%`、`to $92.8bn from $95bn` |
| `increase_decrease` | 方向词在数字前 40 字符内，或名词形式在数字后 20 字符内 | `increased 0.2%`、`0.3 percent increase` |
| `comparison` | 比较措辞与数字相距 ≤60 字符 | `compared with 3.2%` |
| `temporal_comparison` | 期间比较措辞（可无数字） | `year over year`、`over the past 12 months` |

组字段：`expression_id`、`expression_type`、`raw_text`、`start/end`（全文位置）、
`candidate_ids`（引用已有原子，不复制数字）、`sentence_id`、`paragraph_id`、
`detection_method`、`detection_status`。组不替代原子：`2.1–2.5%` 保留两个原子，再加一个 range 组。

### 不变量

- **没有数字会消失**：每个十进制数字字符都属于且只属于一个原子；词内数字与 URL 数字成为
  `unclassified_numeric`，不会被静默删除。`m²` 的指数不计为数字。`statistics.coverage.uncovered` 必须为空。
- **不计算最终值**：`$92.8 billion` 是 `value=92.8, scale=billion`；数量级、币种、单位换算留给 N4。
- **左端最长**：同一位置取最长匹配，与已接受原子重叠的匹配被丢弃；相邻数字不合并。
- **ID 稳定**：相同输入、相同版本、相同规则得到相同 ID；内容或规则变化产生新 ID / 新结果。
- **失败语义**：没有数字是合法结果；输入不是 N0 文档时抛 `ValueError`。

### 统计

`statistics`：`candidate_count`、`expression_group_count`、`unclassified_numeric_count`、`by_type`、
`coverage`（数字字符总数 / 已覆盖 / 未覆盖位置）。

## 6. N1 不做的事

N1 不判断：0.4% 是当前月变化率；0.3% 是上个月变化率；两者是否属于同一指标；是否构成重要 Claim。
这些是 N2、N3 的职责。N1 只交付"有哪些数字、原文是什么、位置在哪、文本声明了哪些关系"。

## 7. 留存与版本

`opportunity_radar/pipeline_store.py` 提供**独立的**追加式 SQLite 留存
（默认 `data/claim-pipeline/node_runs.sqlite3`），不写生产库，不改 RSS 业务表。

每条运行记录：`article_id`、`document_id`、`content_hash`、`node_name`、`node_version`、
`input_hash`、`output_hash`、`execution_status`、`executed_at`、`params_json`、`tools_json`、
`output_json`。主键包含 `(article_id, node_name, node_version, input_hash, params_json)`，
写入使用 `INSERT OR IGNORE`：相同运行不覆盖，正文/规则/版本变化产生新行，旧行保留。

规则源码哈希（`RULESET`）随输出保存，并进入 N1 的输入哈希与参数，因此"规则改了但版本号没变"
不会复用旧结果。N1 输出可在相同输入与规则下直接复用（工具默认复用并报告 `n1_reused`）。
失败运行带状态标记，不使用成功运行的键，因此一次瞬时失败不会让后续成功结果无法留存。

## 8. Microsoft Recognizers-Text 实测与结论

实测环境：Python 3.12.10，PyPI `recognizers-text*` **1.0.2a2**（alpha；需 `emoji==1.7.0` 才能导入），
包内没有 datetime 识别器，也没有 percentage / percentage-point 识别器（只有 number、currency、
dimension、age、temperature）。

用规格要求的表达式对比（规则 / Recognizers-Text / 组合，36 个样本）：

| 方法 | 候选 | 正确定位 | 未分类 | 定位失败 | 数字覆盖完整样本 |
|---|---|---|---|---|---|
| 规则 | 41 | 41 | 1 | 0 | 36/36 |
| Recognizers-Text | 45 | 45 | 0 | 0 | 33/36 |
| 组合 | 41 | 41 | 1 | 0 | 36/36 |

识别器的具体缺口：

- `0.2 percent`、`2 percentage points` 只返回数字，类型丢失；
- `$92.8bn` 返回 `$92.8`，数量级丢失；`USD 12.8 billion` 丢失币种（按普通数字返回）；
- `5 million vehicles` 只返回 `5 million`，单位丢失；
- `September 2026`、`Q3 2026`、`FY2025` 只返回数字年份，`FY2025` 完全识别不到；
- `15 per 100`、`3:1` 拆成两个数字；电话拆成四个数字；
- `10-K`、`Form 8-K`、版本号无分类；
- `year over year`、`month-on-month` 完全识别不到；
- `start/end` 的 `end` 是包含式索引，需要转换；resolution 会直接算出 `12.8 billion → 12800000000`，
  按规格不能当作最终 Claim 数值。

组合方法新增候选为 **0**：识别器能发现的都被规则覆盖，规则发现的识别器覆盖不到。
结论：**不引入为运行时依赖**。理由是覆盖与类型信息都不足，且会引入 alpha 依赖与偏移转换；
自定义规则保留为唯一运行路径。对比脚本 `tools/eval_numeric_tools.py` 可在安装了识别器的解释器中复跑，
输出 `data/claim-pipeline/tool-eval-*/comparison.json`。

## 9. 与 R2 契约、v7 提示词的关系

- N0/N1 不改动 `claim_contract.py`（r2-v4）、`verify.py`（r2-v2）、生产提示词、评分与门禁。
- N5 组装出的主张必须符合 r2-v4，才能进入 r2-v2 核验；N4 的数量级/单位拆分规则与
  `units.py` 的 `scale` / `unit` 区分一致。
- v7 提示词与影子运行保持不变；N2/N3 若接入，属于提示词与契约变更，仍在 G6 之下。

## 10. 已知限制

1. **只有标题与 RSS 正文**，不是全文；正文抓取关闭。
2. **拼写出来的序数不是数字原子**：`third quarter` 只留下 `2026`；数字形式 `3rd quarter 2026` 才整体识别为 period。
3. **单位歧义不解决**：`5m` 记为 metres，`$` 记为 USD（CAD/AUD 无法从词法区分），`元` 未映射币种。
4. **括号数字标为 `ambiguous`**：BEA 的 `(0.2 percent)` 是补充说明而不是负数，但 N1 不判断符号；
   N4 必须结合上下文处理，不能默认取负。
5. **`than` 等比较词会命中上界表达**（`less than $0.1 billion`）：N1 只记录线索，N3 解释。
6. **N1 精确率 NOT_MEASURED**：基准只标注"应找到的数字"，没有"哪些原子是噪声"的人工标注。
7. **N2–N5 未实现**：流水线目前到"原子 + 关系"，没有主体、指标、标准化与组装。

## 11. 如何运行

```
python tools/run_n1.py --limit 50
python tools/run_n1.py --limit 600 --benchmark data/r2-shadow/benchmark.json
python tools/eval_numeric_tools.py          # 需安装 recognizers-text 的解释器
```

`run_n1.py` 只读生产库、不调用模型：从 FreshRSS 取完整正文 → N0 → N1（可复用历史结果）→
`data/claim-pipeline/<时间戳>/`（`n1.jsonl`、`summary.json`、`summary.md`），并把节点运行写入
`data/claim-pipeline/node_runs.sqlite3`。`--benchmark` 用手工标注的数字计算召回，并列出命中位置。

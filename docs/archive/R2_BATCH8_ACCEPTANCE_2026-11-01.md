# R2 第八批（N0 + N1：契约对齐、复合表达与识别器实测）— 验收记录

日期：2026-11-01
结论：**N0、N1 已按第八批规格交付并在真实语料上验证；N2–N5 未开始。**
v7 仍未启用，生产仍是 v6；v7 切换判定仍是 **NOT READY**。本批不改变 Claim 契约、核验器、
评分、生产提示词或发布门禁。

规格：`R2_BATCH8_N0_N1_SPEC_2026-11-01.md`；现行契约：`docs/CLAIM_PIPELINE.md`。

---

## 1. 交付范围

本批把第七批的 N0/N1 按第八批规格重做，重点是：

1. N0 接受规格定义的输入（`article_id` / `content` / `content_format` / …），输出
   `document_id`、`content_hash`、段落/句子 ID、`offset_unit` / `offset_convention`。
2. N0 不再受 7,000 字符限制（本项目原本也没有该限制）；离线工具以 `max_content=0` 读取完整正文，
   N0 自身不截断。
3. N1 候选类型与规格对齐（`percentage`、`percentage_point`、`currency`、`quantity`、`scalar`、
   `date`、`period`、`ratio`、`unclassified_numeric`），候选偏移改为 N0 全文位置。
4. 原子候选与复合表达分层：`range`、`from_to`、`increase_decrease`、`comparison`、
   `temporal_comparison` 只引用原子 ID，不复制数字。
5. 新增独立、追加式的节点留存（`pipeline_store.py`），规则源码哈希进入输入哈希，规则变化不复用旧结果。
6. 独立实测 Microsoft Recognizers-Text 并作出是否引入的结论。

未做：N2、N3、N4、N5；未接入生产 Claim 流程；未启用 v7；未修改评分与门禁。

## 2. 实现位置

| 文件 | 内容 |
|---|---|
| `opportunity_radar/article_text.py`（`n0-v1`） | N0：输入契约、HTML/纯文本规范化、段落/句子/ID、全文与字段偏移、raw 偏移、哈希、`RULESET` |
| `opportunity_radar/numeric_candidates.py`（`n1-v1`） | N1：原子扫描与分类、数量级/单位/币种分离、日期/期间/时间/比率/识别号、复合表达组、覆盖检查 |
| `opportunity_radar/pipeline_store.py` | 独立追加式节点留存；`INSERT OR IGNORE`；按版本/输入/参数分键；失败运行不复用 |
| `tools/run_n1.py` | 只读工具：完整正文 → N0 → N1（可复用）→ JSONL/摘要；人工基准召回与命中位置 |
| `tools/eval_numeric_tools.py` | 识别器对比（规则 / Recognizers-Text / 组合），仅评估用，运行时不导入 |
| `tests/test_numeric_pipeline.py` | 54 项测试 |

对生产代码的唯一改动：`freshrss_client.py` 新增可选参数 `max_content`（默认 12,000，保持生产行为）
与 `_feed` 转发；生产分析器仍拿到 12,000 字符上限。默认调用路径不变，现有测试全部通过。

## 3. Microsoft Recognizers-Text 实测

### 安装与环境

- Python 3.12.10。
- PyPI 可用版本：`recognizers-text` / `-number` / `-number-with-unit` **1.0.2a2**（alpha）。
- 直接导入失败：`emoji` 2.x 移除了 `UNICODE_EMOJI`；固定 `emoji==1.7.0` 后可导入。
- **PyPI 上没有 `recognizers-text-datetime`**（返回 "no matching distribution"）。
- 包内没有 percentage / percentage-point 识别器：可用的只有 number、currency、dimension、age、temperature。

### 对比结果（36 个规格样本，规则 = 本项目 N1）

| 方法 | 候选 | 正确定位 | 未分类 | 定位失败 | 数字覆盖完整样本 |
|---|---|---|---|---|---|
| 规则 | 41 | 41 | 1 | 0 | 36/36 |
| Recognizers-Text | 45 | 45 | 0 | 0 | 33/36 |
| 组合 | 41 | 41 | 1 | 0 | 36/36 |

识别器重复/重叠 11 次；组合方法新增候选 **0**。

### 识别器缺口（逐例）

| 输入 | 规则 | Recognizers-Text |
|---|---|---|
| `0.2 percent` | percentage | scalar `0.2` |
| `2 percentage points` | percentage_point | scalar `2` |
| `$92.8bn` | currency `$92.8bn` | currency `$92.8`（数量级丢失） |
| `USD 12.8 billion` | currency | scalar `12.8 billion`（币种丢失） |
| `5 million vehicles` | quantity | scalar `5 million`（单位丢失） |
| `September 2026` / `Q3 2026` | date / period | scalar `2026` |
| `FY2025` | period | 无 |
| `year over year` / `month-on-month` | temporal_comparison | 无 |
| `15 per 100` / `3:1` | ratio | 两个 scalar |
| `+1-800-555-1234` | identifier | 四个 scalar |
| `10-K` / `Form 8-K` | identifier | scalar |
| `2.1–2.5%` | 两个原子 + range | 两个 scalar，无关系 |

其他实测细节：`start/end` 的 `end` 为包含式索引，半开区间需 `+1`；resolution 直接把
`12.8 billion` 算成 `12800000000`，按规格不能当作最终 Claim 数值。

### 结论：不引入

覆盖与类型信息都不足，组合方法没有新增任何候选；引入还会增加 alpha 依赖、偏移转换和
"resolution 不得当结论"的风险。**自定义规则保留为唯一运行路径**；对比脚本保留在
`tools/eval_numeric_tools.py`，可在装有识别器的解释器中复跑。

## 4. 真实语料验证

数据源：本机 FreshRSS 已批准来源的当前池，567 篇唯一文章（按 URL 去重）。
正文以 `max_content=0` 读取，N0 不截断。输出：`data/claim-pipeline/pool-final/`（本地证据，未提交）。

| 指标 | 数值 |
|---|---|
| 扫描文章 | 567（成功 567，失败 0） |
| 原子候选 | 4,334（每篇 7.64） |
| 复合表达组 | 337 |
| 未分类数字 | 1,269 |
| 无候选文章 | 140 |
| 数字字符覆盖 | **9,905 / 9,905**，`uncovered` 为空 |
| 正文被截断 | 0 |
| 耗时 | 7.27 秒 |
| 节点留存 | N0 567 行、N1 567 行；重跑复用 N1 **567/567** |

原子类型分布：scalar 2,252、unclassified_numeric 1,269、identifier 223、period 119、
currency 110、quantity 106、date 104、percentage 94、time 39、ordinal 10、magnitude 8。

### 人工基准

沿用第六批的 5 篇、19 个带单位数字：**19/19（100%）**，数字字符覆盖 83/83。
第六批同一基准上 v7 模型召回为 13/19（68%）。

### 五个 BEA 遗漏数字（规格第七节）

| 数值 | 原文 | 位置 | 句子 | 段落 | 状态 |
|---|---|---|---|---|---|
| 0.2%（monthly rate） | `0.2 percent` | 85–96 | s0002 | p0002 | detected；cue `at a monthly rate` |
| 0.5% | `0.5 percent` | 401–412 | s0003 | p0002 | ambiguous（原文括号，见 §6） |
| $92.8bn | `$92.8 billion` | 232–245 | s0003 | p0002 | detected |
| $12.8bn | `$12.8 billion` | 361–374 | s0004 | p0002 | detected |
| $0.1bn | `$0.1 billion` | 445–457 | s0005 | p0002 | detected |

同篇第二个 `0.2 percent`（317–328）也是 `ambiguous`，原因相同：BEA 用括号作补充说明，
不是会计负数。N1 记录 `parenthesized` 并标 `ambiguous`，把符号判断留给 N4。

## 5. 测试

- 新增/重写 `tests/test_numeric_pipeline.py`：54 项，覆盖 N0 契约与定位、原子类型表、
  变化/比较/期间关系、边界案例（电话、URL、引用、10-K、8-K、版本号、千分位、负数、括号数、
  科学计数法、重复数字、跨句相同数字）、ID 与顺序确定性、`candidate_ids` 可解析、节点留存复用。
- 全量：**765 项通过**（本批前 742）。

## 6. 未验证与缺口

1. **N1 精确率 NOT_MEASURED**：基准只标注"应找到的数字"，没有噪声标注。
2. **括号数字一律标 `ambiguous`**：BEA 的补充说明也被标；这是保守选择，N4 必须处理。
3. **只有标题与 RSS 正文**：正文抓取关闭；N0 没有正文以外的内容。
4. **拼写序数不识别**：`third quarter` 只留下 `2026`；`3rd quarter 2026` 才整体识别。
5. **单位歧义**：`5m` 记为 metres，`$` 记为 USD，`元` 未映射币种。
6. **N2–N5 未实现**：没有主体、指标、标准化与 Claim 组装。
7. **识别器结论基于 1.0.2a2**：若上游发布包含 datetime / percentage 的新版本，需要重跑对比。

## 7. 生产影响检查

- 未写生产数据库；N0/N1 不读数据库。节点留存写入独立的 `data/claim-pipeline/node_runs.sqlite3`。
- 未修改 `claim_contract.py`、`verify.py`、`units.py`、`analyzer.py`、`prompts/`、`schema.py`、
  `digest.py`、`publication.py`、评分与门禁。
- `freshrss_client.py` 的 `max_content` 默认值与生产行为一致；只有离线工具传 `0`。
- v7 未启用；生产提示词 v6；G6 未批准。

## 8. 变更清单

| 类型 | 文件 |
|---|---|
| 新增 | `opportunity_radar/pipeline_store.py`、`tools/eval_numeric_tools.py` |
| 重写 | `opportunity_radar/article_text.py`、`opportunity_radar/numeric_candidates.py` |
| 重写 | `tests/test_numeric_pipeline.py`、`tools/run_n1.py` |
| 修改 | `opportunity_radar/freshrss_client.py`（可选 `max_content`，默认不变） |
| 文档 | `docs/CLAIM_PIPELINE.md`、本文件、`docs/archive/R2_BATCH8_N0_N1_SPEC_2026-11-01.md`、`docs/archive/README.md`、`docs/PROJECT_STATUS.md`、`docs/IMPLEMENTATION_PLAN.md`、`docs/ARCHITECTURE.md`、`README.md`、`CLAUDE.md` |

## 9. Git

- 第八批提交在 `feat/evidence-lanes-source-governance` 上，连同第七批一起推送。
- `main` 已合并过该分支的 PR #7，但 PR #7 **不包含**第七、八批提交；推送后需要新的 PR 才能进入 `main`。

# 影子运行对比：基线 vs 候选配置（2026-10-23）

> 目的：在不改评分、证据和准入规则的前提下，比较"原有 7 个社区来源"与"加入官方/新闻来源后的 14 个来源"
> 在**同一台机器、同一个 FreshRSS、同一个模型**上的实际产出差异。
> 结论只覆盖这一次运行；样本量很小，不能外推为稳定收益。

## 设置

| 项 | 基线 | 候选 |
|---|---|---|
| 配置 | `data/shadow/baseline.csv` | `data/shadow/candidate.csv` |
| 启用来源 | 7（原有社区/技术源，feed id 3–9） | 14（新增 NVIDIA、BEA、Census、Fed、ONS、BBC、NYT） |
| 数据库 | `data/shadow/baseline.sqlite3` | `data/shadow/candidate.sqlite3` |
| 报告目录 | `reports/shadow-baseline/` | `reports/shadow-candidate/` |
| 运行方式 | `--dry-run`，`OR_MAX_ARTICLES=6` | 同左 |
| 模型 | Qwen3-30B-A3B-Instruct-2507-Q4_K_M | 同左 |

两个数据库相互隔离，互不复用历史分析；运行期间**没有**并发进程（第一次尝试因后台进程重叠而作废，已删除其结果）。

复现：

```powershell
$env:OR_SOURCES_PATH='data/shadow/baseline.csv'
$env:OR_DB_PATH='data/shadow/baseline.sqlite3'
$env:OR_REPORT_DIR='reports/shadow-baseline'
$env:OR_MAX_ARTICLES='6'
.\.venv\Scripts\python.exe -m opportunity_radar.cli --dry-run
```

候选配置把路径换成 `candidate` 即可；先把两个数据库删掉，否则第二轮会把文章当作"已分析"跳过。

## 结果

| 指标 | 基线 | 候选 |
|---|---|---|
| 获取 / 新增 / 进入分析 / 成功 / 失败 | 6 / 6 / 6 / 6 / 0 | 6 / 6 / 6 / 6 / 0 |
| 参与产出的来源数 | 6 | 6 |
| 来源构成 | 全部为社区/论坛 | 全部为官方/媒体 |
| A 通道分析条目 | **0** | **6** |
| B 通道 | 4 | 0 |
| C 通道 | 2 | 0 |
| `priority` | 1 | 2 |
| `watch` | 2 | 3 |
| `filtered` | 3 | 1 |
| 证据分布 | E2 2 · E1 2 · E0 2 | E2 0 · E1 5 · E0 1 |
| 情报主线 | 工程 4 · 市场机会 2 · 科技 2 | 宏观 3 · 国际新闻 2 · 企业资本 1 |

来源清单：

- 基线：Hacker News Ask、Hacker News Show、preCICE、ParaView、SALOME、SimScale 论坛。
- 候选：BBC、Federal Reserve、NVIDIA Newsroom、NYT、UK ONS、US Census。

## 怎么读这组数字

**成立的部分**

1. **A 通道从"没有输入"变成"每个条目都来自官方或新闻"**。基线日报的商业情报段是空的，只能靠 B/C 通道的社区信号撑版面；这正是本轮要修的结构问题。
2. **过滤率下降**：基线 6 条里 3 条被过滤（招聘、证据不足、无商业信号），候选 6 条里只有 1 条。官方来源的标题与摘要更容易定位，`filtered/insufficient_evidence` 明显减少。
3. **主线覆盖发生变化**：基线只有工程与社区两类，候选第一次出现宏观、国际新闻与企业资本。

**不能声称的部分**

1. **候选 E2 为 0，基线 E2 为 2**。这不是退步，而是来源形态不同：基线里的论坛帖是完整正文（复核为 `full_text`），官方 Feed 只有标题和短摘要（`excerpt`），按现行规则只能到 E1。E2 需要解决正文获取，不能靠调低门槛。
2. **候选样本 100% 来自新来源，是首轮偏差**。新接入的 BBC/NYT/NVIDIA 条目更新更频繁，`OR_MAX_ARTICLES=6` 且按来源轮流取最新时，旧来源没有进入样本。它不代表日常比例；要判断稳定结构，需要连续多天的运行。
3. **`priority` 从 1 到 2 不构成"质量提升"**。两个样本都太小，且分数是通道内相对值，A 通道与 B/C 通道的分数不可直接比较。
4. **没有任何人工有用率数据**。"更多官方条目"不等于"更值得读"，需要用 `review` 标签在真实阅读后统计。

## 这次运行没有证明什么

- 没有证明官方来源会持续更新（每个来源只刷新过一次）；
- 没有证明条款允许长期保存与摘要（许可仍全部为 unknown）；
- 没有证明新来源的正文足以支撑结论（`excerpt` 是操作分类，不是完整性质检）；
- 没有证明去重有效（本轮没有出现跨来源同一事件）。

## 下一步（需要真实数据后再定）

1. 连续运行 7 天，按来源统计：抓取成功率、空正文率、`priority` 命中、人工有用率。
2. 在 A 通道观察官方条目是否重复（同一发布会多篇稿）以及是否需要通讯社转载识别。
3. 若 E2 长期为 0，先评估"官方页面正文获取"（PDF/HTML 解析），而不是降低 `promote_rank`。

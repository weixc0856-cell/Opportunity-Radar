# S0 来源覆盖审计（第一步：现有来源盘点与缺口矩阵）

状态：**P0 已冻结**。本文件覆盖 S0-1（来源盘点）、S0-2（采集能力审计，含 FreshRSS 映射与 robots 实测）、
S0-3（覆盖缺口）与重复分析、S0-4 的 P0 最终评审（§7）；P1/P2 未开始，S0-5 未开始，不做接入。
日期：2026-11-01
阶段边界：只读。未修改代码、数据库、配置或依赖；未创建连接器；未启动 R0/S1。

## 0. 方法与结论标注

数据来源：

- `config/sources.local.csv`（47 行登记，15 行启用）
- 生产库 `data/opportunity_radar.sqlite3`：articles、analyses、analysis_failures、analysis_sections
- 代码：`freshrss_client.py`、`fulltext.py`、`page_monitor.py`、`datasets.py`
- 统计窗口：数据库全部文章，published 2026-10-06 至 2026-11-01（16 个有文章的日期；日采集从 2026-10-22 起稳定）

结论标注：

- **实测**：来自数据库或配置的直接计数。
- **登记**：来自来源登记表声明，未实测。
- **NOT_MEASURED**：样本或能力不足，不做判断。
- **待核验**：涉及外部来源的 API、许可、配额，本轮未查证。

本报告不预设"RSS 不够用"。它只回答三个问题：现在监测什么、遗漏什么、重复多少。
是否引入外部来源、是否替换现有来源，由后续步骤和用户决定。

---

## 1. 现在究竟在监测什么

### 1.1 登记与启用

| 项 | 数值 | 标注 |
|---|---|---|
| 登记行 | 47 | 实测 |
| 启用 | 15 | 实测 |
| approved 但未启用 | 0 | 实测 |
| `review_required`（未核验许可，保持禁用） | 32 | 实测 |
| 运行期依赖 | 0 个第三方包 | 实测 |

### 1.2 启用来源与实测产出

窗口为该来源在库中的全部文章（published 首末日期）。

| 来源 | 层级 | 声明通道 | 访问级别 | 文章 | 已分析 | 覆盖天数 | E0/E1/E2 | priority/watch/filtered |
|---|---|---|---|---|---|---|---|---|
| Hacker News — Ask | L5 | B | excerpt | 20 | 19 | 8 | 0/19/0 | 0/0/19 |
| Hacker News — Show | L5 | B | excerpt | 22 | 19 | 8 | 3/16/0 | 0/2/17 |
| OpenAI Developer Community | L5 | B | full_text | 11 | 9 | 8 | 0/1/8 | 1/1/7 |
| ParaView Forum | L5 | B,C | full_text | 8 | 7 | 6 | 0/1/6 | 1/1/5 |
| SimScale Community Forum | L5 | B,C | full_text | 7 | 7 | 6 | 1/1/5 | 0/3/4 |
| preCICE Forum | L5 | B,C | full_text | 2 | 2 | 2 | 0/0/2 | 1/1/0 |
| SALOME Platform Forum | L5 | B,C | auto | 1 | 1 | 1 | 1/0/0 | 0/0/1 |
| NVIDIA Newsroom | L0 | A | auto | 4 | 4 | 4 | 0/4/0 | 4/0/0 |
| U.S. BEA | L0 | A | excerpt | 3 | 3 | 2 | 0/3/0 | 2/1/0 |
| Federal Reserve | L0 | A | excerpt | 2 | 2 | 2 | 2/0/0 | 0/0/2 |
| UK ONS | L0 | A | excerpt | 3 | 3 | 3 | 0/3/0 | 2/1/0 |
| BBC Business | L3 | A | excerpt | 7 | 7 | 6 | 0/7/0 | 1/6/0 |
| NYT Business | L3 | A | excerpt | 7 | 6 | 7 | 1/5/0 | 1/4/1 |
| BBC Technology | L3 | A | excerpt | 7 | 5 | 7 | 0/5/0 | 1/4/0 |
| NYT Technology | L3 | A | excerpt | 6 | 5 | 6 | 0/5/0 | 2/3/0 |
| **合计** | | | | **110** | **99** | | **8/70/21** | **16/27/56** |

说明：E0/E1/E2 为评分记录中的证据秩；`priority/watch/filtered` 为确定性评分状态，未包含来源配额造成的 deferred。

证据秩与证据状态是两套口径：秩来自 `scoring.evidence_rank`，状态来自 `scoring.evidence_state`。
9 条 v4 旧记录没有 state，其中 3 条秩为 E0、6 条为 E1。因此 E0 的 8 条 = `title_only` 3 + `unlocated_quotes` 2 + 旧记录 3；
E1 的 70 条 = `rss_excerpt_only` 64 + 旧记录 6。§1.6 给出逐项对账。

### 1.3 分层结构

| 层级 | 含义 | 启用来源 | 文章 | 占比 |
|---|---|---|---|---|
| L0 原始事实 | 政府统计、央行、企业公告 | 4 | 12 | 10.9% |
| L1 国际研究/数据机构 | IMF、OECD、World Bank、Eurostat 等 | **0** | 0 | 0% |
| L2 咨询与产业研究 | McKinsey、四大等 | **0** | 0 | 0% |
| L3 权威新闻 | BBC、NYT | 4 | 27 | 24.5% |
| L4 专业技术 | 论文、标准、研究实验室 | **0** | 0 | 0% |
| L5 早期信号 | 论坛、社区、项目发布 | 7 | 71 | 64.5% |

### 1.4 产出按层级与状态

| 层级 | 已分析 | priority | watch | filtered | priority 占比 |
|---|---|---|---|---|---|
| L0 | 12 | 8 | 2 | 2 | 66.7% |
| L3 | 23 | 5 | 17 | 1 | 21.7% |
| L5 | 64 | 3 | 8 | 53 | 4.7% |

注意：L0/L3 的访问级别多为 `excerpt`，证据秩被限制在 E1；L5 中声明 `full_text` 的来源可以进入 E2。
因此这里的 priority 比例同时受**内容基础**与**评分规则**影响，不能单独作为来源质量结论。

### 1.5 通道

| 通道 | 已分析 | 来源构成 |
|---|---|---|
| A 商业、科技与经济情报 | 35 | L0 12 + L3 23 |
| B 商业机会 | 53 | L5 全部（hn-ask 17、hn-show 17、openai 8、paraview 5、simscale 5、precice 1） |
| C 技术观察与工程信号 | 2 | preCICE 1、ParaView 1 |
| 无通道记录（v4 旧记录） | 9 | 遗留记录，未重新路由 |

声明通道与实际通道存在偏差：15 个启用来源中，4 个声明包含 C，但 10 天内只产生 2 条 C 通道分析；
内容路由按内容判定，声明只做收窄。

### 1.6 证据状态与内容基础

| 证据秩 | 证据状态 | 数量 | 说明 |
|---|---|---|---|
| E0 | `title_only` | 3 | 仅标题 |
| E0 | `unlocated_quotes` | 2 | 引文无法定位 |
| E0 | 无 state（v4 旧记录） | 3 | 旧格式，秩按 E0 计 |
| E1 | `rss_excerpt_only` | 64 | 摘要引文可定位 |
| E1 | 无 state（v4 旧记录） | 6 | 旧格式，秩按 E1 计 |
| E2 | `primary_source_located` | 21 | 一手来源正文引文可定位 |
| **合计** | | **99** | |

对账：E0 8 = 3 + 2 + 3；E1 70 = 64 + 6；E2 21。旧记录没有 `evidence_state`，不得把它们当作 `rss_excerpt_only` 或 `title_only` 统计。

`multi_source_coverage` 出现 **0 次**；`market_validation` 为 `single_source` 的占 90/99。
原因是同一事件的判定依赖 `event_key`（规范化标题哈希），跨来源不同标题永远不相等（见 §3）。

### 1.7 主题与类别

分析结果的 `article_type`：

| 类别 | 数量 | 占比 |
|---|---|---|
| general | 55 | 55.6% |
| user_pain | 16 | 16.2% |
| tech | 12 | 12.1% |
| product | 8 | 8.1% |
| funding | 7 | 7.1% |
| hiring | 1 | 1.0% |

### 1.8 现有采集能力与限制（代码层）

| 能力 | 现状 | 限制 |
|---|---|---|
| Feed 接入 | 仅 FreshRSS Fever API（POST，20 秒超时）；按 Feed ID 逐一读取，来源轮转取样 | 没有通用连接器；不能直接读 RSS 或 JSON API |
| 正文抓取 | 按来源选择 `article_page`；先读 robots.txt；401/403/429 立即停止 | 全库 `full_text_fetch` 均为 `none`；单轮上限 20 页；无 JavaScript；失败不重试 |
| 页面监测 | 仅记录链接与标题；遵守 robots 与最小间隔（默认 6 小时） | 不抓正文；JS 渲染页面（如中国政府网）标为 blocked |
| 结构化数据 | `datasets.py` 探测已批准端点并解析 JSON-stat | 只探测最新期，不存历史序列；未批准数据集保持 blocked |
| 配额 | 登记表有 `max_requests_per_day` | **代码未强制**；全局只受 `OR_MAX_ARTICLES` 与 FreshRSS 抓取约束 |
| 来源配额 | `source_cap` 只影响本期分发（deferred） | 不改变评分，也不跨期承载 |
| 重试 | 采集层无退避重试 | 单源失败只记录，不自动恢复（R0 计划覆盖模型调用，不覆盖采集） |
| 来源身份 | 文章只存 `source_name` | 无 `source_id`/`connector`/`external_id`；3 篇无法按名称归属 |

### 1.9 采集节奏

- 论坛/社区：每天 1–3 条，覆盖 6–8 天。
- 新闻媒体：每天约 1 条，覆盖 6–7 天。
- 官方统计：10 天内 2–3 条（ONS、BEA、Fed），存在 3–7 天的间隔。
- 数据库最早文章为 2026-10-06（BEA），但日采集从 2026-10-22 起稳定。

### 1.10 FreshRSS Feed 映射与 robots 实测（S0-2 收尾）

**Feed 映射（2026-11-01，只读访问本机 FreshRSS Fever API）**

| 检查 | 结果 |
|---|---|
| FreshRSS 订阅数 | 27 |
| 启用来源的 Feed ID | 15 / 15 全部存在，无缺失 |
| FreshRSS 中不属于登记表的 Feed | 0 |
| 仍订阅但登记表未启用的 Feed | 12（OpenAI News、DeepMind、Hugging Face、TechCrunch、Simon Willison、GitHub Blog、SimScale Blog、HN Front Page、US Census、BBC News、NYT Home、FreshRSS Releases） |
| 启用来源中名称与 Feed 标题不一致 | 5（SALOME、SimScale、BEA、Fed、ONS） |

**四层权限必须分开记录**（不要用"退订/不退订"一个动作处理）：

| 层级 | 含义 | 当前状态 |
|---|---|---|
| 1. FreshRSS 抓取 | FreshRSS 是否继续拉取该 Feed | 27 个 Feed 全部在抓，含 12 个未批准 |
| 2. Opportunity Radar 读取 | 程序是否从 Fever API 读取 | 只读取 15 个已批准 Feed ID |
| 3. 进入分析 | 是否送入模型与评分 | 只有读取到的已批准来源文章 |
| 4. 正式情报输出 | 是否进入简报 | 只有通过证据与评分门槛的条目 |

12 个未批准 Feed 的新状态记为 **`subscribed_unapproved`**：FreshRSS 仍在抓取，但 Opportunity Radar 不读取、
不分析、不输出。**本轮不建议退订**：其中 DeepMind、Hugging Face、GitHub Blog、US Census 等可能有研究价值，
应在 S0-4 评估后再决定保留、隔离或退订。该状态目前只记录在审计报告中（S0 只读，未修改登记表）。

其他含义：

- 映射本身完整，采集不会漏源。
- 5 处名称不一致解释了 §3.4 的 3 篇无法按名称归属；`source_id` 绑定仍是必要的。

**robots.txt（2026-11-01，使用项目 UA `OpportunityRadar-PageWatch/0.1`）**

| 域名 | 检查路径 | 结果 |
|---|---|---|
| news.ycombinator.com | `/ask` | 允许（12 条适用规则） |
| precice.discourse.group | `/` | 允许（15 条） |
| discourse.paraview.org | `/` | 允许（15 条） |
| discourse.salome-platform.org | `/` | 允许（15 条） |
| community.openai.com | `/` | 允许（15 条） |
| forum.simscale.com / www.simscale.com | `/`、`/forum/` | 允许（15 / 28 条） |
| nvidianews.nvidia.com | `/` | 允许（1 条） |
| www.bea.gov | `/` | 允许（52 条） |
| www.federalreserve.gov | `/` | robots.txt 404，视为无规则 |
| www.ons.gov.uk | `/` | robots.txt 404，视为无规则 |
| www.bbc.com / www.bbc.co.uk | `/news/business`、`/news/articles/` | 允许（49 / 57 条） |
| www.nytimes.com | `/section/business` | 允许（109 条） |

限制：

- 这只说明**我们的页面抓取 UA** 在检查时被允许；FreshRSS 服务端抓取 Feed 不受此检查覆盖。
- robots 允许不等于获得许可，也不等于允许保存或再发布正文；许可仍以来源登记与条款核验为准。
- 检查是单次快照，站点规则会变化；每个来源启用前应重新检查。

---

## 2. 遗漏了什么（相对 PRD 研究范围的缺口矩阵）

判断口径：以 `docs/PRD.md` §1.1 与 §3 的研究范围为目标，对照登记、启用与实际产出。
"缺口"不等于"必须接入"；它只表示当前没有可用的信息输入。

| 研究维度 | 需要的层级 | 登记情况 | 启用 | 实测产出 | 缺口判断 |
|---|---|---|---|---|---|
| 全球宏观（GDP、通胀、就业、利率） | L0/L1 | BEA、Fed、ONS、BLS（禁用）、IMF（禁用）、OECD（禁用）、World Bank（禁用） | 3 | 12 篇（BEA 3、Fed 2、ONS 3，另 NVIDIA 4 属企业） | 部分覆盖；缺就业（BLS 禁用）、通胀、欧元区与中国 |
| 货币与财政政策 | L0/L3 | Fed、PBC（禁用）、Reuters/AP/AFP（禁用） | 1 | 2 篇（Fed 新闻稿） | 严重不足：只有新闻稿，无政策分析来源 |
| 贸易与地缘经济 | L0/L1/L3 | BEA 贸易发布、ONS 贸易发布 | 2 | 包含在宏观统计中 | 只有统计发布，无贸易政策与地缘来源 |
| 产业政策与监管 | L0/L3 | PBC（禁用）、中国政府网（page_watch **blocked**，JS 渲染） | 0 | 0 | 空白 |
| 企业经营、资本开支、并购、订单 | L0/L3 | NVIDIA Newsroom、NVIDIA IR（禁用）、AMD IR（禁用）、无 SEC EDGAR | 1 | 4 篇 | 严重不足：只有一家企业的新闻稿，无财报与申报数据 |
| 市场供需、价格、库存、产能 | L1/L2/L3 | 无专门来源 | 0 | 0 | 空白 |
| AI、半导体、算力、数据中心 | L0/L3/L4 | NVIDIA Newsroom、BBC/NYT Technology、arXiv（禁用）、SIA（禁用）、IEEE Spectrum（禁用） | 3 | 13 篇科技新闻 + 4 篇 NVIDIA + 论坛讨论 | 部分覆盖；缺产业数据与论文 |
| 能源 | L0/L1 | 无 | 0 | 0 | 空白 |
| 制造业、汽车、机器人、新材料 | L0/L3/L4 | 无产业来源 | 0 | 0 | 空白 |
| 工业软件与 CAE | L4/L5 | 4 个工程论坛 | 4 | 18 篇（ParaView 8、SimScale 7、preCICE 2、SALOME 1） | 有用户侧信号，无厂商与产业侧证据 |
| 中国与亚洲 | L0/L3 | PBC（禁用）、国家统计局（page_watch，只记录链接，不抓正文） | 0 | 0 | 空白 |
| 欧洲（非英国） | L0/L1 | 无 | 0 | 0 | 空白 |
| 学术与技术证据 | L4 | arXiv cs.AI / cs.LG、Microsoft Research、Google Research（均禁用） | 0 | 0 | 空白 |
| 咨询与产业研究 | L2 | 登记表中不存在此类来源 | 0 | 0 | 登记层缺失 |
| 商业机会与用户痛点 | L5 | HN、OpenAI 社区、4 个工程论坛 | 7 | 71 篇，B 通道 53 条 | 有量；其中 priority 3 条、watch 8 条 |

### 2.1 地理覆盖（登记 + 实测）

| 地区 | 启用来源 | 文章 |
|---|---|---|
| 美国 | BEA、Fed、NYT Business/Technology、NVIDIA | 22 |
| 英国 | ONS、BBC Business/Technology | 17 |
| 全球平台（非地域新闻） | HN、OpenAI 社区、工程论坛 | 71 |
| 中国 | 0（PBC 禁用；NBS 仅页面监测） | 0 |
| 欧洲（非英国） | 0 | 0 |
| 亚洲其他 | 0 | 0 |

### 2.2 情报主线（登记声明）

启用来源覆盖 `macro_economy`（3）、`international_news`（4）、`corporate_capital`（1）、
`engineering_specialist`（4）、`market_opportunity` + `technology_research`（3）。
主线 `policy_regulation`、`industry_supply_chain`、`system_maintenance` 的启用来源数为 **0**。

### 2.3 缺口优先级（用户确认，2026-11-01）

| 优先级 | 维度 |
|---|---|
| P0 | 中国与亚洲；产业政策与监管；制造业、汽车、机器人、新材料；企业经营、财报、资本开支；能源 |
| P1 | 全球宏观经济；欧洲（非英国）；AI、半导体、算力、数据中心；学术与技术证据；市场供需、价格、库存、产能 |
| P2 | 咨询与产业研究；工业软件与 CAE；商业机会与用户痛点 |

约束：

- P2 不代表删除现有来源，只代表暂不投入大量接入与维护资源。
- L0–L5 是分析来源的工具，不是必须填满的 KPI；不因层级空缺而接入低价值来源。
- 每批来源接入必须回答：它带来了什么此前无法获得、或无法可靠获得的信息。

---

## 3. 重复与转载

### 3.1 可测量项（实测）

| 检查 | 结果 | 说明 |
|---|---|---|
| 相同 `event_key`（规范化标题完全一致） | 0 组 / 110 篇 | 无同标题重复 |
| 相同 `summary_hash` | 0 组 | 无完全相同内容 |
| 标题 Jaccard ≥ 0.5 | 0 对 | 110 篇两两比较 |
| 最高标题相似度 | 0.44 | BEA 美国贸易 × ONS 英国贸易——不同经济体，不是重复 |
| 规范化 URL（保留查询参数）重复 | 0 | — |
| 同源重复（同一来源内） | 0 | — |

### 3.2 不能测量项（NOT_MEASURED）

- **跨来源同一事件**：标题相似度无法识别"同一政策的不同措辞"。当前 `event_key` 只做同标题哈希，
  因此跨来源事件重复没有测量手段；需要 R1 的事件关联。
- **转载/通讯社共用稿**：登记表没有谱系字段，无法判断 BBC 与 NYT 是否引用同一通讯社。
- 因而 `multi_source_coverage` 为 0、`single_source` 为 90/99 是**结构性结果**，不是"这些事件只有一个来源"的证据。

### 3.3 已知的重复案例（来自历史实验，不在本窗口）

`docs/OPEN_ISSUES.md` ISSUE-003 记录的 ONS 零售销售双条目、NYT 同稿跨栏目，属实验数据；
本生产窗口未出现同类。样本量不足，不能据此认为重复问题已消失。

### 3.4 来源身份缺陷

有 3 篇文章无法通过登记名称匹配到来源（SimScale Forum 2 篇、SALOME Forum 1 篇），
因为 FreshRSS 的 Feed 标题与登记名称不同。它们已被计入上表的人工别名映射；
这说明**按名称归属来源不可靠**，与 PRD FR-S3（文章直接绑定 `source_id`）一致。

### 3.5 低信息条目

- E0 共 8 条：`title_only` 3 条、`unlocated_quotes` 2 条，另有 3 条 v4 旧记录没有证据状态（按 E0 计入）。
- 标题为 `Show HN` 的条目 1 条；标题长度 < 15 字符的 3 条。
- 这些条目进入分析会消耗模型时间，但不产生可发布内容。

---

## 4. 事实性观察（不构成接入建议）

1. **体量与价值来源相反**：L5 提供 64.5% 的文章，但只贡献 3 条 priority；L0 提供 10.9% 的文章，贡献 8 条 priority。
2. **层级断裂**：L1、L2、L4 的启用来源为 0；L2 在登记表中完全不存在。L0 只有美国与英国。
3. **C 通道几乎为空**：10 天 2 条，且都来自工程论坛的问答，不是技术进展或产品发布。
4. **官方来源节奏慢**：ONS/BEA/Fed 合计 8 篇/10 天，间隔 3–7 天；这属于发布日历特性，不是抓取故障。
5. **重复无法判断**：标题级检查为 0，但事件级能力缺失；`multi_source_coverage` 从未触发。
6. **来源身份与名称耦合**：3 篇无法按名称归属；文章表没有 `source_id`。

---

## 5. 未测项与限制

| 项 | 状态 | 原因 |
|---|---|---|
| Unique Event Yield | **NOT_MEASURED** | 没有事件实体；当前 `event_key` 去重后每篇都是独立事件，proxy 恒为 1，无评价意义 |
| Signal Yield（每来源） | **proxy only** | 只能用"可识别事件条目数/文章数"，且 R1 前等于 1 |
| Independent Evidence Yield | **NOT_MEASURED** | 无来源谱系，无法判断独立性 |
| Source Cost per Useful Event | **NOT_MEASURED** | 无 API 成本；维护工时未记录 |
| 跨源事件重复率 | **NOT_MEASURED** | 需要 R1 事件关联 |
| L0/L3 的 E2 能力 | 受声明限制 | 访问级别为 `excerpt`，即使正文可用也不会产生 E2 |
| 外部候选来源的 API/许可 | **待核验** | S0-4 未开始；本报告不含任何外部 API 结论 |
| 长期稳定性 | **未观察** | 10 天窗口、110 篇；rates 只作参考 |

---

### 5.1 基线冻结（2026-11-01）

本报告的全部计数以此快照为准，后续不得混用：

| 对象 | 记录值 | 说明 |
|---|---|---|
| 数据库 | `data/opportunity_radar.sqlite3`，SHA-256 `8c8194659af7c7630bd12583fa5cf8492e2180ff3ec7192b707403ce9298f425`，1,925,120 字节 | 本文所有计数来源 |
| 数据库 `user_version` | 0 | 尚无迁移记录 |
| 代码 | Git commit `e79dff923efe867ac2c23ad51ddc5b6bfdbf8dc6` | 分支 `feat/evidence-lanes-source-governance` |
| 来源登记 | `config/sources.local.csv`，SHA-256 `b0b9b0794c73c924761f461fe20000d539fc228ac67440950f437371e4b4f691`，28,129 字节，**gitignored** | 未包含在 commit 中，必须单独记录哈希 |
| 评分配置 | `config/scoring.toml`，SHA-256 `b0e87ca95b3ed2779db6715781bf99effb958b73ce65bf4bcd302659455b3cac` | 已跟踪 |
| 提示词文件 | `prompts/analyst.md`，VERSION 6，SHA-256 `0d546f010fc8286bbc8a2796032ff8b484d397edd99eabf1cd9731c3d012d224` | 已跟踪 |
| 共享提示词 | `output_contract.md` `4a11bf73…`；`style_guide_zh.md` `216bc86d…` | 运行时追加，单独变更会改变提示词 |
| 运行时提示词 | 完整 SHA-256 `b9b5666851ad14ae01740b580602f2003caef9dc0891f4e5923ae034c8bff140`（短号 `b9b5666851ad`） | `analyst.md` + shared 合并后的实际文本 |
| 运行配置 | Python 3.13.14；模型 `Qwen3-30B-A3B-Instruct-2507-Q4_K_M`；`OR_MAX_ARTICLES=20`；`OR_LLM_TIMEOUT_SECONDS=300`；`full_text_min_chars=400` | 非秘密项；`.env` 含凭据，不记录内容也不记录哈希 |
| 统计窗口 | published 2026-10-06 至 2026-11-01 | 16 个有文章的日期 |
| 分析记录 | 99 条（v5 61、v4 38） | 含 9 条 v4 无证据状态记录 |

计数口径：

- 文章与已分析：`articles` 全表；`analyses` 全表。
- 证据秩：`analyses.result_json` 的 `scoring.evidence_rank`。
- 证据状态：`scoring.evidence_state`；v4 记录无该字段，秩按 `LEGACY_LEVEL` 口径计为 E0/E1。
- 状态与通道：`scoring.status`、`scoring.lane`。
- 来源归属：优先 `meta.source_id`；为空时按规范化名称，并对 5 处名称差异使用固定别名映射
  （SALOME、SimScale、BEA、Fed、ONS）。
- 层级映射：L0 = NVIDIA Newsroom、BEA、Fed、ONS；L3 = BBC Business/Technology、NYT Business/Technology；
  L5 = HN Ask/Show、OpenAI Community、preCICE、ParaView、SALOME、SimScale。

失效条件：评分规则、schema、提示词、来源登记或运行窗口任一变化，本基线即失效。
重新统计时必须生成新快照（哈希 + 提交 + 日期），不得与旧数字混算。

---

## 6. S0-4 P0 候选来源调查（已冻结；最终评审见 §7）

状态定义（四阶段，逐步推进；前一阶段不自动包含后一阶段）：

- **`access_verified`**：访问方式已经确认（API/RSS/批量/页面），但条款与价值未确认。
- **`terms_verified`**：许可与使用条款已确认，并且**按权利分别记录**：存储、商业使用、再分发、历史数据。
- **`value_verified`**：对项目有实际信息价值，且已按 Coverage / Signal Yield / Evidence Value 评价。
- **`integration_candidate`**：满足进入接入评审的条件（访问、条款、价值均通过）。
- 辅助状态：`access_documented`（官方页面已取到但配额/格式/历史细节不全）、`blocked`（当前环境无法取得）、`pending`（未核验）。

重要：不得用一个"verified"或一个许可标签覆盖全部行为。以下四个权利必须分别核实：

| 权利 | 要回答的问题 |
|---|---|
| 存储 | 是否允许长期保存原文、数据或再发布版本？ |
| 商业使用 | 是否允许用于商业目的或商业产品？ |
| 再分发 | 是否允许在简报、研究或对外产品中再发布？ |
| 历史数据 | 是否允许获取并使用历史序列，还是只能取最新值？ |

### 6.0 指标范围与来源类型（防止只用官方统计）

| 领域 | 需要覆盖的指标 | 来源类型必须区分 |
|---|---|---|
| 汽车 | 生产、销量、出口、库存、投资、产能 | 官方统计（各国统计/交通部门）、行业协会（OICA、ACEA、CAAM、JAMA、SIAM）、企业披露 |
| 机器人 | 安装量、出货量、应用行业、企业订单 | 行业协会（IFR）、官方统计、企业披露 |
| 能源 | 价格、发电结构、供需、库存、产能、项目投资 | 官方统计（EIA、国家能源局、资源能源厅）、国际组织（IEA）、行业与电网数据（Ember、ENTSO-E、JODI） |
| 制造业 | PMI、工业产出、产能利用率、设备投资 | 官方统计（统计局、央行）、行业协会、企业披露 |

行业协会统计可能很有价值，但必须单独核实方法、样本范围与版权；不得与官方统计混为一谈。

### 6.1 统一评价表（每个候选来源都必须回答）

1. 原始信息是什么？
2. 是否真正补充现有覆盖缺口？
3. 是否有 API、RSS、批量下载或页面访问能力？
4. 是否允许自动化访问？
5. 是否允许保存、商业使用和再分发？
6. 历史数据能追溯多久？
7. 配额、成本、更新频率如何？
8. Coverage、Signal Yield、Evidence Value 分别是什么状态？
9. 与现有来源是否重复？
10. 最终建议：保留候选 / 暂缓 / 排除 / 待核验。

规则：

- 没有查到许可，不等于许可允许；没有查到 API，不等于无法合法自动化采集。
- 每个结论必须附官方页面证据与访问日期。
- 免费、热门、技术上容易调用，都不构成接入理由。
- 聚合平台（如 GDELT）如后续纳入，主要承担**事件发现**，不直接算作独立证据。
- 来源角色分为四类，角色决定它在证据链中的位置，不决定可信度：
  一手披露（SEC EDGAR、DART、交易所）、统计与数据（EIA、Ember、各国统计局）、
  政策原文（政府门户）、事件发现（GDELT 等聚合平台）。

### 6.2 主线一：亚洲宏观与政策（中国、日本、韩国、印度）

| 来源 | 原始信息 | 访问方式（初勘） | 状态 |
|---|---|---|---|
| 国家统计局（中国） | 官方统计发布与统计数据库 | 英文门户提供 RSS 与月度/季度/年度数据；未确认 API/批量 | access_documented |
| 中国人民银行 | 货币政策操作、政策公告、统计数据、报告 | 网页与报告下载；未见 RSS/API | access_documented |
| 工业和信息化部（中国） | 产业政策、政策解读、行业数据 | 以文章形式发布；未见 RSS/API | access_documented |
| 日本银行（BOJ） | 统计与时间序列 | 统计 RSS + 时间序列检索；未提 API/批量 | access_documented |
| 印度储备银行（RBI） | 政策、统计、Database on Indian Economy | RSS；数据门户；未提 API | access_documented |
| 韩国 KOSIS | 官方统计 OpenAPI | 需申请认证 key；每分钟限额（数值未给）；条款为韩文：**商用与再分发需事先同意**；data.go.kr 条目声称 KOGL 第 1 类（署名），两者冲突待解 | access_documented + terms_verified（限制性；存在冲突） |
| 日本 e-Stat | 官方统计 API | 需 e-Stat 账号注册；内容条款已核验（商用允许、再分发需署名、兼容 CC BY 4.0）；API 另有条款 | access_documented + terms_verified（内容；API 条款另议） |

### 6.3 主线二：欧美与英国政策监管

| 来源 | 原始信息 | 访问方式（初勘） | 状态 |
|---|---|---|---|
| Federal Register（美国） | 联邦法规与公告 | JSON API 端点可直接返回结果（无需认证）；文档页被重定向到 `unblock.federalregister.gov` | access_verified（仅端点；字段/历史/限额/条款待核） |
| EUR-Lex（欧盟） | 法规、判例、数据复用说明 | 页面返回空内容 | pending |
| GOV.UK Content API（英国） | 政府内容 JSON | 已取到 JSON 内容记录；OGL v3 通用条款已核验 | access_documented（页面是否全部适用 OGL 待核） |
| 中国政府网 | 政策原文与最新政策 | 中文站政策列表由 JS 渲染；英文门户可正常访问（分页，无 RSS/API/批量） | access_documented（英文门户）；中文站 blocked |

### 6.4 主线三：能源

| 来源 | 原始信息 | 访问方式（初勘） | 状态 |
|---|---|---|---|
| EIA（美国） | 电力、油气、煤、排放、能源展望时间序列 | API key；JSON API + ZIP 批量；覆盖与历史因数据集而异 | access_verified + terms_verified + value_verified + `integration_candidate`（限定：单一指标样本，见 §6.9.2） |
| Ember | 电力需求、发电、排放、价格 | OpenAPI v1（需 key）；**免 key 公开 CSV**（全球/欧洲，年度发电）；容量端点自 2016-01 | access_verified + terms_verified（CC BY 4.0）+ value_verified（有限样本） |
| IEA | 报告、数据浏览器、付费数据集 | 无 API；报告等 CC BY 4.0，数据集/数据浏览器等另行授权 | access_verified + terms_verified（无 API；报告 CC BY 4.0，数据集另议） |
| JODI | 石油与天然气月度数据 | 在线数据库与下载；未提 API | access_documented（无 API；条款未声明） |
| ENTSO-E Transparency Platform | 欧洲电力发电、负荷、输电、平衡 | 平台数据；Manual of Procedures 未给 API/认证/条款；平台首页本轮加载失败 | pending |
| 中国国家能源局 / 日本资源能源厅 | 能源政策与统计 | 未核验 | pending |

### 6.5 主线四：汽车与制造业

| 来源 | 原始信息 | 访问方式（初勘） | 状态 |
|---|---|---|---|
| 工业和信息化部（中国） | 汽车、电子、软件、锂电等行业数据 | 文章式发布；未见 API/RSS | access_documented |
| IFR（国际机器人联合会） | 机器人统计摘要、《World Robotics》 | 公开新闻稿与摘要；报告付费/登录；使用条款未读取 | access_documented（数据付费） |
| ACEA（欧洲汽车） | 乘用车与商用车注册、产量 | 每月发布乘用车/商用车新闻稿（夏季除外）；无 API/批量/历史下载；单年区域份额样本（2022） | access_documented；value 未测（无连续序列） |
| JAMA / SIAM / KAMA | 日本、印度、韩国汽车统计 | 未核验 | pending |
| ISM / S&P Global PMI | 制造业 PMI | 未核验；ISM 报告与 S&P Global PMI 可能涉及付费/许可 | pending |
| 中国国家统计局 PMI | 中国制造业 PMI | 统计局发布；数据库/RSS 访问 | access_documented |
| OICA（全球汽车产量） | 全球产量与销量统计 | 年度报告（1999–2026，含部分年份与 2026 Q1）；Definitions PDF 存在但文本不可提取；全量下载链接未暴露；单位与连续性未确认 | access_verified + terms_verified（非商业；商业需许可）；value 未测 |
| 中国汽车工业协会（CAAM） | 中国汽车产销 | 访问时连接重置 | blocked |

### 6.6 主线五：企业经营与披露

| 来源 | 原始信息 | 访问方式（初勘） | 状态 |
|---|---|---|---|
| SEC EDGAR（美国） | 申报历史、XBRL 财务数据 | REST JSON，无需认证；ZIP 批量每晚更新；10 请求/秒，需声明 UA | access_verified + terms_verified + value_verified + `integration_candidate`（**限定范围**，见 §6.9.2） |
| 韩国 DART | 披露原文与结构化财务数据 | Open API；需认证 key；原文 XML | access_documented |
| HKEXnews（香港） | 上市公司公告 | 标题/内容检索；未见 API/RSS/批量；再分发需同意 | access_documented（再分发受限） |
| EDINET（日本） | 有价证券报告等 | API 需注册；本轮取到的是代码表/分类下载门户，API 文档与条款未读 | access_documented（API 注册入口存在） |
| Companies House API（英国） | 公司登记与实时信息 | 开发者指南：600 请求/5 分钟、TLS、key 安全要求；许可证页未找到，OGL 适用性未确认 | access_verified（指南）；licence 待核 |

### 6.7 用语修正

本轮核验的 NBS、PBoC、MIIT 几个入口，**未确认到公开 API**；其中 NBS 英文门户提供 RSS 与统计数据库，
PBoC 与 MIIT 以网页、报告和文章为主。不能据此推断"中国一手来源普遍没有公开 API"。
后续必须继续区分：正式 API、公开数据库查询接口、RSS、网页监测、人工发布。

### 6.8 核验用官方页面（访问日期 2026-11-01）

- SEC EDGAR：https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC 自动化访问说明：https://www.sec.gov/os/webmaster-faq
- EIA：https://www.eia.gov/opendata/
- EIA 版权与复用：https://www.eia.gov/about/copyrights_reuse.php
- EIA 电力数据目录：https://www.eia.gov/electricity/data.php
- EIA Table 1.1（煤炭净发电量样本）：https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_1_01
- IEA：https://www.iea.org/terms
- Ember：https://ember-energy.org/data/
- Ember API：https://ember-energy.org/data/api/（文档 https://api.ember-energy.org/v1/docs；规范 https://api.ember-energy.org/v1/openapi.json）
- Ember 年度 CSV：https://files.ember-energy.org/public-downloads/generation/outputs/release_generation_yearly_global.csv
- Ember 年度数据页：https://ember-energy.org/data/yearly-electricity-data
- DART：https://opendart.fss.or.kr/intro/main.do
- 国家统计局（英文）：https://www.stats.gov.cn/english/
- 中国人民银行：https://www.pbc.gov.cn/
- 工业和信息化部：https://www.miit.gov.cn/
- 日本银行：https://www.boj.or.jp/en/statistics/
- 印度储备银行：https://www.rbi.org.in/
- KOSIS：https://kosis.kr/openapi/index/index.jsp
- KOSIS 条款（韩文）：https://kosis.kr/serviceInfo/useClause.do
- e-Stat API：https://www.e-stat.go.jp/api/
- e-Stat 使用条款：https://www.e-stat.go.jp/terms-of-use
- 中国政府网英文门户：https://english.www.gov.cn/policies/latestreleases
- GOV.UK Content API：https://www.gov.uk/api/content
- ACEA：https://www.acea.auto/statistics/（样本 https://www.acea.auto/figure/passenger-car-registrations/）
- OICA：https://www.oica.net/（统计栏目；生产 https://www.oica.net/production-statistics/；销售 https://www.oica.net/sales-statistics/）
- JODI：https://www.jodidata.org/
- OGL v3：https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/
- HKEXnews 检索：https://www.hkexnews.hk/search/titlesearch.xhtml?lang=en
- ENTSO-E Transparency：https://www.entsoe.eu/data/transparency-platform/
- Companies House API：https://developer.company-information.service.gov.uk/
- Companies House 开发者指南：https://developer.company-information.service.gov.uk/developer-guidelines
- IFR：https://ifr.org/
- HKEXnews：https://www.hkexnews.hk/index.htm
- EDINET：https://disclosure2.edinet-fsa.go.jp/
- Federal Register：https://www.federalregister.gov/developers/documentation/api/v1（文档页重定向）
- Federal Register API 端点：https://www.federalregister.gov/api/v1/documents.json（可直接返回 JSON）
- EDINET 门户：https://disclosure2.edinet-fsa.go.jp/weee0010.aspx（API 注册与代码表下载；非 API 文档）
- EUR-Lex：https://eur-lex.europa.eu/content/help/data-reuse.html（未返回内容）
- CAAM：https://www.caam.org.cn/（连接重置）
- 中国政府网：https://www.gov.cn/zhengce/zuixin/（JS 渲染，2026-10-23 实测）

### 6.9 权利核验矩阵（只列已取到条款的来源）

| 来源 | 存储 | 商业使用 | 再分发/对外展示 | 历史数据 | 依据（官方原文要点） | 未确认 |
|---|---|---|---|---|---|---|
| SEC EDGAR | 允许 | 允许 | 允许（政府内容可自由访问与复用） | 申报历史可按公司获取；批量每晚更新 | SEC webmaster FAQ：政府创建内容与 EDGAR 公开申报"free to access and reuse"；10 请求/秒；须声明 UA | 例外材料（如第三方图片）与商业产品中的具体展示方式 |
| EIA | 允许 | **未明确** | 允许（建议注明来源与日期；照片、标志除外） | 因数据集而异（如 SEDS 自 1960） | EIA 版权页：美国政府作品属公共领域；建议注明"Source: U.S. Energy Information Administration (日期)" | 商业使用未明确；第三方授权材料与照片 |
| Ember | 允许 | 允许（需署名） | 允许（需署名） | 月度序列；起始年份待核 | Ember 数据页："All content is released under a Creative Commons Attribution Licence (CC-BY-4.0)" | 数据集的准确范围与署名格式 |
| IEA | 报告允许；数据集另议 | 报告允许；数据集另议 | 报告允许；数据集另议 | 数据集另议 | IEA terms：多数报告/图表 CC BY 4.0；**数据集、数据浏览器、数据库、WEO 数据附件等不适用 CC** | 付费数据集条款、商业使用与存储条件 |
| OICA | 待核验 | **需 OICA 许可** | **需 OICA 许可** | 季度与年度发布；起始年份待核 | OICA 官网：统计对非商业用途与会员免费，商业用途需联系 OICA | 存储与再分发的具体条件；商业使用许可流程 |
| JODI | 未声明 | 未声明 | 未声明 | 未声明 | 站点仅有版权声明，未见使用条款 | 全部四项 |
| KOSIS | 需事先同意（条款未授予通用复用） | 需事先同意 | 需事先同意 | 未声明 | KOSIS 站点条款（韩文，Art.15/16）；data.go.kr 条目声称 KOGL 第 1 类（署名） | 两处条款冲突；无官方英文条款 |

条款补充：

- **OGL v3**（英国开放政府许可）通用条款已核验：允许复制、发布、分发、改编，允许商业与非商业使用，要求署名；
  排除个人数据、第三方权利、标识与徽章等。GOV.UK 与 Companies House 是否逐页声明适用 OGL 仍待核验，
  不能仅凭"英国政府网站"推定。
- **HKEXnews**：页面声明转载、分发、使用或链接需取得同意，属于受限来源，不能按开放数据对待。
- **JODI**：条款页未找到（404），四项权利仍为未声明。
- **ENTSO-E**：平台首页本轮加载失败，API/条款仍未核验。

使用规则：

- 允许商业使用，不等于允许任意再分发；允许内部存储，不等于可以把原始数据直接展示给用户。
- 表中"再分发/对外展示"必须按具体产品行为（邮件简报、HTML 报告、机会数据库）分别判断。
- 未列入表中的来源，四项权利均视为**待核验**，不得假定允许。

### 6.9.1 `value_verified` 的证据要求

一个来源只有在以下三个问题都有实际样本支撑时，才能标为 `value_verified`：

1. 它实际提供了哪些指标或事件？——必须列出具体字段与样本条目。
2. 这些信息是否已被现有来源覆盖？——对照 `config/sources.local.csv` 与生产库。
3. 它能否提供独立的一手证据，而不只是重复转载？——说明来源角色（一手披露/统计/政策原文/事件发现）。

没有样本时保持"待评估"。Signal Yield 无法测量时写 `NOT_MEASURED`，不得用主观评分补齐。

### 6.9.2 小样本价值核验（只读，非接入）

价值验证不等于正式接入。以下样本仅通过公开接口/页面读取，不写连接器、不改数据库。

| 来源 | 样本 | 提供了什么 | 现有语料是否覆盖 | 独立性 | 结论 |
|---|---|---|---|---|---|
| SEC EDGAR | NVIDIA（CIK 1045810）`us-gaap:Revenues` | 2007–2026 年度与季度收入，字段含期间、值、表单、申报日 | 现有 NVIDIA 语料 4 条均为新闻稿，**无财务序列** | 企业原始申报，一手披露 | `value_verified`；可归为 `integration_candidate`（限定范围，见 §6.11） |
| Federal Register | 最新 3 条 "energy" 检索结果 | NIH 专利许可、FCC 超宽带规则、USDA 租约；字段含标题、类型、机构、日期、摘要 | 现有语料无监管公告 | 政府原始公告，一手 | 样本已看，但关键词噪声明显；价值依机构/主题过滤而定，仍 `not_measured` |
| 中国政府网英文门户 | 2026-07-24 至 2026-10-26 的 15 条政策发布 | AI 就业、电力事故应急、集成电路布图保护等主题 | 现有语料无中国政策 | 政府原文，一手 | 标题级样本显示新增信息；正文条款、中英文同步、重复发布未验证，仍 `not_measured` |
| EIA | Table 1.1 煤炭净发电量（2026-10-23 发布） | 美国全国；千兆瓦时；月度+年度；2024 年 652,156、2025 年 734,928、2026-08 70,937；2025 及以前为终值、2026 为初值 | 现有语料无能源序列 | 官方统计 | `value_verified`；可归为 `integration_candidate`（限定单一指标） |
| Ember API | OpenAPI v1.2.3 | 端点：碳强度/需求/排放/发电（年/月）、风光装机（月）；单位 TWh、%、MtCO₂、GW、gCO₂/kWh；年度自 2000、月度 2000-01、装机 2016-01；需 api_key | 无 | 开放数据，CC BY 4.0 | 字段与覆盖已核，**未取数值**，仍 `not_measured` |
| Ember 公开 CSV | 全球年度发电 CSV（16.1 MB，104,241 行） | 年份 1985–2025；209 个国家/经济体；字段 Area/ISO/Year/Area type/source/Generation TWh/share %/capacity GW/emissions/flags；美国煤炭 2024=652.16 TWh、2025=737.15 TWh；美国序列 2000–2025 | 现有语料无能源序列 | 二次汇编（方法论 PDF，非一手） | `value_verified`（样本已取；二次汇编，待读方法论） |
| ACEA | 乘用车注册区域份额图 | 全球份额：亚洲 51.6%、美洲 23.7%、欧洲 19.5%；单位 %；2022 年；2023-05-18 发布 | 无 | 协会统计 | 单年截面样本，无连续序列，仍 `not_measured` |
| OICA | 生产/销售统计页 | 年度报告（1999–2026，部分年份）、2026 Q1、下载全量；单位未标注；部分欧洲国家缺失 | 无 | 协会统计 | 连续性/单位未确认，仍 `not_measured` |
| EIA / Ember / e-Stat / KOSIS | 未取样 | — | — | — | `not_measured`（EIA 需 key；e-Stat/KOSIS 需注册；Ember 未取样） |

EIA 样本的口径补充：2016–2025 的 Annual Totals 是完整 12 个月合计；2026 只有 1–8 月的 Year to Date，
没有 2026 年度值；月度与年度使用相同来源列与单位（千兆瓦时），年度为聚合值；2026 年数据为初值，
2025 及以前为终值；页面未定义 "net" 的具体扣减公式；已查 EIA 术语表：net generation = "gross generation less the electrical energy consumed at the generating station(s)"，
抽水蓄能抽水计入厂用电并从毛发电中扣除（来源：EIA Glossary, N 页）。入库计算需按此定义处理。

SEC EDGAR 的 `integration_candidate` 是**限定范围**的：

- 已验证：NVIDIA 历史收入序列（年度/季度）相对现有新闻语料的增量。
- 尚未验证：其他公司的覆盖率、不同财务指标的完整性、长期更新稳定性。
- 接入前必须处理：XBRL 标签差异、单位、报告期间、季度累计值（YTD）、修订申报；
  **不能把 API 返回的所有记录直接拼成时间序列**。

统计类样本的比较口径（后续 EIA、Ember、OICA、ACEA、KOSIS、e-Stat 必须逐项记录）：

1. 指标名称及原始定义。
2. 地区、统计对象、单位。
3. 时间范围与频率。
4. 原始发布日期与修订情况。
5. 与现有数据是否可比较；不可比较时说明原因。

车产销、能源消费/发电量、机器人安装量等指标，不能因名称相似就当作可互相验证。

本轮已出现的具体不可比例子：

- EIA 是美国**全国煤炭净发电量**（千兆瓦时，月度/年度）；Ember 是**按国家/地区的发电结构**（TWh，年度/月度）。
  两者统计对象、地理范围与单位不同，只能互补，不能互相验证。
- ACEA 是**区域份额**（%），OICA 是**全球产量/销量**（单位未标注），不能直接拼成一条全球汽车市场序列。
- Ember 与 EIA 的美国煤炭发电量在 2024 年几乎相同（652.16 vs 652.156 TWh），2025 年相差约 0.3%（737.15 vs 734.928 TWh）。
  可以互相核对，但数值不完全一致，说明来源、修订与方法不同；不能把 Ember 当作 EIA 的替代，也不能把两者差值当作误差。
- **数值吻合不等于来源独立**：Ember 是二次汇编，如果其美国数据直接或间接采用 EIA，则两者一致只说明转录/转换一致，
  不构成两份独立证据。Ember 的方法论必须确认数据来源、转换方法、修订机制与各国来源是否一致。
  在此之前，Ember 的定位是**全球横向比较候选**，不是 EIA 的独立验证来源。

样本核验的边界：

- 单公司、单关键词、单页面的样本只能证明"存在这类信息"，不能证明长期产出与信噪比。
- 不得仅因样本"看起来有用"就转为 `integration_candidate`；SEC 的归类基于访问、条款与样本三项证据，且只覆盖已验证的范围。

同一机构可以有不同的信息入口与访问方式：中文门户的 JS 渲染问题不能推导出英文门户不可用
（本轮英文门户可正常访问）。反过来，英文门户可用也不代表中文原文、完整条款或全部发布都能取得。

### 6.9.3 独立性提醒

- 三家媒体转载同一份协会公告，只算**一份证据**，不因文章数量增加而变成三份独立来源。
- 官方统计、企业披露与行业协会统计即使数字不同，也可能因统计口径、样本范围与修订政策不同而**不能直接互相验证**。
- 横向覆盖矩阵中的"独立性"列必须按来源谱系判断，不能按来源名称数量判断。

### 6.9.4 四个不同层次不能互相替代

| 层次 | 解决的问题 | 不能推出 |
|---|---|---|
| robots.txt | 自动化爬虫可以访问哪些路径 | 不能推出获得数据使用授权 |
| API 使用规则 | 频率、认证、User-Agent | 不能推出可以保存或再发布 |
| 使用条款 | 数据如何存储、使用、处理 | 不能推出可以商业使用或对外展示 |
| 版权与许可 | 商业使用、再分发、对外展示 | 不能推出可以无视访问规则 |

遵守 robots 不等于取得授权；有开放许可也不等于可以无视网站的访问规则。

### 6.10 `blocked` 来源的处理顺序

不要因为页面抓不到就直接上浏览器自动化。按顺序确认：

1. 是否存在官方 RSS 或数据接口？
2. 是否存在官方数据下载文件（CSV/Excel/ZIP/XML）？
3. 是否存在其他官方公开查询入口（英文站、镜像、批量包、开放数据门户）？
4. 是否存在官方授权的数据服务？
5. 以上都不存在，且条款允许时，才考虑 Playwright 等浏览器自动化。

不得为了抓到页面而绕过访问限制。

如果替代入口已调查到合理程度仍不可用，记录限制、替代方案与日期，转入其他来源；
P0 不因单个站点阻塞整体进度。CAAM 与 EUR-Lex 目前按此处理，保留 blocked 状态与已知替代线索。

当前 blocked 项的性质并不相同：

- 中国政府网：静态页面只有页脚链接，政策列表由 JS 渲染——先找官方 RSS/数据接口或发布文件。
- Federal Register：文档页被导向反爬页；但直接调用 `https://www.federalregister.gov/api/v1/documents.json` 返回了正常 JSON，
  说明"文档页不可读"不等于"API 不可用"。已改为 `access_verified`，条款仍待核验。
- CAAM：连接重置——先确认是否可从官方镜像/协会公开报告获取。
- EDINET：页面无可读内容；本轮找到 API 注册入口与代码表/分类下载门户，API 文档与条款仍未读取。
- EUR-Lex：页面空响应——先确认是否有 SPARQL/批量/开放数据入口。

### 6.11 P0 结束条件与归类

P0 的目标不是查完全部候选，而是判断关键情报缺口能否被合理填补。结束时每个来源必须归入以下四类之一：

| 结论 | 含义 | 需要的证据 |
|---|---|---|
| `integration_candidate` | 访问、权利、价值均有证据支持，进入后续接入评审 | access_verified + terms_verified（四项权利）+ value_verified |
| `deferred` | 有价值，但权利、成本或技术条件尚不成熟 | 说明具体阻碍与可解除条件 |
| `rejected` | 信息增量不足，或权利条件不满足项目需求 | 说明缺失的增量或无法满足的权利 |
| `not_measured` | 现有证据不足，暂时无法判断 | 说明缺哪类证据、如何补 |

当前归类（P0 冻结）：SEC EDGAR 与 EIA = `integration_candidate`（各自限定范围）；
Ember = `value_verified`（有限样本）；其余候选为 `not_measured` 或 `deferred`。
KOSIS 与 Companies House 的条款已部分核验，但 KOSIS 条款与 data.go.kr 声明冲突、Companies House 许可未确认，
均不满足接入条件。完整决策表见 §7.1。

P0 完成的判定：

1. 五条主线的候选来源都已完成访问与条款核验，或明确标为 blocked 并说明替代入口调查结果。
2. §6.12 的横向覆盖矩阵填写完成。
3. 每个 `integration_candidate` / `deferred` / `rejected` 都有书面理由。

### 6.12 P0 完成时的横向覆盖矩阵（模板，待填）

| 研究维度 | 当前来源 | 候选新增来源 | 新增信息 | 独立性 | 证据能力 |
|---|---|---|---|---|---|
| 亚洲宏观与政策 | 无 | NBS、PBoC、MIIT、BOJ、RBI、KOSIS、e-Stat、中国政府网英文门户 | 英文门户 15 条标题样本；正文未取；KOSIS 条款限制商用/再分发 | 政府原文/官方统计（待谱系核验） | 政策原文与统计（KOSIS 权利受限） |
| 欧美政策监管 | Fed（美国货币） | GOV.UK、Federal Register、EUR-Lex | Federal Register 3 条样本（NIH/FCC/USDA，关键词噪声）；GOV.UK API 可访问；EUR-Lex 未取 | 政府原文 | 法规/政策原文；需机构与主题过滤 |
| 汽车与制造 | 无有效产业来源 | ACEA、OICA、CAAM、JAMA、SIAM、KAMA、各国统计 | ACEA：2022 区域份额样本；OICA：年度报告入口；无连续序列 | 协会统计（口径需核） | 截面/年度；连续性未确认 |
| 机器人 | 无 | IFR、企业披露 | IFR 公开摘要；World Robotics 付费；未取样 | 协会统计（付费） | 安装量/出货量，样本未取 |
| 能源 | 无（仅新闻） | EIA、Ember、IEA、JODI、ENTSO-E、NEA、Enecho | EIA：美国煤炭净发电量样本；Ember：1985–2025、209 国、美国煤炭 2024/2025 样本 | 官方统计（EIA）/二次汇编（Ember） | 时间序列；两者可交叉核对但数值不完全一致 |
| 企业经营 | NVIDIA Newsroom | SEC、DART、HKEXnews、EDINET、Companies House | SEC：NVIDIA 财务序列样本；DART/HKEX/EDINET/Companies House 未取样 | SEC：一手披露；其余待核 | SEC：XBRL 结构化；其余待核 |

用途：识别哪些候选来源提供了现有体系真正缺少的信息，而不是选出最多的来源。P0 结束时填写完整。

### 6.12.1 过程归类（最终决策见 §7.1）

| 来源 | 初步归类 | 理由 |
|---|---|---|
| SEC EDGAR | `integration_candidate` | 访问、条款、样本价值三项齐备；范围限 NVIDIA 收入序列 |
| EIA | `integration_candidate` | 访问、条款、样本价值三项齐备；范围限煤炭净发电量 |
| Ember | `value_verified`（有限样本） | 访问、条款、公开 CSV 与 2024/2025 数值样本已核；二次汇编，待读方法论；定位为全球横向比较，不作为 EIA 的独立验证；未定 integration |
| OICA | `not_measured` | 单位与连续性未确认 |
| ACEA | `not_measured` | 只有单年截面，无连续序列 |
| KOSIS | `not_measured`（权利风险） | 韩文条款限制商用/再分发，与 data.go.kr 的 KOGL 声明冲突 |
| Companies House | `not_measured` | API 规则已核；许可证未确认 |
| 中国政府网英文门户 | `not_measured` | 仅标题级样本，正文未取 |
| CAAM、EUR-Lex | `deferred`（blocked） | 访问未解决；替代入口已记录 |
| IEA | `deferred` | 无 API；多数数据集付费/另行授权 |
| IFR | `deferred` | 报告付费/登录 |
| JODI | `not_measured` | 条款未声明 |
| ENTSO-E | `not_measured` | API/条款未核验 |
| 其余未列来源 | `not_measured` | 证据不足 |

这张表是 P0 当前证据的汇总，不是最终接入决定；统一评审时逐项确认理由与后续动作。

### 6.13 本轮不做什么

- 不判断是否接入，不形成首批名单。
- 不因为某个来源免费、热门或容易调用就推荐它。
- 不把"有 API"当成"有情报价值"；Signal Yield 与 Evidence Value 仍按 §5 的口径标注。
- 不修改任何来源登记或配置。

---

## 7. P0 最终评审（2026-11-01 冻结）

来源调查到此冻结，不再扩展候选清单。以下三份结论用于后续接入设计评审。

### 7.1 来源决策表

| 来源 | 最终归类 | 证据 | 未解决事项 |
|---|---|---|---|
| SEC EDGAR | `integration_candidate`（限定） | 访问（JSON API/批量）、条款（10 req/s、UA、政府内容可复用）、价值（NVIDIA 2007–2026 收入序列） | 其他公司与指标覆盖、长期稳定性、XBRL 标签/期间/YTD/修订处理 |
| EIA | `integration_candidate`（限定） | 访问、条款（公共领域/署名）、价值（美国煤炭净发电量样本；net 定义已查） | 其他数据集、州级/价格序列、长期稳定性 |
| Ember | `value_verified` | 公开 CSV：1985–2025、209 国；美国煤炭 2024=652.16 TWh、2025=737.15 TWh；CC BY 4.0 | 方法论、二次汇编的独立性、是否进入接入设计 |
| 中国政府网英文门户 | `not_measured` | 15 条政策标题样本 | 正文条款、中英文同步、重复发布 |
| 国家统计局 / PBoC / MIIT | `not_measured` | 访问方式已文档化（NBS 有 RSS/数据库；PBoC/MIIT 网页与文章） | 条款、样本、存储与再分发 |
| BOJ / RBI | `not_measured` | RSS/时间序列检索、数据门户已确认 | API/批量、条款、样本 |
| KOSIS | `not_measured`（权利风险） | 韩文条款：商用/再分发需同意；data.go.kr 声称 KOGL 1 类 | 两处条款冲突；无官方英文条款 |
| e-Stat | `not_measured` | API 需账号；内容条款允许商用、再分发需署名、兼容 CC BY 4.0 | API 条款、样本 |
| Federal Register | `not_measured` | API 端到端可用；3 条样本（NIH/FCC/USDA，噪声） | 字段/历史/限额/条款；主题过滤 |
| GOV.UK | `not_measured` | Content API 可访问；OGL v3 通用条款已核 | 页面级 OGL 适用性、样本 |
| EUR-Lex | `deferred`（blocked） | 无可用读取入口 | 访问；替代入口 |
| OICA | `not_measured` | 年度报告 1999–2026（部分年份）；Definitions PDF 存在但文本不可提取 | 单位、连续性、口径 |
| ACEA | `not_measured` | 月度新闻稿；单年区域份额样本 | 连续序列、下载、条款 |
| CAAM | `deferred`（blocked） | 连接重置 | 访问；替代入口 |
| IFR | `deferred` | 公开摘要；World Robotics 付费/登录 | 价值、许可 |
| IEA | `deferred` | 报告 CC BY 4.0；数据集/数据浏览器另行授权；无 API | 数据集条款与成本 |
| JODI | `not_measured` | 下载与在线数据库；无 API | 许可与条款 |
| ENTSO-E | `not_measured` | 平台存在；MoP 未给 API/条款 | API、认证、条款 |
| DART | `not_measured` | Open API + key；XML | 条款、样本 |
| HKEXnews | `not_measured` | 检索页；再分发需同意 | API/批量、许可 |
| EDINET | `not_measured` | API 注册入口；代码表/分类下载 | API 文档、条款 |
| Companies House | `not_measured` | 开发者指南：600 req/5min、TLS、key 安全 | 商业复用许可（OGL 未确认） |
| SSE/SZSE | `not_measured` | 未核验 | 是否公开披露接口 |

`rejected`：暂无。不是因为没有不合格来源，而是现有证据不足以排除任何来源。

### 7.2 信息覆盖矩阵（六维度）

| 维度 | 已补上的信息（来源） | 仍缺 | 证据强度 |
|---|---|---|---|
| 亚洲宏观与政策 | 中国英文门户 15 条政策标题；KOSIS/e-Stat/BOJ/RBI 访问方式 | 正文/序列样本；中国官方数据条款；KOSIS 许可冲突 | 弱 |
| 欧美政策监管 | Federal Register 3 条 API 样本；GOV.UK Content API 可访问 | EUR-Lex；字段/历史/限额/条款；主题过滤 | 弱 |
| 汽车与制造 | ACEA 2022 区域份额；OICA 年度报告入口与 Definitions PDF | 连续月度/季度产销量、单位、口径一致性 | 弱 |
| 机器人 | IFR 公开摘要与付费报告边界 | 安装量/出货量样本与许可 | 无 |
| 能源 | EIA 美国煤炭净发电量数值样本；Ember 1985–2025、209 国年度发电样本 | IEA 数据集、中国/日本能源、ENTSO-E；Ember 方法论 | 中 |
| 企业经营 | SEC NVIDIA 财务序列样本 | 其他公司、亚洲披露、Companies House 许可、DART/HKEX/EDINET 条款 | 中 |

结论：P0 没有把六个维度都补齐；它证明了能源与企业经营可以补，亚洲政策与汽车制造仍缺决定性样本。

### 7.3 下一阶段建议

**进入接入设计（只做设计，不实施）**

1. **SEC EDGAR**：从美国大型上市公司财务报表开始，先解决 XBRL 标签映射、期间/YTD、修订申报与单位。
2. **EIA**：从电力时间序列开始，按已核验的 net generation 定义入库，保留发布日、修订状态与数据集版本。

**备选（需先解决条件）**

- **Ember**：先读方法论 PDF，确认数据来源、转换与修订机制；即使数值与 EIA 接近，也不能据此认定独立。若作为跨国对照而非一手证据，可进入设计备选。
- **Federal Register / GOV.UK**：只做政策发现通道，需先设计机构/主题过滤与条款确认。
- **中国政府网英文门户 / NBS**：先取正文样本与存储/再分发条款，否则保持观察。

**暂缓**

- IEA 数据集（付费/另行授权）、IFR（付费）、CAAM 与 EUR-Lex（访问未解决）。

**保持观察**

- OICA、ACEA（连续性与单位）、KOSIS（许可冲突）、Companies House（许可）、JODI、ENTSO-E、
  DART、HKEXnews、EDINET、e-Stat、SSE/SZSE。

**共同前置**：任何来源进入接入设计前，必须完成四项权利核验、样本口径记录与维护成本评估；
423 项测试只能证明现有代码未变，不能作为来源方案的质量证明。

### 7.4 P0 结论与边界

- P0 找到了两个有实际信息增量的候选（SEC EDGAR、EIA），并保留了 Ember 的有限价值样本；
- 没有把"入口可访问"或"有公开 CSV"误判为接入资格；
- 没有 `rejected` 来源，因为尚无足够证据否定任何来源；
- 未写连接器、未改数据库、未启动 R0；
- 下一步是接入设计评审，不是实施。


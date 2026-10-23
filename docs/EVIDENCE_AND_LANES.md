# 证据状态与三条编辑通道

本文说明 `evidence.py`、`lanes.py`、`scoring.py` 与 `config/scoring.toml` 共同实现的规则：
一份日报凭什么把某条内容放进简报，以及凭什么把它标成"事实"。

## 1. 为什么改

改动前的实际行为（可从 `reports/archive/2026/10/*.items.json` 复现）：五天日报里
`priority` 条目恒为 0，证据等级只出现 E0 和 E1。原因不是来源太少，也不是阈值太高，
而是**代码里没有任何路径能产出 E2**：

- `freshrss_client.py` 只保存 RSS 的 `html` / `description`，`content_source` 永远是
  `rss_summary` 或 `title_only`；
- `evidence_level()` 只把引文与标题、摘要比对，因此最高只能返回 `summary`（E1）；
- `score_article()` 把 E1 封顶在 `priority - 1`。

也就是说，把阈值从 75/55 调成任何数字、换更大的模型、增加订阅源，都不会让"优先验证"
出现。这是一个结构性缺陷，优先级高于来源扩容。

第二个问题是报告把**所有**引文都写在"事实"标签下，包括定位失败的引文。数据层已经
知道某条引文在原文里找不到（`field='unlocated'`），但渲染层忽略了这个信息，于是同一张
卡片可以同时写着"E0 · 无法定位"和一段看似原文的事实陈述。

## 2. 证据状态

`evidence.py` 用两个维度描述证据，二者都只依赖程序可核对的信息。

### 2.1 内容基础（`content_basis`）

我们**可以依赖**的原文有多少：

| 值 | 条件 |
|---|---|
| `title_only` | 没有正文文本；或来源声明为 `title_only` |
| `excerpt` | 有正文，但来源未声明为 `full_text`；或来源声明为 `excerpt` |
| `full_text` | **仅当**来源在登记表中被人工复核并声明为 `content_access_level=full_text` |

另有一个纯提示字段 `content_basis_estimate`：程序按长度（≥ 400）和截断标记
（"Read more"、省略号）猜测的内容完整度。**它只用于提示复核，不参与评分，也不授予 E2。**

为什么把两者分开：400 字可能是完整短文，也可能是长文的前半段；没有截断标记不等于没有
截断。启发式猜测不能替代来源级复核，否则"看起来像全文"会被当成"确实拿到了全文"。

报告会在卡片上显示一行提示：文本看起来是全文、但来源尚未声明时，说明只有把该来源复核为
`content_access_level=full_text` 才能按 E2 计。

### 2.2 证据状态（`evidence_state`）

| 状态 | 等级 | 含义 |
|---|---|---|
| `none` | E0 | 没有任何引文 |
| `title_only` | E0 | 引文只出现在标题 |
| `unlocated_quotes` | E0 | 至少一条引文在提供的文本中找不到 |
| `rss_excerpt_only` | E1 | 摘要中的引文已定位 |
| `full_text_verified` | E2 | 正文中的引文已定位 |
| `primary_source_located` | E2 | 同上，且来源为一手方（`first_party` / `project_record`） |
| `multi_source_coverage` | E2 | 同一事件有 ≥2 个不同来源的已分析条目 |

**每个 E2 状态各自证明什么、不证明什么**（报告附录会原样输出这段口径）：

- `full_text_verified`：引文可在收到的正文中定位；不代表正文里的每个事实都已被独立证实。
- `primary_source_located`：引文可在该一手来源自己的发布中定位；这只确认对方这样说过，
  不代表该说法成立。财报、正式公告、营销材料和技术白皮书的证据用途不同，本字段只回答
  "这段文字是否出自该来源本身"。
- `multi_source_coverage`：同一事件有多个来源的已分析条目；**尚未**核对这些来源是否独立、
  是否转载同一稿源。两家媒体转载同一篇通讯社稿件、厂商新闻稿加一篇复述博客，都会产生这个
  状态。它不等于交叉验证。

厂商自述（`vendor_marketing`）永远不算 `primary_source_located`。

需要主张级交叉验证时，必须先有"具体主张 → 支持它的独立来源"的映射；这需要
`claim_text` / `claim_source_url` 与来源独立性判断，见第 6 节。

不可定位的引文会单独渲染成"未核实引文（原文中未找到，不作为事实）"，并在附录中计入
"无法在原文中定位"。卡片上的"事实（可在原文定位）"只包含通过定位校验的引文。

## 3. 三条通道

| 通道 | 回答的问题 | 组件（各 0–5 分） | 晋升门槛 |
|---|---|---|---|
| A 商业、科技与经济情报 | 今天发生了什么重要变化，为什么值得关注 | 重要性、来源可靠性、证据完整度、新颖性、相关性、时效性 | E1 |
| B 客户痛点与商业机会 | 谁遇到了什么问题，有没有人愿意付费 | 痛点严重度、买方明确度、买方付费证据、独立佐证、验证可行性、现有方案缺口、新颖性 | E2 |
| C 技术观察与工程信号 | 哪些技术变化值得跟踪，但还不足以得出商业结论 | 技术成熟度、可复现性、影响范围、来源可靠性、新颖性 | E2 |

### 3.1 准入矩阵

| 通道 | E0 | E1（摘要引文已定位） | E2（正文引文已定位） |
|---|---|---|---|
| A 商业情报 | 过滤 `insufficient_evidence` | 可观察，分数够则可晋升 | 可观察，分数够则可晋升 |
| B 商业机会 | 过滤 `insufficient_evidence` | 只能观察，不得晋升 | 可晋升，由评分与其他门槛决定 |
| C 技术观察 | 过滤 `insufficient_evidence` | 只能观察，不得晋升 | 可晋升，由评分与其他门槛决定 |

证据等级是**必要**条件，不是充分条件：E2 的低分、重复事件、无关内容仍会被过滤
（`low_score`、`no_business_signal`、`source_cap`）。

### 3.2 路由的两种情况

容易混淆，明确区分：

- **来源登记缺少 `editorial_lanes`**：这是配置缺陷，审计报错，来源不允许启用。
- **来源已允许进入某条通道，但文章内容没匹配到更细的分类**：这是运行时默认，按该通道的
  默认规则处理。未声明通道的社区来源若只产出普通帖子，默认进 B。

### 3.3 买方付费与卖方变现分开

`classifier.py` 现在分别记录：

- `buyer_payment_evidence`：`explicit_budget` / `stated_willingness` / `existing_purchase` / `none`
- `seller_monetization_signal`：`commercial_service` / `pricing_published` / `none`
- `adoption_signal`：`production_use` / `none`
- `pain_evidence`：`repeated` / `single_report` / `none`
- `market_validation`：`multi_source` / `buyer_confirmed` / `single_source` / `seller_claim` / `none`

只有 `buyer_payment_evidence` 参与 B 通道的付费分。公开定价页、企业版、商业支持属于卖方
信号，会出现在报告里，但不会让一条内容被读成"有人愿意付费"。

## 4. 来源登记治理

新增字段见 `config/sources.csv` 表头与 `docs/SOURCE_POLICY.md`。审计工具会拒绝未知通道、
非法 `content_access_level` 和越界 `source_cap`，并要求启用来源至少声明一条
`editorial_lanes`。

### 4.1 判断与分发是两个层次

`status`（`priority` / `watch` / `filtered`）回答"这条信息本身是否值得关注"，由证据等级、
通道准入和评分决定。`distribution`（`included` / `deferred`）回答"它是否进入本期阅读区"，
由来源配额和报告容量决定。**配额不得改写 `status`**：一条 94 分的供应链公告被配额延后，
它仍然是 priority，只是本次没有进入阅读区。否则报告会把"没排进这一期"误说成"不值得关注"。

被延后的条目保留原等级、分数、证据与来源，集中列在附录"本期未纳入分发（来源单期配额）"，
执行摘要与简报说明也会写明数量，并注明不代表价值较低。

`source_cap` 在**评分与排序之后**执行：`apply_source_caps()` 先按 `priority` 优先、再按
分数降序排列，然后才计算各来源已入选数量。后到的高分公告不会被先到的低分文章挤掉。配额在
priority 与 watch 两个区间合并计算，因为配额的存在目的是保证来源多样性，而不是奖励产量。

来源未解析的条目不会被套用任何来源配额，其数量计入统计并在附录显示。

2026-10-23 新增 13 个候选来源（NVIDIA / Microsoft / AMD / Google Research / AWS / IMF /
OECD / World Bank / SIA / MIT Technology Review / IEEE Spectrum），全部 `review_required`、
`enabled=false`。其中 AMD、IMF、OECD、World Bank 四行的 `feed_url` 指向新闻页或出版页而非
已确认的 RSS 端点，`review_notes` 已逐条注明；启用前必须实测替换。

## 5. 建议的来源复核顺序

1. 对现有 18 个来源抽样，比较 Feed 内容与原始文章页面，记录是否提供全文、是否经常截断。
2. 审查 13 个新候选：真实 Feed 地址、访问方式、实际内容、权限、通道归属。官网有 RSS 图标
   不等于端点可用。
3. 优先复核 A 通道的官方与产业来源：它们在 E1 条件下就能进入情报简报，可以较快改善商业与
   产业覆盖，且不需要降低 B/C 的标准。
4. 最后再复核 B/C 的全文供给。只有确实供出全文且已完成来源级复核的 Feed 才声明
   `full_text`；其余来源继续贡献 E1 观察线索。

**不建议通过调低 `full_text_min_chars` 来制造 E2**：那改变的是条目数量，不是内容完整性。

## 6. 还没做的

按优先级排列，均为后续工作，不在本次改动范围内：

1. **正文抓取**。当前 E2 只能来自"Feed 本身带全文 + 来源已复核"。为正文单独抓取需要新的
   来源级授权（`content_access_level` 与条款），属于政策决定，不能默认开启。
2. **`claim_text` / `claim_type` / `claim_source_url`**。目前逐条记录引文与定位，但还没有把
   "需要核验的具体事实"与"事实 / 观点 / 推断 / 预测"拆成模型输出字段。这需要提升
   `prompts/analyst.md` 版本并同步 schema。
3. **来源独立性与主张级交叉验证**。`event_sources()` 现在只能回答"同一事件有几个来源"，
   不能回答"这些来源是否独立、是否支持同一项具体主张"。要实现 `cross_source_confirmed`
   需要先有第 2 项。
4. **事件聚类与跨日增量**。已有 `event_key`、`event_seen()` 与 `event_sources()`，但还没有
   "首次出现 / 最近更新 / 本期增量"的持久化视图。
5. **人工标注基准集与质量指标**。README 里的 `review` 命令可以记录人工标签，但还没有
   100–200 条标注样本和 Top-5 有用率、引文支持率、重复推送率等指标的口径文件。

在完成第 1 项之前，"优先验证"只会出现在来源已声明 `full_text` 的 B/C 条目上，以及 A 通道
的 E1 条目上。这是当前证据标准下的诚实结果，不应通过放宽门槛来制造。

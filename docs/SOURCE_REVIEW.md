# 来源体系审查（2026-10-23）

> 这是审查记录，不是批准。表中 `review_status=review_required` 的来源一律保持禁用。

## 审查方法与边界

- **实测时间**：2026-10-23。
- **实测方式**：对 `config/sources.csv` 每一行的 `feed_url` 发起一次 GET（User-Agent 标明用途），判断 HTTP 状态、内容类型、能否解析为 RSS/Atom，并统计样本条目的正文长度与最新日期。仅读取响应头与最多 300KB，不保存文章内容。
- **未做**：未登录、未绕过任何访问控制、未抓取文章正文页、**未核对任何来源的服务条款**。
- 因此 `feed_status=verified_feed` 只表示"该 URL 当前返回可解析的 RSS/Atom"，**不表示**获得许可，也不表示内容准确或更新稳定。
- **影子运行未执行**：本机没有可用的 FreshRSS、本地模型与 SMTP 运行环境，第 7 节只给出方案，不给数字。

## 1. 仓库实际状态

| 项 | 实测值 |
|---|---|
| 登记行数 | 模板 31，本地 31 |
| 启用数 | 模板 0，本地 7 |
| 本地已填 feed id 但禁用 | 7（openai-news、deepmind-blog、huggingface-blog、techcrunch-ai、simon-willison、github-blog、simscale-blog） |
| 两表字段差异 | 56 处，全部集中在 `freshrss_feed_id`、`last_verified_at`、`permission_status`、`reviewed_at`、`enabled`、`review_notes` |
| 编辑治理字段差异 | 无（两表 lanes/access/authority/cap/fallback 一致） |
| 归一化名称碰撞 | 0 |
| 重复 feed_url | 0 |
| 重复 canonical_domain | 3 处（hn 三行共用 news.ycombinator.com，arxiv 两行共用 arxiv.org），属同一提供方下的不同订阅，不是重复订阅 |

任务书第 5 节列出的 16 个来源中，**"FreshRSS releases" 不在本仓库登记表内**；仓库原始来源是 18 个，另加 2026-10-23 新增的 13 个候选，共 31 行。

### 元数据在代码中的实际作用点

| 字段 | 生效位置 | 说明 |
|---|---|---|
| `enabled`/`permission_status`/`access_method`/`feed_url`/`freshrss_feed_id` | `source_policy.is_approved()` | 五者同时满足才会被采集 |
| `editorial_lanes`、`source_type` | `lanes.derive_lane()` | 收窄通道 |
| `content_access_level` | `evidence.content_basis()` | 决定能否进入 E2 |
| `source_cap` | `cli.apply_source_caps()` | 决定本期分发（不改 `status`） |
| `provenance_class` | `classifier._source_quality()` | 决定 `primary_source_located` 是否可能 |
| `topic_tags`、`source_authority` | 仅登记与审计 | 不参与评分 |

### 审计规则与默认值

`source_audit.py` 对**启用**来源要求：approved、HTTPS、允许的访问方式、feed id、canonical_domain、有效期内的 `reviewed_at`/`last_verified_at`、合法 `provenance_class`、至少一条 `editorial_lanes`。对所有行校验 `content_access_level`、`source_cap` 取值。

缺失字段处理：`content_access_level` 缺省 `auto`；`source_cap` 缺省 0（不限额）；`editorial_lanes` 为空时**仅禁用行可以通过**，启用行报 `missing_editorial_lanes`。

可用诊断：`python -m opportunity_radar.source_audit [--check-urls]`（只查启用来源）、报告附录的"来源审计"与"旧记录来源匹配"行。

## 2. 逐来源审计表

列说明：`feed_status` 为实测结论；`n` 为样本条目数（单次拉取）；`body_med` 为条目正文长度中位数（字符）；`latest` 为最新条目日期；`access` 是登记表中的 `content_access_level`（当前全部为 `auto`）。

| id | feed | home | type | lanes | access | auth | cap | en | fs | http | n | med | latest | status | action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| openai-news | https://openai.com/news/rss.xml | https://openai.com/news/ | official_blog | A | auto | official_primary | 3 | no | verified_feed | 200 | 1315 | 146 | Thu, 22 Oct 2026 | review_required | keep |
| deepmind-blog | https://deepmind.google/blog/feed/basic/ | https://deepmind.google/blog/ | official_blog | A,C | auto | official_primary | 2 | no | verified_feed | 200 | 100 | 0 | Thu, 22 Oct 2026 | review_required | reconfigure |
| huggingface-blog | https://huggingface.co/blog/feed.xml | https://huggingface.co/blog | official_blog | A,C | auto | official_primary | 2 | no | verified_feed | 200 | 889 | 0 | Thu, 22 Oct 2026 | review_required | reconfigure |
| google-ai-blog | https://blog.google/technology/ai/rss/ | https://blog.google/technology/ai/ | official_blog | A | auto | official_primary | 2 | no | verified_feed | 200 | 20 | 117 | Wed, 21 Oct 2026 | review_required | keep |
| arxiv-cs-ai | https://rss.arxiv.org/rss/cs.AI | https://arxiv.org/list/cs.AI/recent | research_feed | C | excerpt | primary_research | 2 | no | verified_feed | 200 | 370 | 1523 | Thu, 22 Oct 2026 | review_required | keep |
| arxiv-cs-lg | https://rss.arxiv.org/rss/cs.LG | https://arxiv.org/list/cs.LG/recent | research_feed | C | excerpt | primary_research | 2 | no | verified_feed | 200 | 379 | 1660 | Thu, 22 Oct 2026 | review_required | keep |
| techcrunch-ai | https://techcrunch.com/category/artificial-intelligence/feed/ | https://techcrunch.com/category/artificial-intelligence/ | news_media | A | excerpt | professional_media | 2 | no | verified_feed | 200 | 20 | 147 | Fri, 23 Oct 2026 | review_required | keep |
| simon-willison | https://simonwillison.net/atom/everything/ | https://simonwillison.net/ | independent_expert | A,C | auto | independent_expert | 2 | no | verified_feed | 200 | 30 | 1932 | 2026-10-22T19:42 | review_required | keep |
| github-blog | https://github.blog/feed/ | https://github.blog/ | official_blog | A,C | auto | official_primary | 2 | no | verified_feed | 200 | 10 | 15960 | Thu, 22 Oct 2026 | review_required | keep |
| simscale-blog | https://www.simscale.com/blog/feed/ | https://www.simscale.com/blog/ | vendor_blog | A | auto | vendor | 2 | no | verified_feed | 200 | 10 | 49941 | Mon, 19 Oct 2026 | review_required | keep |
| hackernews-front | https://news.ycombinator.com/rss | https://news.ycombinator.com/ | community_aggregator | B,C | excerpt | community_aggregator | 2 | no | verified_feed | 200 | 30 | 68 | Thu, 22 Oct 2026 | review_required | keep_but_downrank |
| hn-ask | https://hnrss.org/ask | https://news.ycombinator.com/ask | user_forum | B | excerpt | community_primary | 3 | yes | verified_feed | 200 | 20 | 645 | Fri, 23 Oct 2026 | approved | keep |
| hn-show | https://hnrss.org/show | https://news.ycombinator.com/show | project_launch | B | excerpt | community_primary | 3 | yes | verified_feed | 200 | 20 | 274 | Fri, 23 Oct 2026 | approved | keep |
| precice-forum | https://precice.discourse.group/latest.rss | https://precice.discourse.group/ | user_forum | B,C | auto | community_primary | 3 | yes | verified_feed | 200 | 30 | 2252 | Tue, 20 Oct 2026 | approved | keep |
| paraview-forum | https://discourse.paraview.org/latest.rss | https://discourse.paraview.org/ | user_forum | B,C | auto | community_primary | 3 | yes | verified_feed | 200 | 30 | 1632 | Thu, 22 Oct 2026 | approved | keep |
| salome-forum | https://discourse.salome-platform.org/latest.rss | https://discourse.salome-platform.org/ | user_forum | B,C | auto | community_primary | 3 | yes | verified_feed | 200 | 30 | 1560 | Thu, 22 Oct 2026 | approved | keep |
| openai-community | https://community.openai.com/latest.rss | https://community.openai.com/ | user_forum | B | auto | community_primary | 3 | yes | verified_feed | 200 | 30 | 2733 | Fri, 23 Oct 2026 | approved | keep |
| simscale-forum | https://forum.simscale.com/latest.rss | https://forum.simscale.com/ | user_forum | B,C | auto | community_primary | 3 | yes | verified_feed | 200 | 30 | 1611 | Thu, 22 Oct 2026 | approved | keep |
| nvidia-newsroom | https://nvidianews.nvidia.com/rss.xml | https://nvidianews.nvidia.com/ | official_blog | A | auto | official_primary | 3 | no | not_a_feed | 200 |  |  | unknown | review_required | keep |
| nvidia-ir | _(none verified)_ | https://investor.nvidia.com/ | investor_relations | A | auto | official_primary | 2 | no | not_a_feed | 200 |  |  | unknown | review_required | investigate_usage_terms |
| microsoft-blog | https://blogs.microsoft.com/feed/ | https://blogs.microsoft.com/ | official_blog | A | auto | official_primary | 2 | no | verified_feed | 200 | 10 | 15666 | Tue, 20 Oct 2026 | review_required | keep |
| microsoft-research | https://www.microsoft.com/en-us/research/feed/ | https://www.microsoft.com/en-us/research/blog/ | research_feed | C | auto | primary_research | 2 | no | verified_feed | 200 | 10 | 23515 | Thu, 22 Oct 2026 | review_required | keep |
| amd-ir | https://ir.amd.com/news-events/press-releases/rss | https://ir.amd.com/ | investor_relations | A | auto | official_primary | 2 | no | not_a_feed | 200 |  |  | unknown | review_required | keep_but_downrank |
| google-research | https://research.google/blog/rss/ | https://research.google/blog/ | research_feed | C | auto | primary_research | 2 | no | verified_feed | 200 | 100 | 15 | Wed, 21 Oct 2026 | review_required | reconfigure |
| aws-ml-blog | https://aws.amazon.com/blogs/machine-learning/feed/ | https://aws.amazon.com/blogs/machine-learning/ | official_blog | A,C | auto | vendor | 2 | no | verified_feed | 200 | 20 | 28308 | Thu, 22 Oct 2026 | review_required | keep |
| imf-publications | _(none verified)_ | https://www.imf.org/en/Publications | government | A | excerpt | official_primary | 1 | no | unreachable | 403 |  |  | unknown | review_required | investigate_usage_terms |
| oecd-publications | _(none verified)_ | https://www.oecd.org/en/publications.html | government | A | excerpt | official_primary | 1 | no | unreachable | 403 |  |  | unknown | review_required | investigate_usage_terms |
| world-bank-research | _(none verified)_ | https://www.worldbank.org/en/research | government | A | excerpt | official_primary | 1 | no | not_a_feed | 200 |  |  | unknown | review_required | investigate_usage_terms |
| sia-news | _(none verified)_ | https://www.semiconductors.org/ | industry_association | A | excerpt | industry_association | 2 | no | not_a_feed | 200 |  |  | unknown | review_required | investigate_usage_terms |
| mit-tech-review | https://www.technologyreview.com/feed/ | https://www.technologyreview.com/ | news_media | A | excerpt | professional_media | 2 | no | verified_feed | 200 | 10 | 7716 | Thu, 22 Oct 2026 | review_required | keep |
| ieee-spectrum | https://spectrum.ieee.org/feeds/feed.rss | https://spectrum.ieee.org/ | news_media | A,C | excerpt | professional_media | 2 | no | verified_feed | 200 | 30 | 8340 | Thu, 22 Oct 2026 | review_required | keep |
## 3. 实测结论与建议

| source_id | 实测结论与建议 |
|---|---|
| openai-news | Feed 已验证，仅 146 字符摘要；公司官方叙事需与财报互证。 |
| deepmind-blog | 条目描述为空（中位 0，最大 210），实际只能产出 E0；需改用能取到正文的接入方式。 |
| huggingface-blog | 一次返回 889 条且正文全为空，属全量归档 + 标题流；现有接入方式无法使用。 |
| google-ai-blog | 252 字符摘要；产品营销占比高，A 通道需标注为官方自述。 |
| arxiv-cs-ai | 1523 字符为论文摘要，不是全文；只能作为 C 通道线索。 |
| arxiv-cs-lg | 1660 字符为论文摘要，不是全文；只能作为 C 通道线索。 |
| techcrunch-ai | 147 字符摘要，二手报道；重大事实须回溯原始公告。 |
| simon-willison | 1932 字符，接近全文；个人观点需与官方来源区分。 |
| github-blog | 15960 字符且含 content:encoded，接近全文。 |
| simscale-blog | 49941 字符，近全文；厂商自述，不得当作独立市场证据。 |
| hackernews-front | 68 字符，基本是链接流；只作发现入口，不作事实依据。 |
| hn-ask | 645 字符为提问正文；可证明有人提出问题，不能证明需求普遍。 |
| hn-show | 274 字符产品自述；不等于有人付费。 |
| precice-forum | 2252 字符为完整帖子。 |
| paraview-forum | 1632 字符为完整帖子。 |
| salome-forum | 1560 字符为完整帖子。 |
| openai-community | 2733 字符为完整帖子；社区讨论不代表官方立场。 |
| simscale-forum | 1611 字符为完整帖子。 |
| nvidia-newsroom | 原登记 /rss 实测为 HTML；已改为页面自带的 /rss.xml（已验证：20 条，正文中位 372 字符）。 |
| nvidia-ir | 声明地址为 HTML，页面未提供可发现的 Feed；feed_url 已留空，未找到可验证端点。 |
| microsoft-blog | 15666 字符，近全文；官方叙事需与财报互证。 |
| microsoft-research | 23515 字符，近全文；研究结果不等于产品可用性。 |
| amd-ir | 原登记地址为 HTML；已改为页面自带的 /rss（已验证），但条目描述为空，实际只能产出 E0。 |
| google-research | 100 条、正文中位 15 字符，实质是标题流。 |
| aws-ml-blog | 28308 字符，接近全文；厂商内容营销，不得作为独立市场证据。 |
| imf-publications | HTTP 403 且原地址为网页；feed_url 已留空，本机无法验证任何端点。 |
| oecd-publications | HTTP 403 且原地址为网页；feed_url 已留空，本机无法验证任何端点。 |
| world-bank-research | 声明地址为 HTML 且未发现 Feed；feed_url 已留空。 |
| sia-news | 声明地址为 HTML 且未发现 Feed；feed_url 已留空。 |
| mit-tech-review | 7716 字符，接近全文；二手报道。 |
| ieee-spectrum | 8340 字符，接近全文；技术媒体，商业结论需独立来源。 |
## 4. 关键发现（已实测事实）

1. **NVIDIA Newsroom 的登记端点不是 Feed。** `https://nvidianews.nvidia.com/rss` 返回 `text/html`；同页 `<link rel="alternate">` 指向 `https://nvidianews.nvidia.com/rss.xml`，实测为可解析 RSS（20 条，正文中位 372 字符，最新 2026-10-22）。
2. **AMD IR 的登记端点是新闻页。** 页面自带的 `https://ir.amd.com/news-events/press-releases/rss` 可解析，但条目描述为空（中位 0 字符），实际只能产出 E0。
3. **IMF 与 OECD 无法从本机验证**：两者均返回 HTTP 403，且登记地址本身就是出版页。
4. **World Bank 与 SIA 没有可发现的 Feed**：登记地址是网页，页面未声明任何 RSS/Atom。
5. **DeepMind Blog 的 Feed 条目正文为空**（中位 0，最大 210 字符），按现有规则只能产出 E0。
6. **Hugging Face Blog 一次返回 889 条且正文全为空**，属全量归档 + 标题流。
7. **Google Research 的条目正文中位 15 字符**，实质是标题流。
8. **18 个原始来源中 8 个、13 个候选中的 5 个**，Feed 携带 ≥1500 字符正文（见第 5 节名单）。

## 5. 判断与建议变更

### 5.1 已执行（2026-10-23 批准后）

| 来源 | 变更 |
|---|---|
| nvidia-newsroom | `feed_url` 改为实测可用的 `/rss.xml` |
| amd-ir | `feed_url` 改为实测可用的 `/rss`，并在 `review_notes` 标注"只能产出 E0" |
| nvidia-ir、world-bank-research、sia-news、imf-publications、oecd-publications | **清空 `feed_url`**，`review_notes` 记录"未找到可验证端点"。登记表不再用网页冒充 Feed |
| admin 校验 | `feed_url` 改为**仅启用行必填**；禁用候选可以暂时没有端点 |
| 11 个来源 | `content_access_level` 由 `auto` 改为 `full_text`（依据第 9 节两篇抽样核验） |
| 登记表 schema | 删除 `fallback_policy` 列及其解析、校验与文档（见第 11 节） |
| simscale-blog / simscale-forum | `terms_url` 改为官方现行页面（见第 12 节） |

`content_access_level=full_text` 是**内容获取质量的操作性分类**，不是对来源准确性、独立性、版权许可或自动再利用权限的认证。论坛、厂商博客与媒体来源即使正文完整，也不因此提高其事实可信度：`provenance_class` 与证据状态仍分别决定"一手/二手/厂商自述"和"主张是否可定位"。

### 5.2 建议但**未执行**，需要人工批准

1. **为 11 个来源声明 `content_access_level=full_text`**（2026-10-23 已完成每源两篇抽样核验，见第 9 节）：github-blog、simscale-blog、simon-willison、precice-forum、paraview-forum、openai-community、simscale-forum、microsoft-blog、aws-ml-blog、mit-tech-review、ieee-spectrum。
   `salome-forum` 有一篇样本为前缀式截断（窗口命中 2/5），`microsoft-research` 两次拉取均失败，**本轮不建议声明**。
   2026-10-23 已批准并写入两张登记表；`salome-forum` 与 `microsoft-research` 保持 `auto`。
2. **DeepMind Blog、Hugging Face Blog、Google Research、AMD IR** 在解决正文获取前，建议保持禁用或 `source_cap=0`。它们目前只会消耗采集与配额，产不出可进入简报的条目。
3. **`fallback_policy` 已批准删除并在本轮执行**（见第 11 节）。
4. **IMF、OECD** 需人工确认是否存在合规的程序化访问方式；在确认前保持 `feed_url` 为空并禁用。

## 6. 未核实项

- **所有来源的服务条款与内容复用许可**：本机只做了端点可达性与格式检查，没有做任何法律判断。`approved` 仅代表"本地私测允许"，不是法律结论。
- **更新频率与长期稳定性**：只做了一次拉取，不能据此判断是否会频繁失败或变更。
- **内容重叠度**：需要比对文章正文才能判断，未做。同名事件不自动等于重复报道。
- **信息增量**：需要人工阅读样本，未做。
- **FreshRSS 的 Readability/全文选项能否为标题流来源补充正文**：未验证。

## 7. 影子运行方案（未执行）

前置条件：可用的 FreshRSS、本地 llama-server、至少一个已批准来源。步骤：

1. 复制 `config/sources.local.csv` 为 A（现状）与 B（候选配置），B 只改 `editorial_lanes`/`content_access_level`/`enabled`，不改评分与证据规则。
2. 用 `OR_SOURCES_PATH` 切换配置，用**独立的 `OR_DB_PATH`** 隔离两个数据库，避免历史互相污染。
3. 各跑 3 天，逐日记录：新增事件数、重复事件数、A/B/C 分布、E0/E1/E2 分布、priority/watch/filtered 分布、来源未匹配数、获取失败数、文章级重复率、需人工核验条目数、B 相对 A 的独有事件、以及这些事件的人工价值判断。
4. 判定标准：若 B 的新增主要来自重复内容、低质量摘要或无关文章，应调整来源，而不是降低准入矩阵。

当前**没有**这些数字，本文件不提供任何模拟值。

## 8. 回滚方案

- 本轮全部改动都在工作区，**未提交、未推送**。
- 仅回滚登记表：`git checkout -- config/sources.csv config/sources.local.csv`。
- 回滚前的 `feed_url` 原值（如需手工恢复）：
  - nvidia-newsroom: `https://nvidianews.nvidia.com/rss`
  - nvidia-ir: `https://investor.nvidia.com/investor-resources/rss/default.aspx`
  - amd-ir: `https://ir.amd.com/news-events/press-releases`
  - world-bank-research: `https://www.worldbank.org/en/research`
  - sia-news: `https://www.semiconductors.org/feed/`
  - imf-publications: `https://www.imf.org/en/Publications`
  - oecd-publications: `https://www.oecd.org/en/publications.html`
- 禁用某个来源不会删除任何历史数据：`enabled=false` 只影响后续采集。
- `--render-only` 是只读路径（数据库以 `mode=ro` 打开），回滚不会产生数据库差异。

## 9. 全文抽样核验（任务 A，2026-10-23）

每个来源取两篇样本：按正文长度排序后取第 25 与第 75 百分位，避免只测极端值。对每篇比较 Feed 正文与原文页面。

判定口径（每篇独立判定）：

- 在 Feed 正文上均匀取 5 个 160 字符窗口（跳过末尾 10%，那里常是作者简介/页脚），检查是否都能在页面正文中找到；同时检查 Feed 正文是否以 `…`、`Read more` 等截断标记结尾。
- `full_text_confirmed`：≥4/5 窗口命中，且无截断标记。
- `excerpt_confirmed`：≤3/5 命中，或有截断标记。
- `inconclusive`：原文页面无法提取正文（<400 字符，通常为拦截页或需 JS），或 Feed 正文 <200 字符不足以判断。

同时记录整串包含（`feed ∈ page`）、长度比与原文页长度，供人工复核。**整串包含不作为判定依据**：原文页会插入图注、代码块与页脚，完整正文也很少逐字整段出现。

| source | 两篇结论 | 综合 |
|---|---|---|
| github-blog | full / full | **full_text_confirmed** |
| simscale-blog | full / full | **full_text_confirmed** |
| simon-willison | full / full（均 4/5） | **full_text_confirmed** |
| precice-forum | full / full | **full_text_confirmed** |
| paraview-forum | full / full | **full_text_confirmed** |
| salome-forum | **excerpt**(2/5) / full | excerpt_confirmed |
| openai-community | full / full | **full_text_confirmed** |
| simscale-forum | full / full | **full_text_confirmed** |
| microsoft-blog | full / full（ratio≈1.0） | **full_text_confirmed** |
| microsoft-research | Feed 两次拉取均失败 | inconclusive |
| aws-ml-blog | full / full | **full_text_confirmed** |
| mit-tech-review | full / full | **full_text_confirmed** |
| ieee-spectrum | full / full | **full_text_confirmed** |

逐篇明细：

| source | # | 文章（截断） | feed_len | page_len | ratio | 窗口命中 | 结论 |
|---|---|---|---|---|---|---|---|
| github-blog | 1 | How to continue a GitHub Copilot app session i | 6792 | 7302 | 0.93 | 5/5 | full_text_confirmed |
| github-blog | 2 | How 3 Java Champions are using GitHub Copilot  | 21546 | 22131 | 0.974 | 5/5 | full_text_confirmed |
| simscale-blog | 1 | Engineering AI, explained | 12856 | 13119 | 0.98 | 5/5 | full_text_confirmed |
| simscale-blog | 2 | Mixing tank simulation: how to set up a stirre | 31268 | 23328 | 1.34 | 5/5 | full_text_confirmed |
| simon-willison | 1 | Chirp Pong | 590 | 1874 | 0.315 | 4/5 | full_text_confirmed |
| simon-willison | 2 | sparqlite: SPARQL 1.1 inside SQLite, written i | 1716 | 3156 | 0.544 | 4/5 | full_text_confirmed |
| precice-forum | 1 | Staggered timesteps with 3 participant couplin | 1006 | 2536 | 0.397 | 5/5 | full_text_confirmed |
| precice-forum | 2 | Error while coupling Atmospheric Boundarly Sol | 2823 | 3812 | 0.741 | 5/5 | full_text_confirmed |
| paraview-forum | 1 | ParaView is using the wrong VTK clip? | 547 | 1753 | 0.312 | 5/5 | full_text_confirmed |
| paraview-forum | 2 | ParaView 6.2.0 is now available! | 1213 | 1647 | 0.736 | 5/5 | full_text_confirmed |
| salome-forum | 1 | Utilisation de technique systèmes experts dans | 369 | 851 | 0.434 | 2/5 | excerpt_confirmed |
| salome-forum | 2 | NETGEN version in salome | 1399 | 1836 | 0.762 | 5/5 | full_text_confirmed |
| openai-community | 1 | Feature Request: Automatically Update Chat Tit | 1286 | 1958 | 0.657 | 5/5 | full_text_confirmed |
| openai-community | 2 | Feature Request: Opt-In AI Personhood Mode | 3969 | 4861 | 0.816 | 5/5 | full_text_confirmed |
| simscale-forum | 1 | Trouble completing the FEA simulation due to s | 669 | 1184 | 0.565 | 5/5 | full_text_confirmed |
| simscale-forum | 2 | Help verifying lift and drag coefficinets setu | 1730 | 4349 | 0.398 | 5/5 | full_text_confirmed |
| microsoft-blog | 1 | Microsoft to expand Azure Maia system to multi | 7754 | 7754 | 1.0 | 5/5 | full_text_confirmed |
| microsoft-blog | 2 | Advancing digital sovereignty with greater con | 12968 | 13098 | 0.99 | 5/5 | full_text_confirmed |
| microsoft-research | – | Feed 两次拉取均失败 | – | – | – | – | inconclusive |
| aws-ml-blog | 1 | How U.S. Hunger connects leaders and data usin | 15315 | 14561 | 1.052 | 5/5 | full_text_confirmed |
| aws-ml-blog | 2 | Stop guessing auto scaling targets for TTS on  | 21565 | 21108 | 1.022 | 5/5 | full_text_confirmed |
| mit-tech-review | 1 | We can do impossible things | 3386 | 4315 | 0.785 | 5/5 | full_text_confirmed |
| mit-tech-review | 2 | The Download: computing’s next leap and permaf | 6254 | 7119 | 0.878 | 5/5 | full_text_confirmed |
| ieee-spectrum | 1 | Why AI Can’t Replace Engineering Teams | 4272 | 4672 | 0.914 | 5/5 | full_text_confirmed |
| ieee-spectrum | 2 | Why Engineers Should Brave Capitol Hill | 8095 | 8415 | 0.962 | 5/5 | full_text_confirmed |
**结论**：11 个来源两篇样本均确认完整，且未发现系统性内容缺失，符合提出 `full_text` 的条件。`salome-forum` 与 `microsoft-research` 不符合。**登记表未做任何修改**，等待人工批准后执行。

已知局限：每源仅两篇；`simon-willison` 的两篇命中为 4/5（一个窗口因原文页插入引用块而错位），判断为可接受但需人工复核该源。

## 10. 低信息量来源处置（任务 C）

| source | Feed | 条目数 | 样本正文长度 | 空正文 | 建议 |
|---|---|---|---|---|---|
| deepmind-blog | RSS 可解析 | 100 | 中位 81 / 最大 210（60 篇样本） | 26/60 | 保持禁用，重新配置接入方式 |
| huggingface-blog | RSS 可解析 | 889 | 全部为 0（60 篇样本） | 60/60 | 保持禁用，重新配置 |
| google-research | RSS 可解析 | 100 | 中位 15 | 未取得完整分布（拉取超时） | 保持禁用，重新配置 |
| amd-ir | RSS 可解析 | 10 | 全部为 0 | 10/10 | 保持禁用；端点已修正但无正文 |

四个来源当前 `enabled=false`、`review_required`，**无需修改状态**。在正文获取问题解决前，它们只会消耗采集与配额，不会产出可进入简报的条目（E0 一律过滤）。

**更正一处此前建议**：我上一轮提到可以用 `source_cap=0` 处理这些来源，这是错的——按当前实现 `source_cap=0` 表示**不设配额**，不是禁用。禁用只能通过 `enabled=false`，本轮不改变任何来源的启用状态。

## 11. `fallback_policy` 审查（任务 D）

代码搜索结果：

| 位置 | 用途 |
|---|---|
| `source_policy.py` | 解析为 `Source.fallback_policy` |
| `source_audit.py` | 校验取值 ∈ {skip, title_only, retry_later} |
| `admin_server.py` | 作为可编辑字段读写 |
| `README.md`、`docs/SOURCE_POLICY.md`、`docs/EVIDENCE_AND_LANES.md` | 文档描述 |

**没有任何运行代码读取该字段。** 它当前只有"被解析、被校验、被显示"三种行为，没有语义。

建议**删除**，而不是补实现：

1. 抓取失败的处理今天已经在 `cli.py` 中（单篇失败计入 `errors`、整轮失败走 `analysis_failed`），再加一层按来源的回退策略会引入第二种失败语义，且没有真实需求驱动。
2. 若要保留，必须先明确目标语义（例如"该来源本轮失败时，是否用上次结果补位"），这会牵涉历史复用与重复推送，属于新产品能力，不是治理字段。

**执行结果（2026-10-23，已批准）**：已从两张 CSV、`source_policy.Source` 与解析、`source_audit` 的 `ALLOWED_FALLBACK` 与校验分支、`admin_server.SOURCE_FIELDS`、`README.md`、`docs/SOURCE_POLICY.md`、`docs/EVIDENCE_AND_LANES.md` 及测试中移除。全仓库搜索确认代码内已无引用（本文件保留的是历史记录）。抓取失败与整轮失败仍由 `cli.py` 现有的 `errors` / `analysis_failed` 语义处理，行为未变。

## 12. 使用条款待核实清单（任务 E）

只核对"条款页面是否存在、是否可访问"，以及对文本中是否出现 RSS / 自动化获取 / 再分发字样做机械标记。**未做任何法律判断**；出现这些字样不代表禁止，未出现也不代表允许。

| source | 登记 terms_url | HTTP | 文本含 "rss" | 含自动获取/爬取字样 | 含再分发字样 |
|---|---|---|---|---|---|
| github-blog | https://docs.github.com/en/site-policy/github-terms/github-terms-of-service | 200 | 否 | 是 | 否 |
| simscale-blog | https://www.simscale.com/terms-and-conditions/ | 200（正文疑为动态渲染） | – | – | – |
| simon-willison | https://simonwillison.net/about/ | 200 | 否 | 否 | 否 |
| precice-forum | https://precice.discourse.group/tos | 200 | 否 | 是 | 否 |
| paraview-forum | https://discourse.paraview.org/tos | 200 | 否 | 否 | 否 |
| openai-community | https://community.openai.com/tos | **403** | – | – | – |
| simscale-forum | https://www.simscale.com/forum/faq | 200 | – | – | – |
| microsoft-blog | https://www.microsoft.com/en-us/legal/terms-of-use | 200 | 否 | 是 | 是 |
| aws-ml-blog | https://aws.amazon.com/terms/ | 200 | 否 | 否 | 否 |
| mit-tech-review | https://www.technologyreview.com/terms-of-service/ | 200 | 是 | 是 | 是 |
| ieee-spectrum | https://www.ieee.org/site-terms-of-use.html | 202 | 否 | 否 | 否 |

需要人工处理：

1. **simscale 的两个登记条款地址原为 404，已改为官方现行页面**（博客 → `/terms-and-conditions/`，论坛 → `/forum/faq`），两者分别登记，不共用许可结论。主站条款页返回的可见文本仅约 1.4KB，疑为动态渲染，**条款全文与版本日期未能从本机确认**；内容复用、自动采集、商业再发布三项许可仍为 `unknown`。
2. **openai-community 的条款页 403**，无法从本机读取。
3. 其余来源虽可访问，但**没有一条经过人工阅读**；`review_status` 继续为 `review_required`，`approved` 仅表示本地私测允许。
4. 公开可访问、可订阅、可自动获取、可再利用是四种不同权限，本表不区分它们——这正是需要人工判断的部分。

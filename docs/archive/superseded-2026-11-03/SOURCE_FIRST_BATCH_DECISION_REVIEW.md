# 第一批信息源决策审查

版本：0.1（审查稿，等待决策）
日期：2026-11-02
基线：`main@1c45b9b`；N0–N5 冻结在 Batch 16
审查对象：GDELT、FRED、BLS、Federal Register、SEC EDGAR 扩展
性质：只读审查。未修改生产代码、数据库、配置、调度任务或运行行为；未接入真实 API；未申请账号或购买服务。

依据文件：

- [SOURCE_INTELLIGENCE_RESEARCH.md](SOURCE_INTELLIGENCE_RESEARCH.md)
- [SOURCE_INTELLIGENCE_ROADMAP.md](SOURCE_INTELLIGENCE_ROADMAP.md)
- [source-catalog.csv](source-catalog.csv)
- [source-tools-comparison.csv](source-tools-comparison.csv)
- [source-coverage-matrix.csv](source-coverage-matrix.csv)
- 当前 [PROJECT_STATUS.md](PROJECT_STATUS.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、[SOURCE_POLICY.md](SOURCE_POLICY.md)
- 当前 SEC 摄取实现：[sec.py](../opportunity_radar/ingest/sec.py)、[rights.py](../opportunity_radar/ingest/rights.py)、[store.py](../opportunity_radar/ingest/store.py)

---

## 1. 当前信息发现缺口的归纳

### 1.1 当前系统实际处在什么位置

| 项目 | 当前实际 | 含义 |
|---|---|---|
| 文章 | 126 篇，117 篇已分析 | 样本小，且集中在已订阅来源 |
| 来源结构 | L5 82 篇（65.1%）、L3 32 篇（25.4%）、L0 12 篇（9.5%） | 主要是社区/新闻，官方一手很少 |
| 事件 | 117 个，**0 个多文章事件** | 跨来源事件尚未形成 |
| 证据/主张 | 220 / 220，全部骨架、未核验 | 生产链路没有可核验数值主张 |
| 实体/关联 | 10 entities、2 mentions、3 candidate links | 实体解析很薄；3 条关联全部 candidate |
| 关联质量 | 3 条 link 的 gap_days 约 93.7 天 | 关联是规则产物，不是已确认事件链 |
| 谱系 | `syndication_group` 全空；`multi_source_coverage=0` | 无法计算独立佐证 |

### 1.2 四类缺口

1. **发现缺口**：只能看到已订阅 Feed；没有“订阅外发生了什么”的入口。
2. **一手验证缺口**：新闻/社区内容是二手线索；没有企业申报、政策原文、宏观序列来验证。
3. **背景缺口**：宏观只有 BEA/Fed/ONS 的标题级文章，没有就业、通胀、工资、序列修订。
4. **关联缺口**：没有多文章事件；现有 3 条 claim↔event 关联全部 candidate，且时间差很大；没有可复用的 event→entity→evidence 链。

### 1.3 第一批要验证的假设

这批来源不是“接上就有价值”。它们是五个待验证假设：

| 假设 | 内容 | 当前证据 |
|---|---|---|
| H1 | GDELT 能发现现有 RSS 之外的相关事件/URL | 尚未运行；0 条 GDELT 数据 |
| H2 | SEC EDGAR 的 filing 级数据能解释/补充公司事件 | 当前只有 10 家公司 revenue/capex facts；无 filing 事件表 |
| H3 | BLS/FRED 能为政策/企业事件提供宏观背景 | 当前无 BLS/FRED 数据；只有 BEA/Fed/ONS 标题 |
| H4 | Federal Register 能比新闻更早/更准地提供政策变化 | 当前无政策来源；只有 Fed 货币政策新闻稿 |
| H5 | 四类来源可以形成“发现→一手→背景→实体”的链 | 当前 0 多文章事件；3 条 candidate link；未验证 |

**审查立场**：H1–H5 都是待验证假设，不是当前能力。第一批试点的目的，是用可量化数据判断它们是否成立，而不是“把五个 API 接上”。

---

## 2. 五个候选来源逐项评价

### 2.1 总表

| 来源 | 核心价值 | 与现有重叠 | 一手/线索 | 商业权利 | 工程成本 | 建议 |
|---|---|---|---|---|---|---|
| **GDELT** | 全球/多语言事件发现、URL/域名 | 低；无 GDELT 数据；可能与 BBC/NYT 文章重复 | 线索/发现，不是证据 | 数据可商用需署名；上游文章正文另核 | 低 | **立即试点（影子）** |
| **FRED** | 美国/全球宏观序列、修订、元数据 | 中；与 BEA/Fed 部分重叠 | 二次汇编，不是独立一手 | 无一般再分发权；第三方序列受限；展示待确认 | 低 | **随后/有条件** |
| **BLS** | 就业、CPI、工资、生产率 | 低；现有宏观只有 BEA/Fed/ONS 标题 | 一手官方统计 | 公共领域；署名；BLS 徽标商标 | 低 | **立即试点** |
| **Federal Register** | 美国法规、拟议规则、公告 | 无；只有 Fed 货币政策新闻稿 | 一手政策原文 | 美国政府作品；API 非官方法律版 | 低 | **立即试点（窄范围）** |
| **SEC EDGAR 扩展** | 8-K/10-Q/10-K、Form D、filing 级事件 | 低–中；现有 10 家公司 revenue/capex facts；RSS 仅 NVIDIA 新闻 | 一手企业披露 | SEC 内容可复用；第三方附件未清 | 中 | **随后，窄范围** |

### 2.2 GDELT

**能提供什么现有系统无法获取的信息**

- 全球新闻的事件/文章发现：65 种语言、最近 3 个月滚动、历史可到 2017；返回标题、URL、域名、语言、来源国、时间。`[官方]`
- 跨订阅来源的线索：中国/欧洲/亚洲、非英语媒体、行业媒体，当前 RSS 没有。
- 事件时间线/tone/来源国等聚合视图（可选），用于判断某议题是否在升温。

**是否与现有 RSS/SEC/EIA 重复**

- 当前没有 GDELT 数据；新增是真实的。
- 可能与 BBC/NYT/Reuters 等已订阅来源的同一篇文章重复；必须在 URL/标题/正文层面去重。
- 与 SEC/EIA 不重复：GDELT 是新闻发现，SEC/EIA 是结构化一手数据。

**一手还是线索**

- **线索/发现**。GDELT 是聚合器，不原创事实；它返回的标题/URL 不能直接作为 evidence/claim。
- 上游文章的权利不由 GDELT 授予；正文不能默认存储/展示/再分发。

**对四类情报的价值**

| 类型 | 价值 |
|---|---|
| 商业 | 中高：发现公司/行业事件、并购/投资/工厂/产品线索；需回溯原始来源 |
| 科技 | 中高：AI/半导体/数据中心/能源事件；对技术细节不如论文/企业披露 |
| 经济 | 中：政策/贸易/宏观新闻发现；数值需官方统计验证 |
| 产业 | 高：跨地区产业事件/供应链/政策线索；需要行业词表和实体解析 |

**持续追踪与提前性**

- 可持续：每日/15 分钟更新；但官方未公布固定配额，实践约 1 请求/5 秒、单次最多 250 条；无 SLA。`[官方/第三方]`
- “提前”是相对于**本系统现有 RSS**，不保证早于原始新闻发布；必须用试点测量。

**授权边界**

- GDELT 自有数据：官方声明可用于学术、商业、政府用途，无费用；再分发需引用 GDELT。`[官方]`
- 上游文章：标题/URL/正文权利属于原发布者；GDELT 不授予。
- 建议：只存 discovery metadata（URL、domain、title、seendate、language、sourcecountry、query）；不存正文；订阅展示/再分发保持 `CONDITIONAL`，需逐源确认。
- **注意**：`source-catalog.csv` 中 `long_term_storage=ALLOWED` 应理解为 GDELT 自有数据/元数据；上游文章正文不在该授权内。本次审查不修改目录，但把这一点作为接入前置条件。

**工程边界**

- 写入 `discovery_candidates`，不写 Article、不写 evidence/claim。
- 需要 URL 规范化、域名审批、去重、限流/退避、失败记录。
- 与现有 event/entity 的关联只能是 candidate；不能自动合并。

**结论**

**立即试点，但只做影子发现。** 这是低成本、高学习价值的一步；在证明“RSS 外新增价值”之前，不进入日报/证据链。

### 2.3 FRED

**能提供什么**

- 美国及部分全球宏观序列：GDP、通胀、就业、利率、消费、生产等；带 series metadata、频率、单位、季调、更新时间。`[官方]`
- 历史序列与修订；比 RSS 标题更适合做背景和趋势。
- 可作为 BEA/Fed/ONS 的补充，但不能替代原始发布机构。

**是否重复**

- 与 BEA/Fed 部分重叠；FRED 是二次汇编，很多序列来自这些机构。
- 与现有 RSS 不重复：RSS 只有标题/新闻稿，没有序列。
- 不能把 FRED 序列与 BEA/Fed 序列当作两份独立证据；需要 series-level provenance。

**一手还是线索**

- **二次汇编/分发**，不是独立一手来源。
- 对“某个数字是多少”可作为上下文；对“该数字是否权威”应回到原始机构（BEA/BLS/Fed 等）。

**对四类情报的价值**

| 类型 | 价值 |
|---|---|
| 商业 | 中：利率/通胀/消费背景；不直接给公司事件 |
| 科技 | 低–中：宏观需求/投资背景 |
| 经济 | 高：宏观序列/修订 |
| 产业 | 中：行业需求背景；需行业数据补充 |

**持续追踪与提前性**

- 可持续：每日更新；API key；无公开数值配额；适合增量同步。`[官方]`
- 不是“新闻提前”，而是数据更新/发布日历；对政策/市场的解释价值取决于分析层。

**授权边界**

- 免费 API key；无公开数值上限；但银行可调整带宽/交易限制。`[官方]`
- **没有一般再分发权**；第三方序列可能受版权限制；必须显示指定声明："This product uses the FRED API but is not endorsed or certified by the Federal Reserve Bank of St. Louis." `[官方]`
- 内部人类分析大概率可用；AI 处理、衍生数据、订阅展示/再分发在条款中没有明确授权 → 标 `PENDING_VERIFICATION`，不能升级为 `ALLOWED`。
- 原始序列直接对外展示/再分发应暂缓；若只做内部背景/派生指标，需要法务确认。

**工程边界**

- 写入 `macro_observations`（observation 模型），不写 Article。
- 需要 series_id、单位、频率、季调、期间、revision、vintage、source_url、retrieved_at。
- 不能把不同 series 拼成一条“宏观序列”；不能把 FRED 与 BEA/Fed 当独立双源。

**结论**

**随后接入，且有条件。** 如果只用于内部背景，可在 BLS 之后试点；如果要向订阅用户展示原始序列/衍生数据，先解决权利问题。FRED 不是第一批最安全的来源；BLS 的公共领域属性更清晰。

### 2.4 BLS

**能提供什么**

- 就业、失业、CPI/PPI、工资、生产率、职位空缺等；月度/季度；历史序列；发布日历。`[官方]`
- 当前系统没有 BLS 数据；BEA/Fed/ONS 不覆盖这些指标。

**是否重复**

- 与现有宏观来源重叠很小；BEA 是 GDP/贸易/收入，Fed 是货币政策，ONS 是英国统计。
- 与新闻 RSS 不重复：RSS 只有新闻稿/解读，BLS 是序列与发布数据。

**一手还是线索**

- **一手官方统计**；可作为 primary evidence（数值/期间/单位需核验）。
- 比 FRED 更适合作为“官方数字”的来源，因为 BLS 就是原始发布者。

**对四类情报的价值**

| 类型 | 价值 |
|---|---|
| 商业 | 中高：劳动力成本、消费/就业背景；对招聘/薪酬/需求有解释力 |
| 科技 | 中：科技行业就业/工资背景；不直接给技术事件 |
| 经济 | 高：就业/通胀/工资 |
| 产业 | 中高：行业就业/工资/生产率；需行业细分序列 |

**持续追踪与提前性**

- 可持续：月度/季度发布；API v2 注册 key；约 500 查询/日、50 series/请求。`[官方]`
- 发布日通常早于新闻解读；但 BLS 不是“事件发现”工具，而是“数据背景”。

**授权边界**

- 公共领域，除先前有版权的照片/插图；可商用；建议署名；BLS 徽标是注册商标。`[官方]`
- 本地缓存、长期存储、分析、订阅展示、再分发基本清晰；仍需保留来源/期间/单位。
- 这是五个来源中权利最清晰的一个。

**工程边界**

- 写入 `macro_observations`；不写 Article。
- 需要 series_id、期间、单位、季调、revision、发布日、retrieved_at。
- 需要 release calendar/健康检查；不能把“没有新数据”当“没有变化”。

**结论**

**立即试点。** 低权利风险、低工程成本、直接补宏观/劳动力缺口；适合作为第一批的“确定性收益”。

### 2.5 Federal Register

**能提供什么**

- 美国联邦规则、拟议规则、公告、总统文件、机构通知；1994 起；文档级元数据/摘要/全文链接。`[官方]`
- 当前系统没有政策/监管原文；只有 Fed 货币政策新闻稿。
- 可形成政策/监管事件，早于或同步于新闻解读。

**是否重复**

- 与现有 RSS 基本不重复；Fed 新闻稿只覆盖货币政策，不覆盖机构规则/公告。
- 与 SEC 不重复：SEC 是企业披露，Federal Register 是法规/机构行动。
- 与 GDELT 不重复：GDELT 是发现；Federal Register 是原文/元数据。

**一手还是线索**

- **一手政策原文/官方公告**；可作为 primary evidence（需区分 rule/proposed rule/notice）。
- API 是原型，不是官方法律版；法律文本需回到 govinfo 验证。`[官方]`

**对四类情报的价值**

| 类型 | 价值 |
|---|---|
| 商业 | 高：监管变化、合规成本、市场准入 |
| 科技 | 中高：AI/半导体/能源/数据/出口管制相关规则 |
| 经济 | 中高：财政/贸易/监管政策 |
| 产业 | 高：能源、汽车、制造、金融、医疗等行业规则 |

**持续追踪与提前性**

- 可持续：每日发布；1994+ 历史；API 无 key。`[官方]`
- 通常早于/同步于新闻；但不是所有规则都有市场影响，需要机构/主题过滤。
- 需要处理 2,000 条结果上限、日期/机构过滤、文档类型。

**授权边界**

- 美国政府作品，公共领域；1 CFR 2.6 支持再发布；API 不是官方法律版。`[官方]`
- 本地缓存、长期存储、分析、订阅展示、再分发基本清晰；仍需署名/来源，法律文本以 govinfo 为准。
- 第三方材料/图片等例外需注意。

**工程边界**

- 写入 `policy_documents`；不写 Article。
- 字段：agency、document_type、title、abstract、published_at、effective_at、docket_id、citation、url、raw_snapshot。
- 先做窄范围 watchlist（例如 Commerce、Energy、Treasury、USTR、FTC、FCC、EPA、FDA），不要全量 ingest。

**结论**

**立即试点，但窄范围。** 权利清晰、无现有重叠、政策价值高；风险是噪声/数量，需机构/主题过滤。

### 2.6 SEC EDGAR 扩展

**能提供什么**

- `submissions` API：公司 filing history、form type、filing date、accession、primary document、8-K items 等；`companyfacts` 已有 XBRL facts。`[官方]`
- 当前 SEC lane 只取 10 家公司的 revenue/capex tags（2,719 facts），没有 filing 级事件表；扩展后可补 8-K/10-Q/10-K 事件、管理层变动、重大合同、回购、指引等。
- 对“公司自己披露了什么”是一手证据；通常早于/同步于新闻。

**是否重复**

- 与现有 RSS 重叠低：RSS 只有 NVIDIA Newsroom 等少量新闻；当前只有 2 个 entity mentions。
- 与现有 SEC facts 有部分重叠：同一 filing 会产生 facts；但 filing 级事件/表单类型/8-K item 是新增。
- 与 Federal Register/GDELT 不重复：SEC 是企业披露，另两者是政策/新闻发现。

**一手还是线索**

- **一手企业披露**；可作为 primary evidence。
- 但公司 filing 可能含第三方附件/展品，不能默认再分发；现有 `rights.py` 已把 third-party content 标为未清。`[当前代码]`

**对四类情报的价值**

| 类型 | 价值 |
|---|---|
| 商业 | 高：财报、管理层、并购、回购、资本开支、重大合同 |
| 科技 | 中高：研发/资本开支/数据中心/芯片公司披露 |
| 经济 | 中：企业投资/就业/需求信号 |
| 产业 | 高：半导体、能源、汽车、制造、金融等 |

**持续追踪与提前性**

- 可持续：submissions 实时更新（处理延迟通常 <1 秒）；XBRL <1 分钟；bulk 每晚。`[官方]`
- 通常早于新闻；但不是所有 filing 都重要，需 form/8-K item 过滤。
- 当前 10 家公司覆盖不均：ExxonMobil 只有 6 条 facts、TSM 只到 2024；扩展不能假设所有公司/标签一致。

**授权边界**

- SEC 政府内容/公开 EDGAR filing 一般可自由访问与复用；第三方展品/图片例外。`[官方]`
- 现有 `rights.py` 对 `sec-edgar` 状态 `APPROVED`，但 `third_party_content=False`；应继续“存 metadata/facts，不默认再分发展品”。
- 本地缓存/长期存储/分析/订阅展示：SEC 内容基本允许；第三方内容 `CONDITIONAL/UNKNOWN`。

**工程边界**

- 进入现有 SEC 独立摄取库，不进入 RSS 业务表/LLM/日报。
- 新增 `sec_filings`（accession、CIK、form、filed_at、period、primary_doc、items、url、raw_snapshot）；不要把所有 filing 正文塞进 `sec_facts`。
- `submissions` 官方文档化；`companyfacts` 官方文档化；**full-text search 未在官方 API 页面文档化**，Form D 没有单独官方 API，需解析 filing。`[官方]`
- 第一批建议只做 submissions 元数据 + 8-K item 摘要；full-text/Form D 延后。

**结论**

**随后接入，窄范围。** 价值高，但当前 SEC lane 只覆盖 10 家公司 revenue/capex；扩展是新的 filing 模型/解析工作，不宜与 GDELT/BLS/Federal Register 同时全量启动。

---

## 3. 来源之间的互补关系及尚未证实的假设

### 3.1 设想的链路

```
GDELT 发现事件/URL
  → 解析原始来源/域名
  → 若涉及公司：SEC EDGAR filing/companyfacts
  → 若涉及政策：Federal Register 原文
  → 若涉及宏观：BLS/FRED 序列
  → event/entity/evidence 关联
```

### 3.2 哪些是已证实的事实

- 当前 RSS 没有 GDELT/Federal Register/BLS/FRED 数据（来源清单/DB 可核对）。
- 当前 SEC 只有 10 家公司 revenue/capex facts；没有 filing 级事件表。
- 当前 0 个多文章事件；3 条 candidate link；2 个 entity mentions。
- 当前 `syndication_group` 空；`multi_source_coverage=0`。
- 因此，“四类来源能形成跨来源关联”**没有数据证据**，只是设计假设。

### 3.3 哪些是假设，如何验证

| 假设 | 验证方法 | 失败信号 |
|---|---|---|
| H1 GDELT 发现 RSS 外事件 | 影子运行 2–4 周；对比 URL/事件/域名；抽样人工相关性 | 新增候选大多噪声/重复/不可解析 |
| H2 SEC filing 解释公司事件 | 对 GDELT 公司事件抽样，查 ±N 天 SEC filing；人工判断关联 | 大多数事件无 filing；或 filing 与事件无关 |
| H3 BLS/FRED 提供宏观背景 | 对政策/公司事件匹配发布日/指标；检查是否增加解释力 | 指标与事件无时间/主题关联；或只是泛泛背景 |
| H4 Federal Register 早于新闻 | 对同一规则比较 FR 发布日与 RSS/新闻首次提及；测 lead time | 新闻总是更早；或 FR 文档与市场无关 |
| H5 发现→一手→背景→实体链可形成 | 抽样构建 candidate chains；人工评分 precision | 链条大量错误/无法回溯 |

### 3.4 关联规则建议

- GDELT → `discovery_candidate`；不直接生成 event/evidence。
- 原始来源未批准时，只保留候选 URL/域名/标题，不抓正文。
- SEC/Federal Register/BLS/FRED 各自进入独立记录类型；只有通过 entity/time/topic 规则才形成 candidate link。
- 聚合器不算独立来源；同一文章被多源转载只算一个传播单元；官方统计/企业披露/政策原文才是一手。
- 当前 3 条 candidate link 的 93.7 天 gap 说明：时间窗口规则需要重新设计；不能把“同公司+同期间”当事件关联。

---

## 4. 商业使用和数据留存的关键限制

| 来源 | 访问 | 本地缓存 | 长期存储 | 模型分析 | 订阅展示 | 再分发 | 关键依据/待确认 |
|---|---|---|---|---|---|---|---|
| **GDELT** | 免费、无 key | `ALLOWED`（元数据） | `ALLOWED`（GDELT 数据/元数据）；上游正文 `CONDITIONAL/UNKNOWN` | `ALLOWED`（发现） | `CONDITIONAL`（标题/链接；正文需原发布者权利） | `CONDITIONAL`（需署名；上游另核） | GDELT 条款允许商业使用并需引用；上游文章版权不由 GDELT 授予 |
| **FRED** | 免费 key | `ALLOWED` | `CONDITIONAL` | 内部分析大概率；AI/衍生 `PENDING_VERIFICATION` | `CONDITIONAL/PENDING` | 无一般再分发权 | 需指定声明；第三方序列可能受版权限制；展示/再分发需确认 |
| **BLS** | 免费 key | `ALLOWED` | `ALLOWED` | `ALLOWED` | `ALLOWED` | `ALLOWED` | 公共领域；署名；BLS 徽标商标 |
| **Federal Register** | 免费、无 key | `ALLOWED` | `ALLOWED` | `ALLOWED` | `ALLOWED` | `ALLOWED` | 美国政府作品；API 非官方法律版；法律文本回 govinfo |
| **SEC EDGAR** | 免费、10 req/s、UA | `ALLOWED` | `ALLOWED`（SEC 内容） | `ALLOWED` | `ALLOWED`（metadata/facts） | `CONDITIONAL`（第三方展品未清） | SEC 内容可复用；第三方附件/图片例外 |

**统一规则**

- `UNKNOWN` 不升级为 `ALLOWED`；`PENDING_VERIFICATION` 不代表允许。
- GDELT 只能存发现元数据；不存文章正文；订阅展示/再分发逐源确认。
- FRED 原始序列/衍生数据对外展示需确认；内部背景可先做。
- SEC 只存 metadata/facts；不默认再分发 filing 展品/附件。
- BLS/Federal Register 权利最清晰，适合作为第一批“确定性”来源。

---

## 5. 推荐接入顺序及理由

### 5.1 建议顺序

| 顺序 | 来源 | 方式 | 理由 | 前置条件 |
|---|---|---|---|---|
| **1** | **GDELT** | 影子 `discovery_candidates` | 低成本、快速验证发现缺口；不生成证据 | source_id/adapter/去重基线；只存元数据 |
| **2** | **Federal Register** | `policy_documents` | 权利清晰、无重叠、政策价值高；窄范围可控 | 机构/主题 watchlist；2,000 条上限；法律文本核验 |
| **3** | **BLS** | `macro_observations` | 权利最清晰、工程成本低、补就业/通胀/工资 | series 选择；发布日历；revision 处理 |
| **4** | **SEC EDGAR 扩展** | `sec_filings`（submissions） | 企业一手披露；现有 SEC 通道可复用 | 只做 10 家公司 submissions/8-K 元数据；不碰 full-text/Form D |
| **5** | **FRED** | `macro_observations` | 宏观覆盖更广，但权利/展示待确认 | 内部背景 vs 订阅展示决策；series provenance |

### 5.2 为什么不是五个同时启动

- GDELT 需要独立 discovery lane；不能塞进 Article。
- Federal Register/BLS 需要 observation/policy 记录类型；不能塞进 Article。
- SEC 扩展是新的 filing 模型 + 解析工作，不是“多取几个 tag”。
- FRED 权利/展示未确认；同时启动会把权利问题带进产品。
- 五个一起做会同时引入四种 schema、四种运行记录、四种失败模式，难以判断哪个来源真正有效。

### 5.3 建议的“立即试点 / 随后 / 暂缓 / 前置”

- **立即试点**：GDELT（影子）、Federal Register（窄范围）、BLS。
- **随后接入**：SEC EDGAR submissions（10 家公司，窄范围）。
- **暂缓**：FRED 的对外展示/原始序列再分发；SEC full-text/Form D；任何付费/社交来源。
- **前置问题**：
  1. `source_id`/adapter/rights metadata/去重基线（P0）；
  2. 独立 `discovery_candidates` / `macro_observations` / `policy_documents` / `sec_filings` 存储；
  3. 运行记录/配额/失败可见；
  4. GDELT 上游权利与 FRED 展示权的书面确认；
  5. 试点验收指标与停止条件。

---

## 6. 第一批试点的可量化评价指标

### 6.1 基线

| 指标 | 当前基线 |
|---|---|
| 文章 | 126 篇；117 已分析 |
| 多文章事件 | 0 |
| 独立佐证（multi_source_coverage） | 0 |
| `syndication_group` | 全空 |
| 实体 | 10 entities / 2 mentions |
| 候选关联 | 3 条，全部 candidate，gap ≈93.7 天 |
| SEC 覆盖 | 10 家公司，2,719 facts，revenue/capex |
| 政策来源 | 0（只有 Fed 货币政策新闻稿） |
| BLS/FRED | 0 |
| GDELT | 0 |

### 6.2 分来源指标

| 来源 | 指标 | 建议初始门槛（待确认） |
|---|---|---|
| GDELT | 每周 RSS 外候选数 | ≥10 个/周（可按来源词表调整） |
| GDELT | URL 可解析率 | ≥80% |
| GDELT | 与现有 RSS 重复率 | ≤20% |
| GDELT | 抽样人工相关性 | ≥50%（50 条样本，双人复核） |
| GDELT | 429/失败率 | <5%；全部写运行记录 |
| Federal Register | 每周相关文档数 | ≥5 条/周（窄 watchlist） |
| Federal Register | 机构/主题相关性 | 抽样 ≥70% |
| Federal Register | 比新闻早的天数 | 对可匹配规则测 lead time；不预设正负 |
| BLS | 覆盖 series 数 | ≥10 个核心 series，历史完整 |
| BLS | 数值与官方一致率 | 100%（抽样） |
| BLS | period/unit/revision 错误 | 0 个未记录错误 |
| SEC | 10 家公司 filing 元数据覆盖率 | 100% 可追溯（accession/url） |
| SEC | 8-K item 提取率 | ≥90%（抽样） |
| SEC | 与 RSS 重叠/补充 | 统计“filing 已被新闻覆盖”比例 |
| 跨来源 | 候选链数量 | ≥5 条/周（GDELT→原始→SEC/Fed Reg/BLS/FRED） |
| 跨来源 | 候选链人工 precision | ≥50%（抽样；聚合器不计独立） |
| 运维 | 每源错误/重试/陈旧 | 全部可见；无未处理 429 |
| 成本 | 工程小时/维护小时 | 记录实际值；不预设 |

> 上述门槛是产品决策建议，不是已测事实。建议先跑 4 周基线，再定 go/no-go 阈值。

### 6.3 不应使用的指标

- 接入来源数量、API 数量、抓取文章数。
- GDELT/FRED 的“覆盖国家/序列数”本身。
- 没有人工样本的“精确率/召回率”。
- 把转载/聚合器条目算作独立来源。

---

## 7. 需要我决定的事项

1. **第一批试点集合**
   - 建议：GDELT（影子）+ Federal Register（窄）+ BLS 立即；SEC EDGAR submissions 随后；FRED 有条件/随后。
   - 需要你确认：是否接受“SEC/FRED 不在第一批同时启动”。

2. **FRED 的使用边界**
   - 只做内部背景/派生指标，还是向订阅用户展示原始序列/衍生数据？
   - 后者需要法务确认；前者可先做但需标 `PENDING_VERIFICATION`。

3. **SEC EDGAR 扩展范围**
   - 建议只做 10 家公司 `submissions` + 8-K/10-Q/10-K 元数据；不做 full-text search/Form D。
   - 需要你确认是否接受这个窄范围；如果坚持 full-text/Form D，需另立阶段。

4. **GDELT 的展示边界**
   - 建议只进内部 admin/发现报告，不进订阅日报；标题/链接是否可展示需逐源确认。
   - 需要你确认：是否允许内部展示标题/URL；订阅展示暂缓。

5. **存储边界**
   - 是否批准独立 `discovery_candidates`、`macro_observations`、`policy_documents`、`sec_filings` 数据域；不写 RSS 业务表。
   - SEC 仍进现有 ingest DB；Federal Register/BLS/FRED 用独立库/命名空间。

6. **试点周期与 go/no-go**
   - 建议 4 周影子 + 2 周评审；是否接受？
   - 是否接受上面的指标作为初始门槛，或由你调整？

7. **权利复核责任人**
   - GDELT 上游文章权利、FRED 展示/再分发、SEC 第三方展品：谁负责法务/商务确认？
   - 在确认前，相关字段保持 `CONDITIONAL/PENDING_VERIFICATION`。

8. **BEA 是否作为 FRED 的替代/补充**
   - BEA 是更清晰的权利路径（美国政府作品）；如果只需要 GDP/贸易，BEA API 可能比 FRED 更稳。
   - 需要你决定：FRED 是否必须，还是 BEA + BLS 足够。

9. **是否允许宏观/政策数据进入日报**
   - 建议试点期只进内部观察/影子报告，不改日报/门禁；需要你确认。

10. **审批门**
   - 新来源接入属于 G5 范围；生产 Claim 仍需 G6；本次不启动 Batch 17、不启用 v7。
   - 需要你确认：本次只批准“试点设计/只读验证”，还是批准进入实现。

---

### 7.11 审查结论

**建议第一批实际接入顺序：**

1. **GDELT**：立即影子试点，只写 discovery candidates。
2. **Federal Register**：立即窄范围试点，写 policy_documents。
3. **BLS**：立即试点，写 macro_observations。
4. **SEC EDGAR submissions**：随后接入，限 10 家公司、filing 元数据/8-K 摘要。
5. **FRED**：有条件随后；先解决展示/再分发，再决定是否对外使用。

**不建议第一批同时启动五个来源。** GDELT 需要独立发现层；Federal Register/BLS 需要 observation/policy 模型；SEC 扩展是新的 filing 模型；FRED 权利待确认。先做三个低风险来源，能把“发现→一手→背景”的链路验证清楚，再决定 SEC/FRED 的投入。

**如果只能选三个：GDELT + Federal Register + BLS。**  
它们分别补“发现”“政策原文”“宏观/劳动力背景”，权利最清晰、工程成本最低、与现有 RSS/SEC/EIA 重叠最少。SEC 随后补企业披露；FRED 在权利确认后再补更广的宏观序列。

本次审查只新增本文件；未修改其他文档、代码、数据库或配置。等待你的决定后，再进入下一阶段。

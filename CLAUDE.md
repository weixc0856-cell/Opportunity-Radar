# Opportunity Radar — Professional Intelligence & Automated Research Quality Framework

版本：1.0
决策日期：2026-11-01
适用项目：Opportunity Radar
执行环境：Windows / Python / SQLite / FreshRSS / llama.cpp
核心原则：Evidence First、Source Independence、Reproducible Analysis、Quantitative Evaluation、Fail-Closed Publication。

> **本文件是项目主指导文件**，优先级高于 `README.md` 与 `docs/` 下的历史记录。
> 它是 2026-11-01 方向文档的第二版：与上一版冲突之处以本版为准（冲突清单见附录 B）。
> 当前执行指令见 §13：**R1 统一事件模型已分批交付并部署；R2 未开始，需 G6 批准。**
---

# 0. 本次决策的核心变化

本项目不再将个人新闻学背景、人工新闻判断或日常人工标签作为系统质量控制的必要条件。

用户不是专业新闻编辑、经济学研究员或事实核查员，因此不要求用户每天对文章打标签、判断新闻价值或评价模型输出。

后续以成熟的研究方法、统计方法、数据质量方法和自动化测试方法为主要质量控制体系。

系统应当具备：

1. 自动发现全球经济、商业、政策、产业和技术变化。
2. 自动识别事件及其相关来源。
3. 自动抽取结构化事实主张。
4. 将主张与原始证据建立可追溯关系。
5. 判断来源是否独立、是否转载、是否存在证据冲突。
6. 使用官方数据和专业研究进行交叉验证。
7. 进行统计计算、历史比较和量化回测。
8. 区分事实、解释、假设、预测和观点。
9. 自动评估研究质量和发布风险。
10. 对不能可靠验证的内容采取降级、隔离或阻止发布措施。

用户负责确定产品目标、商业关注方向和是否采取实际行动，不承担日常专业编辑职责。

人工复核机制可以保留，但不得成为日常运行的前置条件，也不得把人工标签数量作为阶段验收指标。

## 1. 项目最终定位

Opportunity Radar 定位为：

**全球商业、经济与政策情报 + 商业机会发现 + 技术与产业研究系统。**

不是普通 RSS 阅读器，不是新闻搬运工具，也不是让 LLM 自动生成财经文章的系统。

主要服务对象：

- 企业战略、业务发展、市场研究和企业创新人员。
- 咨询、产业研究、商业分析和投资研究人员。
- 独立创业者、产品构建者和商业机会探索者。
- 需要理解经济、政策、产业与技术变化的专业读者。

主要研究范围：

- 全球宏观经济和金融环境。
- 产业政策、贸易政策、监管和地缘经济。
- 企业经营、资本开支、并购、订单和竞争格局。
- 市场供需、价格、库存、产能和采购行为。
- AI、半导体、数据中心、能源、制造业、汽车、工业软件、机器人和工程技术。
- 新需求、买方痛点、商业模式、付费证据和市场缺口。

默认全球视角，重点关注美国、欧洲、中国及主要亚洲经济体。

不得因为某一地区的信息更新频繁，就将其误认为全球趋势。

## 2. 对标体系及其适用边界

借鉴以下机构公开可观察的研究和编辑原则，不声称掌握其内部未公开 SOP。

### 2.1 McKinsey / McKinsey Global Institute

借鉴：

- 研究问题驱动。
- 事实基础和数据支持。
- 产业结构分析。
- 经济与商业影响。
- 情景、假设和限制条件。
- 结论与决策相关性。

### 2.2 Deloitte / PwC / EY / KPMG

借鉴：

- 结构化研究框架。
- 产业链与市场分析。
- 多维指标体系。
- 证据来源与方法透明。
- 风险识别和交叉验证。
- 定量研究与定性研究结合。

### 2.3 The Economist / Financial Times / Reuters / AP / Bloomberg

借鉴：

- 选题重要性。
- 全球视角。
- 事实准确性。
- 来源透明。
- 不同利益相关方观点。
- 对新闻事件背后机制的解释。
- 对错误和修订的透明处理。

### 2.4 IMF / OECD / World Bank / BIS / IEA / WTO

借鉴：

- 统计定义。
- 数据口径。
- 时间序列。
- 国际可比性。
- 方法论和假设透明。
- 数据修订记录。
- 预测与实际结果区分。

不得把机构声誉直接等同于某条结论的正确性。

## 3. A/B/C 三条研究通道

保留现有三条通道。

### A：Global Economy, Business & Policy Intelligence

研究范围：

- 宏观经济。
- 货币和财政政策。
- 贸易和地缘经济。
- 产业政策和监管。
- 企业战略与资本开支。
- 行业供需和竞争格局。
- 主要经济体和行业变化。

每个重点事件回答：

1. 发生了什么？
2. 相对历史基线发生了什么变化？
3. 为什么值得关注？
4. 哪些国家、行业和企业受到影响？
5. 目前有哪些不同解释？
6. 哪些数据可以支持或反驳当前判断？
7. 接下来应当观察什么？

### B：Business Opportunity Intelligence

研究范围：

- 新需求。
- 买方痛点。
- 企业采购。
- 付费行为。
- 供给缺口。
- 商业模式。
- 新产品和服务。
- 新市场进入机会。

机会状态：

signal_detected
→ problem_supported
→ buyer_identified
→ payment_verified
→ opportunity_candidate

每一级状态必须有对应证据。

融资、融资金额、产品定价、网站访问量、开源项目 Star 数量和厂商宣传不能单独证明买方付费意愿。

### C：Technology & Engineering Intelligence

研究范围：

- AI 和软件工程。
- 半导体与算力。
- 数据中心。
- 能源。
- 制造业。
- 汽车和交通。
- 工业软件和 CAE。
- 机器人。
- 新材料和工程技术。

区分：

- 论文研究。
- 实验验证。
- 开源实现。
- 工程验证。
- 商业产品。
- 客户部署。
- 可规模化商业应用。

技术新颖性不等于商业成熟度。

## 4. 取消日常人工标签制度

明确规定：

- 不要求用户每日标注 5 条文章。
- 不要求用户对模型输出打分。
- 不要求用户判断每条新闻是否重要。
- 不要求用户判断每个经济指标是否正确。
- 不把 reviews 数量作为 R3、R6 的验收条件。
- 不把模型自评作为事实准确率的证据。

保留 reviews 和 review_history 表及相关功能，供未来可选使用。

如果用户主动开展商业验证，可以记录访谈、采购沟通、试点、客户回复和实际收入等结果。

这属于可选业务反馈，不属于每日系统维护任务。

## 5. 建立自动化研究质量体系

建立五个相互独立的质量层。

### Q1：Evidence Quality

判断：

- Claim 是否有原文证据。
- 引文是否完整。
- 定位是否有效。
- 来源是否可追溯。
- 证据是否直接支持该主张。
- 原始内容是否能够在事后复核。

关键事实不能仅依赖模型生成的摘要。

### Q2：Source Independence

每个来源增加或关联：

- source_family。
- parent_source。
- syndication_group。
- ownership_group。
- source_type。
- primary_or_secondary。
- independence_status。

来源关系至少区分：

- independent_primary。
- independent_secondary。
- syndicated。
- republished。
- derived_from_same_source。
- unknown。

多来源验证必须按独立来源关系计算，不能按文章数量计算。

### Q3：Claim Verification

检查：

- 主体。
- 指标。
- 数值。
- 单位。
- 币种。
- 地区。
- 时间范围。
- 比较口径。
- 分母。
- 季节调整。
- 数据修订状态。
- 引文支持关系。

派生数据必须保存公式、输入值和来源。

不能使用简单数字集合匹配代替数值语义核验。

### Q4：Analytical Quality

区分：

- fact。
- source_interpretation。
- system_inference。
- hypothesis。
- forecast。
- opinion。

每项分析应记录：

- 支持证据。
- 反面证据。
- 使用的假设。
- 推论边界。
- 置信度依据。
- 尚未解决的问题。

模型不能自行声明一个没有证据基础的高置信度。

### Q5：Publication Quality

检查：

- 来源合规。
- 事件去重。
- 证据完整。
- 数值核验。
- 分析边界。
- 报告结构。
- 链接和归档。
- 运行完整性。

发布状态：

PASS
PASS_WITH_LIMITATIONS
HOLD
REJECT

不得将系统运行失败伪装成没有有效情报。

## 6. 权威信源与交叉验证体系

来源按用途分层，而不是仅按品牌排名。

### L0：原始事实来源

包括：

- 各国统计局。
- 中央银行。
- 财政部门。
- 监管机构。
- 政府政策发布部门。
- 企业公告和财报。
- 官方能源、贸易和产业数据。

主要用于核实原始事实。

### L1：国际经济研究与数据机构

包括：

- IMF。
- OECD。
- World Bank。
- BIS。
- IEA。
- WTO。
- Eurostat。
- 各国官方统计机构。

主要用于宏观经济、产业数据和国际比较。

### L2：咨询和产业研究

包括：

- McKinsey。
- Deloitte。
- PwC。
- EY。
- KPMG。
- 其他有明确研究方法的行业研究机构。

主要用于商业影响、产业结构和行业研究。

报告预测必须标记为预测，不能直接转化为已发生事实。

### L3：权威新闻媒体

包括：

- Reuters。
- Associated Press。
- Financial Times。
- The Economist。
- Bloomberg。
- Wall Street Journal。
- Nikkei Asia。

主要用于事件发现、背景补充、独立采访和不同立场分析。

### L4：专业技术来源

包括：

- 学术论文。
- 标准组织。
- 研究实验室。
- 企业技术文档。
- 工程测试报告。
- 开源项目。

主要用于技术进展和工程证据。

### L5：早期信号来源

包括：

- Hacker News。
- 开发者社区。
- 专业论坛。
- 社交媒体。

仅作为线索来源，不直接作为重大事实和商业需求的最终依据。

### 交叉验证原则

禁止简单采用"几家媒体都报道了"作为独立验证标准。

必须建立：

Claim
→ Evidence
→ Article
→ Source
→ Source Family

每个 Claim 记录：

- 支持来源数量。
- 独立来源数量。
- 原始来源数量。
- 二手来源数量。
- 转载来源数量。
- 冲突来源数量。
- 证据直接程度。

相同新闻稿被多个媒体转载，只能视为一个原始信息来源。

同一事实由官方数据、企业财报和独立调查分别支持，才具有更强的交叉验证价值。

## 7. 量化回测体系

不依赖日常人工标签，但必须建立可复现的自动化评估。

### 7.1 固定基准样本集

建立 Benchmark Corpus。

样本来源：

1. 官方政策和公告。
2. 官方宏观经济数据。
3. 企业财报。
4. 有明确原始证据的产业事件。
5. 已知转载和重复报道。
6. 已知数据修订案例。
7. 特意构造的数值和时间错误样本。
8. 已知存在反面证据的事件。
9. 论文、技术项目和商业部署的区分案例。

优先使用具有结构化 ID、原始发布记录和可重复获取结果的样本。

样本分为：

- deterministic_gold：可以通过确定性规则核验的样本。
- source_grounded：具有明确原始资料和证据定位的样本。
- synthetic_adversarial：专门构造的错误样本。
- historical_cases：有完整时间线的历史事件。
- unresolved_cases：无法形成确定答案的案例。

不能将模型自己生成的答案作为唯一 Gold Label。

### 7.2 评估指标

| 指标 | 用途 |
|---|---|
| Claim Evidence Coverage | 重要主张的证据覆盖率 |
| Citation Support Rate | 引文对主张的支持比例 |
| Numeric Consistency Rate | 数值、单位和期间一致性 |
| Entity Consistency Rate | 主体识别一致性 |
| Source Independence Rate | 独立来源覆盖情况 |
| Duplicate Cluster Precision | 事件聚类准确性 |
| Duplicate Cluster Recall | 重复事件识别覆盖率 |
| Contradiction Detection Rate | 已知冲突样本检出率 |
| Unsupported Claim Rate | 无证据主张比例 |
| Schema Validity Rate | 结构化输出有效率 |
| Publication Gate Escape Rate | 不合格内容错误通过发布门禁的比例 |
| Runtime Failure Rate | 运行失败率 |
| Source Yield | 来源有效产出 |
| Evidence Pass Rate | 来源证据通过率 |

必须区分真实测量指标和代理指标。

例如：

- 在确定性 Gold 样本上的数字一致性可以进行客观测量。
- 在没有完整真值的新闻语义判断中，不能仅凭模型分数宣称准确率。
- 没有独立标注基准时，语义聚类 Precision/Recall 只能作为待建立指标，不能伪造结果。

### 7.3 历史回测

采用：

- 30 天回测。
- 90 天回测。
- 更长期数据积累后的季度回测。

同一历史样本必须记录：

- 原始文章版本。
- 原始事件。
- 模型版本。
- Prompt 版本。
- Schema 版本。
- 规则版本。
- 数据集版本。
- 最终评估结果。

测试集与调参集分离。

不得在同一测试集上反复调参后，将结果称为独立验证。

### 7.4 版本对比

每次修改模型、Prompt、评分或聚类规则时：

- 使用同一批冻结样本。
- 比较新旧版本。
- 记录新增通过项。
- 记录新增失败项。
- 记录回归错误。
- 记录运行耗时变化。
- 记录证据质量变化。

不允许仅根据总体分数提高就判定升级成功。

关键错误率不得恶化。

## 8. 统计与经济数据分析标准

R5 建立独立的数据引擎。

数据源优先：

- Eurostat。
- ONS。
- BEA。
- BLS。
- FRED。
- IMF。
- OECD。
- World Bank。
- 中国国家统计局。
- 中国人民银行。
- EIA。
- 其他许可明确的官方数据源。

每个 Dataset 必须登记：

- dataset_id。
- provider。
- indicator。
- definition。
- unit。
- frequency。
- geography。
- seasonal_adjustment。
- base_period。
- denominator。
- release_date。
- observation_period。
- revision_policy。
- license_status。

建立 dataset_observations 历史快照。

修订数据不能覆盖历史值。

统计计算包括：

- YoY。
- MoM。
- QoQ。
- Moving Average。
- Index Change。
- Percentage Point Change。
- Rolling Volatility。
- Historical Range。
- Outlier Detection。

所有计算都必须保留原始输入、公式、单位和时间范围。

不应把单个指标的变化直接推断成整个经济体或产业的变化。

预测模型不是当前优先事项。

先建立可靠的历史数据、口径一致性和可复现计算。

## 9. 事件与研究报告体系

保留：

Daily Brief
Weekly Intelligence
Monthly Research

### Daily Brief

主要回答：

今天发生了什么重要变化？

包括：

- Executive Summary。
- Economy & Business。
- Business Opportunities。
- Technology & Engineering。
- What to Watch。
- Evidence & Sources。
- System Notes。

### Weekly Intelligence

主要回答：

过去一周哪些事件发生了变化？这些变化之间是否存在联系？

从 events、claims、evidence 和 dataset_observations 重新生成，不允许简单拼接日报。

### Monthly Research

围绕明确研究问题组织：

Research Question
→ Hypothesis
→ Evidence Collection
→ Data Analysis
→ Counter-evidence
→ Findings
→ Limitations
→ Conclusion

没有足够证据时不强制生成月度报告。

## 10. 开发阶段与实施顺序

### S0：来源覆盖与接入审计（当前阶段，只读）

目标：解决项目过度依赖 RSS、信息源覆盖不足的问题。

边界：只做只读审计、技术调研和实施设计；不修改生产代码、不安装依赖、不改变数据库结构、不影响现有生产任务、不接入未经许可确认的数据源、不自动开通付费服务。

任务：

1. 现有系统审计：全部 RSS 来源及分类；每个来源过去 30 天实际采集量、新增文章、有效文章、去重后事件数；来源间转载关系；A/B/C 通道覆盖；现有 API/RSS/网页采集能力与限制；SQLite 表结构与采集接口。
   所有统计必须来自实际数据库和代码，不得凭空估计。
2. 候选来源调研，按四类分别核验 API 文档、认证、配额、历史数据、许可、更新频率与商业使用限制：
   - A 官方统计、政策、监管与企业文件：Eurostat、BEA、BLS、FRED、World Bank、IMF、SEC EDGAR。
   - B 全球新闻与事件发现：GDELT 公共接口、GDELT Cloud API、Event Registry、NewsAPI。
     必须区分免费公共接口、付费产品与开发测试套餐；不得把仅允许开发测试的免费套餐当作生产方案。
   - C 学术与技术信息：OpenAlex、Crossref、arXiv、GitHub REST API、标准组织与行业协会公开资料。
   - D 研究机构与专业媒体：McKinsey、Deloitte、PwC、EY、KPMG、The Economist、FT、Reuters、AP、Bloomberg、WSJ。
     优先寻找官方 RSS、公开 API、报告索引与公开下载页面；不得假设存在免费 API，不得绕过登录、付费墙或访问限制。
3. 技术栈评估（httpx、tenacity、feedparser、trafilatura、Scrapy、Playwright、DuckDB、scikit-learn TimeSeriesSplit、Promptfoo、Evidently、Pandera、pytest）：逐项说明解决的问题、是否适合本仓库、与现有技术是否重复、依赖与维护成本、是否需要引入、建议引入阶段。不得为了使用框架而使用框架。
4. 来源治理设计：统一候选来源清单字段（source_id、source_type、source_category、target_lanes、access_method、api_documentation、terms_url、license_type、rate_limit、api_cost、historical_availability、content_storage_policy、redistribution_policy、commercial_use、retrieval_method、implementation_complexity、priority、review_status），并设计转载、通讯社共用稿、同一企业新闻稿重复传播的来源谱系识别方案。
5. 量化评估设计：Source Coverage、Retrieval Success Rate、Unique Event Yield、Independent Evidence Yield、Primary Source Coverage、Source Cost per Useful Event、Historical Availability、License Compliance。每项说明数据来源、计算方式、统计周期与限制；不得把文章数量等同于独立证据数量，不得依赖每日人工标注。
6. 来源价值评估：对每个候选来源分别评估 Coverage（覆盖的信息领域与通道）、Signal Yield（在当前频率下可持续产出的独立事件）、Evidence Value（能否提供原始数据、原始公告或可定位证据）。三项独立记录，不得用抓取成功率或文章数量替代；R1 完成前 Signal Yield 只能给出代理值，必须标注 proxy。
7. 环境约束：后续 Python 依赖统一由项目内 uv 环境管理（`.venv`、`pyproject.toml`、`uv.lock`、`uv run`）；不允许全局 pip install，不允许污染系统 Python 或其他项目虚拟环境。Python 版本约束、uv 版本、依赖锁文件、虚拟环境与缓存目录是五个独立对象；`UV_CACHE_DIR` 是进程环境变量，uv 不读取项目 `.env`，必须在 shell / 计划任务 / CI 中显式设置。本阶段只设计依赖清单，不执行安装。
8. 交付：来源覆盖审计报告、A/B/C 缺口分析、候选 API 与来源比较表、来源价值评分表、许可/成本/合法性风险清单、推荐与不推荐技术栈、Source Connector 架构设计、量化验收指标定义、分批接入顺序与复杂度依赖、下一阶段实施计划。

验收区分四类结论：已验证事实、官方文档明确说明的能力、尚未验证的推测、需要用户批准的决策。

顺序说明：先完成设计一致性修订与 S0 只读审计，再冻结 R0 设计，经批准后实施 R0；**R0 仍是第一个代码实施阶段**，S0 完成不等于获得实施授权。每个阶段必须产生可独立使用的产品价值，不得以"为下一阶段做准备"作为完成标准。

### R0：运行可靠性与发布门禁

状态：设计草案，待 S0 结论后冻结（G2）；冻结前不实施。

优先级：最高。

解决 2026-11-01 模型传输故障导致错误发布的问题。

要求：

- 有限退避重试。
- 模型健康检查。
- 熔断。
- 运行级失败率门禁。
- 最低成功覆盖要求。
- 全失败 HOLD。
- 部分失败限制性发布。
- 故障分类和记录。
- 故障注入测试。

验收：

- 模型不可用时不发送正常日报。
- 模型中途断开时不持续撞连接。
- 全部分析失败时进入 HOLD。
- 无有效信号但运行完整成功时允许正常报告。
- 正常路径不回归。
- 所有失败均可追溯。

### R1：Event / Claim / Evidence

建立：

- events。
- event_articles。
- evidences（稳定证据 ID、引文、定位、来源族、独立性）。
- claims（含币种、地区、分母、季调、修订状态等核验所需字段）。
- claim_evidence。
- event_corrections。

优先利用已有 analysis_sections 中可定位的 fact 进行回填。

不伪造旧数据中不存在的 Claim。

来源独立性字段加入来源登记。

优先确定性聚类，不引入额外逐篇 LLM 调用。

验收：

- ONS 等同一事件可以正确聚合。
- 无关事件不会错误合并。
- 重复运行不产生重复事件。
- 引文定位可以回溯。
- 旧日报和旧分析记录不被破坏。

### R2：Evidence Verification

建立 verify.py。

实现：

- 主体比对。
- 指标比对。
- 数值核验。
- 单位转换。
- 时间范围核验。
- 同比、环比和百分点口径核验。
- 引文支持关系。
- 来源独立性检查。
- 冲突证据识别。

提示词升级为新的结构化 Claim 契约。

不能验证的 Claim 不得作为已验证事实发布。

### R3：Editorial Intelligence

将现有评分拆分：

- Signal Score。
- Evidence Score。
- Editorial Priority。

增加 P0–P3 / REJECT。

处理：

- 政策事件分类问题。
- 重要性和证据质量分离。
- 来源配额和编辑排序分离。
- 跨期待办。
- 事件新颖性。
- 反面证据。
- What to Watch。

信源结构调整与本阶段并行开展。

不得要求人工标签作为验收前提。

### R4：Multi-period Publication

实现：

- Weekly Intelligence。
- Monthly Research。
- 历史事件时间线。
- 跨期比较。
- 研究问题组织。
- 反面证据。
- 数据和图表引用。

日报与周报不得简单重复同一事件。

### R5：Economic Data Engine

实现：

- Dataset 注册。
- 历史观察值存储。
- 修订快照。
- 统计口径标准化。
- 同比、环比和移动平均。
- 异常变化检测。
- 图表和事件关联。
- 数据来源追溯。

先从已批准的数据集开始，不为了数量扩展数据源。

### R6：Automated Quality & Backtesting

实现：

- Benchmark Corpus。
- 自动化回归。
- 30/90 天历史回测。
- 模型版本对比。
- Prompt 版本对比。
- 来源健康度。
- 来源独立性统计。
- 失败率。
- 证据通过率。
- 发布质量报告。

不要求日常人工标签。

不能获得真实测量值的指标，明确标注为 NOT_MEASURED，而不是使用模型自评填充。

## 11. 明确禁止的做法

1. 不允许把模型自评当作独立事实验证。
2. 不允许把多篇转载当作独立交叉验证。
3. 不允许用简单数字集合匹配代替数值语义核验。
4. 不允许用数字密度作为所有通道的硬过滤条件。
5. 不允许把咨询报告预测当作实际发生的事实。
6. 不允许把论文、开源项目和商业部署混为一谈。
7. 不允许未经证实的因果关系进入事实结论。
8. 不允许以每日内容数量作为质量目标。
9. 不要求用户承担日常人工标签和新闻编辑工作。
10. 不允许在没有真实基准数据时宣称系统达到某个准确率。
11. 不允许因为来源权威就跳过证据核验。
12. 不允许为追求自动化而取消重大错误的发布保护。

技术栈继续保持：

- Python 标准库优先。
- SQLite。
- FreshRSS。
- llama.cpp。
- Windows Task Scheduler。

暂不引入向量数据库、复杂任务编排、重型数据处理框架或多模型级联。

只有在实际基准测试证明现有方案不足时，才提出依赖变更。

## 12. 每阶段执行协议

每个阶段都必须：

1. 读取 CLAUDE.md 和相关指导文件。
2. 审计实际代码、数据库和测试。
3. 说明现有能力和缺失能力。
4. 设计最小兼容改造。
5. 明确数据库迁移和数据保护策略。
6. 给出文件级修改清单。
7. 给出确定性测试和故障测试。
8. 实际执行测试。
9. 执行端到端验证。
10. 更新必要文档。
11. 提交独立 Git commit。
12. 输出实际结果、未解决问题和下一阶段建议。

每个阶段的验收以其可独立使用的产品价值为准，不得以"为后续阶段做好准备"代替。

必须区分：

- 设计完成。
- 代码实现。
- 测试通过。
- 数据迁移完成。
- 真实运行通过。
- 生产发布成功。

不得把其中任何一项代替其他项目。

---

# 13. 当前执行指令

当前阶段：**R1 统一事件模型已分批交付并部署；R2 未开始。**

已完成并部署：

- S0 来源覆盖审计（P0 冻结）；SEC/EIA 接入设计（G-D1）。
- G-D2 第一阶段：SEC/EIA 独立摄取通道，10/10 验收通过，代码已提交。
- R0 运行可靠性与发布门禁（G2/G3）：重试、熔断、覆盖率分级、HOLD 隔离；真实模型故障注入验证通过。
- Windows 调度器修复：电源设置、启动器退出记录。
- R1 Batch 1–3：Event/Evidence/Claim 统一模型、实体与候选关联、来源谱系；已回填并部署到两个数据库。
- R1 Batch 4：日报按事件展示（同事件合并、来源族与佐证状态、候选关联标注）。

下一步的批准门：

| 门 | 内容 | 状态 |
|---|---|---|
| G5 | 来源批次接入（S1） | 待批准 |
| G6 | R2 核验规则与提示词版本 | 待批准 |
| G7 | R3 优先级体系与配额策略 | 待批准 |
| G8 | R4/R5/R6 启动 | 待批准 |

执行边界：

1. 不擅自启动下一阶段，不以"为后续铺路"作为阶段完成的理由。
2. 每阶段独立 commit；不 amend 已推送的提交；不把未批准的工作区改动混入提交。
3. 已确认的隔离边界继续有效：SEC/EIA 数据不进入 RSS 业务表、不进入 LLM 分析与日报；
   两库共享事件模型契约但物理分离。
4. 评分权重、证据门槛、发布门禁的语义不因新阶段而改变；修改需要单独批准。
5. 不把未核实的关系标成已确认：候选关联保持 `candidate`，未知来源保持 `unknown`。

当前状态与缺口见 `docs/PROJECT_STATUS.md`；各批次的验收与部署记录见 `docs/R1_BATCH*_ACCEPTANCE_2026-11-01.md`。

---

# 附录 A：实现锚点

审计与实现活动中的定位信息，不作为验收结论；具体数字以 `docs/PROJECT_STATUS.md` 为准。

- 入口：`opportunity_radar/cli.py`（抓取 → 分析 → 评分 → 事件归并 → 门禁 → 报告 → 邮件）；
  `unified_main.py`（R1 回填与报告）；`ingest/sec_main.py`、`ingest/eia_main.py`（独立摄取）。
- 存储：`store.py`（生产库与 R1 基础表）、`unified.py`（R1 表与记录构造）、`linking.py`（实体、
  提及、候选关联、证据画像）、`lineage.py`（来源谱系）、`ingest/store.py`（摄取库）。
- 契约：`schema.py` v5（facts/inferences/gaps/actions，逐字引文 + 定位）、`evidence.py`（E0–E2）、
  `scoring.py` v5 + `config/scoring.toml`、`publication.py`（覆盖率与发布状态）。
- 治理：`config/sources.csv`（模板，全部禁用）、`config/sources.local.csv`（本机登记）、
  `config/source_lineage.csv`（来源谱系）、`source_audit.py`、`source_policy.py`。
- 运行：`deploy/windows/{install-task,run-digest,start-model,start-admin,test-digest}.ps1`；
  计划任务 `OpportunityRadarDaily`（每日 08:00，Interactive，电源设置显式放开）。
- 验收：`tools/e2e_verify.py`（schema/server/reset/refuse 四种故障注入）；
  `acceptance.py`；`tests/`（642 项）。
- 文档：本文件、`docs/PRD.md`、`docs/IMPLEMENTATION_PLAN.md`、`docs/PROJECT_STATUS.md`、
  `docs/OPEN_ISSUES.md`、`docs/R1_BATCH*_ACCEPTANCE_2026-11-01.md`、`docs/archive/`（冻结）。


# 附录 B：前版方向文档的保留条目与冲突处理

前版（2026-11-01 上午）已由本文件取代，以下为**仍然有效**的设计规格，供 R1–R4 实施时使用。
与之冲突时以本文件正文为准。

## B.1 已被本版取代的条目

| 前版内容 | 本版处理 |
|---|---|
| 第一阶段直接做 R1 | 插入 R0，见 §10、§13 |
| R3 验收依赖"历史人工标签计算误报率/命中率" | 取消；改为自动基准与 NOT_MEASURED 标注，见 §4、§7 |
| R6 以"人工复核命中率"为指标 | 改为 Benchmark Corpus + 自动化回测，见 §7 |
| 来源只按登记表治理 | 增加 L0–L5 分层与来源独立性字段集，见 §6、§5 Q2 |
| 无统一质量层 | 增加 Q1–Q5，见 §5 |
| 无固定评估样本 | 增加 Benchmark Corpus 与 14 项指标，见 §7 |

## B.2 三条通道的交付字段（继续有效）

A 通道每条内容固定包含：

| 字段 | 要求 |
|---|---|
| Headline | 一句话结论 |
| What happened | 事实及时间 |
| Why it matters | 重要性 |
| Evidence | 数据和原始来源 |
| Industry impact | 产业影响 |
| What to watch | 后续观察指标 |
| Confidence | 判断置信程度 |

B 通道按商业机会证据链组织：

| 维度 | 需要回答的问题 |
|---|---|
| Problem | 谁遇到了什么问题？ |
| Buyer | 谁真正需要解决这个问题？ |
| Payment | 是否存在真实付费证据？ |
| Existing solutions | 目前有哪些解决方案？ |
| Market gap | 现有解决方案有什么不足？ |
| Delivery | 是否存在可实现的交付方式？ |
| Validation | 有什么独立证据支持需求存在？ |

C 通道字段：

| 字段 | 作用 |
|---|---|
| Technology | 涉及什么技术 |
| Development | 具体进展 |
| Evidence | 论文、代码、实验、产品发布 |
| Maturity | 技术成熟度 |
| Reproducibility | 是否可以复现 |
| Commercial relevance | 商业意义 |
| Engineering relevance | 工程应用意义 |

A 通道需区分：已确认事实、来源提出的解释、系统自己的分析假设、尚未验证的预测。

## B.3 Claim 字段设计示意

仅为字段设计示意，不是最终 schema；币种、地区、分母、季调与修订状态在 R1 即入库，R2 负责核验判定（§5 Q3）。

```json
{
  "claim_id": "C001",
  "subject": "某企业",
  "predicate": "revenue_growth",
  "value": 5,
  "unit": "%",
  "period": "2026-Q3",
  "comparison": "year_over_year",
  "evidence_id": "E001",
  "source_location": {"type": "excerpt", "start": 120, "end": 180}
}
```

核验逐项检查：主体、指标、数值、单位、时间范围、同比/环比/百分点口径、原文是否真正支持该主张。
不通过者不得作为已核验事实发布。

## B.4 产品形态（继续有效）

1. Intelligence Brief：每日自动化，回答"今天发生了什么变化"。
2. Research Intelligence：每周、每月，回答"这些变化背后的趋势、因果假设、数据证据和产业影响"。
3. Opportunity Database：长期积累商业需求、买方、付费证据、市场缺口与可验证项目。

三者分工：日报发现信号，研究系统理解变化，机会数据库沉淀可行动信息。

## B.5 专业领域优势（继续有效）

长期可形成两层：通用情报层（全球经济、企业、政策、科技）与专业研究层（制造业、汽车、工程软件、工业 AI、CAE）。
不把系统局限在汽车行业，但让专业研究成为区别于普通新闻聚合器的竞争力。

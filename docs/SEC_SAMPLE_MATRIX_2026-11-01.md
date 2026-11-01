# SEC EDGAR 10 家公司样本矩阵（实施前条件 1）

日期：2026-11-01
状态：**只读样本调查，未接入、未写连接器、未改数据库**
用途：验证 SEC EDGAR 在收入与资本开支上的覆盖边界、标签差异、修订与期间问题
证据文件：`data/sec-sample-2026-11-01/`（本地证据，gitignored）

---

## 1. 方法

| 项 | 内容 |
|---|---|
| 数据源 | `data.sec.gov` companyconcept / submissions；`company_tickers.json` |
| 认证 | 无 API key；声明 User-Agent |
| 速率 | 客户端 ≤5 请求/秒（官方上限 10） |
| 取样日期 | 2026-11-01 |
| 样本 | 10 家公司，覆盖科技、软件、半导体、银行、能源、汽车、工业、消费、医疗、海外发行人 |
| 标签集合 | 收入 5 个候选标签；资本开支 5 个候选标签；IFRS 3 个候选标签（仅 TSM） |
| 限定 | 只做只读查询；不解析完整 10-K 文本；不实现自定义 XBRL |
| 修订计数范围 | `submissions.recent` 的最近申报列表，不等于全历史；更早修订需另行检查 |

候选标签：

- 收入：`Revenues`、`RevenueFromContractWithCustomerExcludingAssessedTax`、`SalesRevenueNet`、
  `RevenuesNetOfInterestExpense`、`InterestAndDividendIncomeOperating`
- 资本开支：`PaymentsToAcquirePropertyPlantAndEquipment`、`PaymentsToAcquireProductiveAssets`、
  `PaymentsForCapitalImprovements`、`PaymentsToAcquireOilAndGasProperty`、
  `PaymentsToExploreAndDevelopOilAndGasProperties`
- IFRS：`Revenue`、`RevenueFromContractsWithCustomers`、
  `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`

---

## 2. 样本矩阵

| 公司 | CIK | 报表 | 最新收入标签 | 最新资本开支标签 | 单位 | 近期修订/比较数据 | 结论 |
|---|---|---|---|---|---|---|---|
| Apple | 0000320193 | 10-K / 10-Q | `RevenueFromContractWithCustomerExcludingAssessedTax`（117 条） | `PaymentsToAcquirePropertyPlantAndEquipment`（105 条） | USD | 0 个 /A；同一期间多 accession | 收入、资本开支均支持 |
| Microsoft | 0000789019 | 10-K / 10-Q | `RevenueFromContractWithCustomerExcludingAssessedTax`（136 条） | `PaymentsToAcquirePropertyPlantAndEquipment`（232 条） | USD | 0 个 /A | 均支持 |
| NVIDIA | 0001045810 | 10-K / 10-Q | `Revenues`（280 条） | `PaymentsToAcquireProductiveAssets`（35 条） | USD | 0 个 /A | 均支持；资本开支标签与其他公司不同 |
| JPMorgan | 0000019617 | 10-K / 10-Q | `RevenuesNetOfInterestExpense`（149 条） | **未找到** | USD | 0 个 /A | 收入支持（银行口径）；资本开支 `unsupported` |
| ExxonMobil | 0002115436 | 10-Q（近期） | `Revenues`（仅 4 条） | `PaymentsToAcquirePropertyPlantAndEquipment`（仅 2 条） | USD | 无 10-K | **身份需人工确认**；近期数据稀疏，资本开支 `requires_filing_parse` |
| Tesla | 0001318605 | 10-K / 10-Q | `Revenues`（286 条）与 `RevenueFromContractWithCustomerExcludingAssessedTax`（49 条）并存 | `PaymentsToAcquirePropertyPlantAndEquipment`（142 条） | USD | **5 个 10-K/A**；原始概念含 11 条修订行 | 均支持；必须处理修订与双标签 |
| Caterpillar | 0000018230 | 10-K / 10-Q | `Revenues`（345 条） | `PaymentsToAcquirePropertyPlantAndEquipment`（58 条） | USD | 0 个 /A | 均支持；历史标签发生迁移 |
| Coca-Cola | 0000021344 | 10-K / 10-Q | `Revenues`（114 条） | `PaymentsToAcquirePropertyPlantAndEquipment`（173 条） | USD | **1 个 10-Q/A** | 均支持；含正式修订样本 |
| UnitedHealth | 0000731766 | 10-K / 10-Q | `Revenues`（268 条） | `PaymentsToAcquirePropertyPlantAndEquipment`（154 条） | USD | 0 个 /A | 均支持 |
| TSMC | 0001046179 | 20-F | `ifrs-full:Revenue`（35 条） | `ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`（35 条） | TWD；USD | 12 个 20-F，无季度 | **仅年度**；最新 2024-12-31；无 10-Q |

覆盖统计：

- 收入：10/10 找到可用标签（ExxonMobil 仅 4 条，需人工确认 CIK 与口径）。
- 资本开支：8/10 找到可用标签；JPMorgan 没有；ExxonMobil 仅 2 条。
- 正式修订样本：Tesla（10-K/A）、Coca-Cola（10-Q/A）。
- 非美国发行人：TSMC（20-F、IFRS、TWD/USD、仅年度）。

---

## 3. 关键发现

### 3.1 收入标签随时间迁移，且公司间不一致

- Apple、Microsoft、Caterpillar 历史上使用 `SalesRevenueNet` 或 `Revenues`，近年改为
  `RevenueFromContractWithCustomerExcludingAssessedTax`。
- NVIDIA 近年使用 `Revenues`；Tesla 同时存在 `Revenues` 与
  `RevenueFromContractWithCustomerExcludingAssessedTax`。
- JPMorgan 使用银行口径 `RevenuesNetOfInterestExpense`。
- 结论：不能为"收入"指定单一标签；必须维护**按公司、按期间**的标签映射，并记录选择理由。

### 3.2 资本开支标签同样不一致

- 多数公司使用 `PaymentsToAcquirePropertyPlantAndEquipment`。
- NVIDIA 使用 `PaymentsToAcquireProductiveAssets`。
- JPMorgan 未找到资本开支概念；银行的投资现金流结构不同。
- ExxonMobil 仅 2 条，且近期的公司身份发生变化（见 3.3）。
- 结论：资本开支的覆盖率低于收入；缺失时标 `unsupported` 或 `requires_filing_parse`，不填 0。

### 3.3 ticker → CIK 不是稳定身份

`company_tickers.json` 当前把 `XOM` 映射到 **ExxonMobil Holdings Corp（CIK 0002115436）**，
近期只有 1 个 10-Q、无 10-K。这个 CIK 与传统 Exxon Mobil 的历史 CIK 不同；ticker 可以指向新的控股实体。
结论：主体以 CIK 为准，并需要人工确认公司重组/更名；不能只用 ticker 做历史序列拼接。

### 3.4 外国发行人只提供年度数据

TSMC 使用 20-F、IFRS taxonomy、TWD/USD 两种单位，最新期间 2024-12-31，没有 10-Q。
结论：美国上市公司与外国发行人的频率、单位、报表体系不同；不能混成一张季度面板。

### 3.5 修订申报与后续比较数据真实存在

- Tesla：5 个 10-K/A；原始概念数据中包含 11 条 `/A` 行。
- Coca-Cola：1 个 10-Q/A。
- 同一 `(start, end)` 在多个 accession 中重复：Apple 46/44 组、Tesla 102 组、NVIDIA 103 组，最多 4 个版本。
- 结论：必须区分 `filing_relation` 与 `selection_status`；不能用单一 `status` 或"最新 filed"简单覆盖历史。
- 注意：修订计数来自最近申报列表；更早的修订（如 Tesla 2012 年的 10-K/A）只在原始概念数据中出现，
  说明"近期 0 个 /A"不能理解为"从未修订"。

### 3.6 `fp` 不能判断季度，期间长度才可以

Apple、Tesla、NVIDIA 的 Q2/Q3 数据中同时存在：

- 约 90 天的单季度值；
- 约 181/272 天的年初至今（YTD）值。

同一 `fp=Q2` 下两种 duration 并存。结论：YTD 派生必须按 §3.4 的六个条件，用 `start`/`end` 与财年判断，
不能只看 `fp`。

### 3.7 Company Facts 的覆盖边界得到验证

- 未找到 JPMorgan 的资本开支，ExxonMobil 数据稀疏；这符合"Company Facts 只聚合标准 taxonomy、
  适用于整个申报主体的事实"的边界。
- 本轮没有解析自定义 taxonomy 或维度化事实；这些数据不在 Company Facts/Concept 的覆盖内。
- 结论：需要的指标若不在标准标签中，必须标 `requires_filing_parse`，不能当作缺失或 0。

### 3.8 单位与报表体系

- 美国公司均为 USD；TSMC 为 TWD 与 USD 双单位。
- IFRS 与 us-gaap 标签不同；不能跨 taxonomy 直接比较。
- 结论：单位与 taxonomy 必须随记录保存；换算只在展示层。

---

## 4. 覆盖结论

| 指标 | 支持 | 部分支持/不支持 | 处理 |
|---|---|---|---|
| 收入 | 9 家明确支持；TSMC 支持（年度） | ExxonMobil 身份与口径待确认 | 按公司映射标签；ExxonMobil 人工确认 |
| 资本开支 | 8 家支持 | JPMorgan 无；ExxonMobil 稀疏 | JPMorgan `unsupported`；ExxonMobil `requires_filing_parse` |
| 季度序列 | 9 家（美国公司） | TSMC 无季度 | 外国发行人只做年度 |
| 修订处理 | Tesla、Coca-Cola 有样本 | 其余公司可能仍有后续比较数据 | 全量启用 `filing_relation` + `selection_status` |
| YTD 派生 | 已验证 Q2/Q3 混合 duration | — | 仅在六个条件满足时派生 |

---

## 5. 对设计文档的反馈

1. §3.4 的标签映射规则是必要的，且需要"按公司 + 按期间"维护，不是一张全局表。
2. §3.4 规则 4（YTD）与规则 5（修订/选择状态）得到样本支持。
3. §3.4 规则 9（Company Facts 覆盖边界）得到样本支持。
4. §9.1 的验收标准需要把"收入 9/10、资本开支 8/10"作为现实基线，而不是要求 10/10。
5. §10 实施条件 1（10 家公司样本矩阵与标签映射初版）**已完成**；标签映射的正式版本仍需在实施设计中固化。

---

## 6. 未解决

| 编号 | 问题 | 下一步 |
|---|---|---|
| S-1 | ExxonMobil 当前 CIK 与传统实体不同 | 人工确认重组关系；历史序列按 CIK 分段 |
| S-2 | JPMorgan 资本开支标签未知 | 查其投资现金流标签或标 `unsupported` |
| S-3 | 自定义 taxonomy 与维度化事实未覆盖 | 需要时另做 filing 解析，不在本阶段 |
| S-4 | 其他 90 家公司的标签分布未知 | 扩大到更大样本再定映射表 |
| S-5 | 修订/比较数据的完整分布未统计 | 在实施设计中按 `filing_relation` 统计 |

---

## 7. 下一步

实施前条件 1 已完成。条件 2（EIA API key 与真实请求/响应样本）仍待执行；
条件 3–5 需在条件 1、2 之后再展开。未接入任何来源，未改数据库或业务代码。

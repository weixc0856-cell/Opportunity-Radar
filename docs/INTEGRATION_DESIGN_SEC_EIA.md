# SEC EDGAR + EIA 接入设计评审

版本：0.8（修订稿）
日期：2026-11-01
状态：**G-D1 设计评审通过（2026-11-01）；G-D2 已批准 SEC/EIA 独立通道第一阶段实施（2026-11-01）。**
授权记录：`docs/IMPLEMENTATION_AUTHORIZATION_2026-11-01.md`（编号 G-D2）
前提：P0 来源调查已冻结并通过（`docs/S0_SOURCE_COVERAGE_AUDIT.md` §7）
范围：仅 SEC EDGAR 与 EIA 两个来源；Ember 不进入本阶段
阶段边界：**本文件仍是设计文档。** 实施范围与禁令以 G-D2 授权记录为准；第一阶段仅含数据获取、规范化、存储与质量验证，不接入现有 LLM/评分/日报，不启动 R0。

---

## 0. 本阶段要回答的问题

本文件对应 P0 之后的第一步，只产出接入设计，不产出实现。需要回答：

1. 两个来源各自的最小数据契约是什么？
2. API 请求与响应样本是什么样？
3. 字段如何映射，数据质量规则是什么？
4. 失败、限流、修订如何处理？
5. 权利边界与运行成本是什么？
6. 独立的验收标准与实施前审批条件是什么？

明确不做：

- 不设计最终数据库 schema；本文件只定义逻辑契约。
- 不写 connector、不改 `opportunity_radar/` 代码、不新增依赖。
- 不把 Ember 纳入本阶段；Ember 的方法论与来源独立性仍未核实。
- 不因为设计完成就视为批准实施。

---

## 1. 两个来源的角色

| 来源 | 角色 | 在证据链中的位置 | 本阶段用途 |
|---|---|---|---|
| SEC EDGAR | 一手披露 | 企业原始申报与 XBRL 财务数据 | 为公司经营、资本开支、收入提供结构化原始数据 |
| EIA | 官方统计 | 美国能源生产、消费、价格、发电与排放 | 为能源与电力提供可追溯的时间序列 |

两者都不直接证明商业机会；它们提供的是**可核验的事实底座**。模型推断与编辑判断仍由后续阶段负责。

---

## 2. 最小数据契约（逻辑层，不是数据库 schema）

### 2.1 通用字段

| 字段 | 含义 | 要求 |
|---|---|---|
| `source_id` | 来源标识 | `sec-edgar` / `eia` |
| `record_type` | 记录类型 | `filing` / `fact` / `series_meta` / `observation` |
| `external_id` | 来源内稳定 ID | CIK+accession / series_id+period |
| `entity_id` | 主体 | CIK（SEC）；地理/行业（EIA） |
| `metric_id` | 指标 | taxonomy+tag（SEC）；series_id（EIA） |
| `period_start` / `period_end` | 期间 | 明确 instant 或 duration |
| `frequency` | 频率 | annual / quarterly / monthly / instant |
| `value_num` / `value_text` | 值 | 数值与文本分开；缺失用 null，不填 0 |
| `unit` | 单位 | 原始单位，不在此层换算 |
| `status` | 来源特定状态 | EIA：`preliminary` / `final` / `unknown`；SEC 不使用单一 status，改用 `filing_relation` / `selection_status`（§3.4） |
| `published_at` / `filed_at` | 发布/申报时间 | 来源提供的时间 |
| `retrieved_at` | 抓取时间 | 本系统时间 |
| `source_url` | 原始链接 | 可回溯 |
| `raw_ref` | 原始记录引用 | 快照哈希或原始文件位置 |
| `quality_flags` | 质量标记 | 缺失、修订、单位换算、YTD 派生等 |

### 2.2 SEC 记录

- `filing`：accession number、form（10-K/10-Q/8-K/20-F）、filed date、period of report；并记录 `filing_relation` 与 `selection_status`。
- `fact`：taxonomy（us-gaap）、tag、label、unit、start/end、val、accn、fy、fp、form、filed、frame。
- 主体以 CIK 为准，ticker 只是别名；公司名称不作主键。

### 2.3 EIA 记录

- `series_meta`：series_id、名称、频率、地理、单位、数据集、起始年份、修订策略。
- `observation`：series_id、period、value、unit、release_date、status（preliminary/final）、dataset version。
- 地理与统计对象必须随记录保存，不能从名称推断。

---

## 3. SEC EDGAR 设计

### 3.1 访问方式（已核验）

| 项 | 内容 |
|---|---|
| 端点 | `data.sec.gov` REST JSON：`submissions/CIK##########.json`、`api/xbrl/companyconcept/...`、`api/xbrl/companyfacts/...` |
| 批量 | `companyfacts.zip`、`submissions.zip`，每晚约 03:00 ET 更新 |
| 认证 | 无需 API key |
| 频率限制 | 官方上限 10 请求/秒；**系统目标 ≤5 请求/秒**，为突发与其他任务留余量 |
| User-Agent | 必须声明，包含机构与联系方式 |
| 公司映射 | `https://www.sec.gov/files/company_tickers.json`（ticker → CIK） |

### 3.2 请求与响应样本（已取样）

`companyconcept` 响应包含：`cik`、`taxonomy`、`tag`、`label`、`description`、`entityName`、`units.USD[]`；
每条观测包含 `start`、`end`、`val`、`accn`、`fy`、`fp`、`form`、`filed`，部分含 `frame`。

NVIDIA（CIK 1045810）`us-gaap:Revenues` 样本：

| 期间 | 值（USD） | 说明 |
|---|---|---|
| 2025-01-27 – 2026-01-25 | 215,938,000,000 | 最新年度 |
| 2026-04-27 – 2026-07-26 | 96,221,000,000 | 最新季度 |
| 2026-01-26 – 2026-07-26 | 177,837,000,000 | 年初至今（YTD） |

覆盖边界（官方说明）：Company Facts / Company Concept **不是全部 XBRL 事实的完整转储**。它们只聚合
使用非自定义 taxonomy（us-gaap、ifrs-full、dei、srt 等）且**适用于整个申报主体**的事实；
公司自定义扩展 taxonomy 与维度化（分部）事实不在其覆盖内。Frame API 的期间是日历期间（`CY####`，365±30 天等），
不是公司财年，不能替代公司实际报告期间。

### 3.3 字段映射

| 目标字段 | SEC 来源 |
|---|---|
| entity_id | CIK（10 位补零） |
| metric_id | `taxonomy:tag`，例如 `us-gaap:Revenues` |
| period | `start` / `end`；无 start 视为 instant |
| value_num | `val` |
| unit | `units` 的键（USD、shares、pure） |
| filing_relation / selection_status | 见 §3.4 规则 5；不得用单一 status 表示 |
| published_at | `filed` |
| raw_ref | accession number + 原始记录哈希 |

### 3.4 数据质量规则

1. **标签规范化**：同一指标可能有多个 us-gaap 标签（如 `Revenues` 与
   `RevenueFromContractWithCustomerExcludingAssessedTax`）。必须维护显式映射表；不得静默混用。
2. **单位**：USD、USD/shares、shares 不可混算；换算只发生在展示层，并记录规则。
3. **期间**：区分 instant 与 duration；不同长度的 duration 不可直接比较。
4. **YTD 派生**：只有同时满足以下条件，才允许 Q = YTD_n − YTD_{n−1}，并标记 `derived`、记录两个输入 accession 与值：
   (1) 同一 CIK、taxonomy/tag、unit；(2) 同一财年；(3) 两个 YTD 起始日一致；
   (4) 结束日符合连续季度关系；(5) 申报版本与比较口径兼容；(6) 公式、输入与映射版本全部留痕。
   任一条件不满足则不派生，保留原始 YTD。不同 accession、不同财年或不同口径的两个 YTD 不得直接相减。
5. **申报关系与取值状态分离**：
   - `filing_relation`：`original` / `amendment` / `subsequent_comparative` / `unknown`。
     10-K/A、10-Q/A 是 `amendment`；后续普通申报重新披露旧期间属于 `subsequent_comparative`，不得称为 amended。
   - `selection_status`：`historical` / `current_selected` / `superseded` / `unresolved`。
     历史披露值保留为 `historical`；当前视图按明确规则选择 `current_selected`；被替代的标记 `superseded`。
   - 没有 `/A` 不代表没有发生重述；不得把新 accession 一律称为 amended。
6. **重复观测**：同一 `(cik, tag, unit, start, end, accn)` 只存一条；跨申报的相同期间保留来源申报信息。
7. **缺失**：404、无该标签、空值一律记 `null` + `quality_flags`，不得填 0。
8. **比例/百分比**：`pure` 单位需明确是比例还是百分比，展示时转换。
9. **Company Facts 覆盖边界**：自定义 taxonomy 与维度化事实不在聚合范围内。需要这些数据时标记
   `requires_filing_parse`，不得当作缺失或 0；本阶段不实现自定义 XBRL 解析，但必须显式标注。

### 3.5 失败、限流与修订

- 403：检查 User-Agent；404：CIK/tag 不存在；429：退避；5xx/超时：有限重试。
- 客户端限速 ≤10 请求/秒；批量抓取优先使用 ZIP。
- 版本检测：区分正式修订（`/A`）、后续申报中的比较数据（新 accn 重述旧期间）与当前选择值；
  同一 `(cik, tag, unit, start, end)` 的新 accn 记录为新版本，不覆盖旧值。

### 3.6 权利与成本

| 权利 | 结论 | 依据 / 限制 |
|---|---|---|
| 存储 | SEC 自身提供的 API、索引与政府制作内容：允许 | 政府内容可访问与复用；企业申报保留原样 |
| 商业使用 | **仅限 SEC 创作内容**；企业申报中的第三方材料需单独判断 | 不能从"网站公开可访问"推导出所有申报内容可自由商业使用 |
| 再分发 | **仅限 SEC 创作内容**；结构化提取的使用场景需单独判断 | 同上；须遵守速率与 UA |
| 历史数据 | 申报历史可按公司获取；批量每晚更新 | 官方说明 |

说明：EDGAR 申报文件主要由企业提交，不等于 SEC 创作或拥有版权；申报中的第三方图片、图表、附件可能受保护。
"公开可访问"不等于"可自由商业再分发"。

成本：API 免费；存储与计算很小；主要维护成本是 XBRL 标签映射与修订处理。

---

## 4. EIA 设计

### 4.1 访问方式（已核验）

| 项 | 内容 |
|---|---|
| API | EIA API v2，需注册 API key（`api_key` 参数） |
| 数据范围 | 电力、油气、煤、排放、能源展望等时间序列 |
| 批量 | ZIP 文件；数据浏览器；部分 CSV/XLS |
| 频率限制 | 页面未给数值配额；以官方 ToS 为准 |
| 鉴权 | key 放环境变量，不进日志、不进仓库 |

### 4.2 数据集选择（本阶段只选一个起点）

起点：**美国电力净发电量（按能源来源，月度/年度）**。

理由：已有公开表格样本、单位与年度/月度关系已核、定义已查；其他数据集（价格、州级、油气）留待后续。

已确认（2026-11-01，真实响应）：route、facets、返回列、月度与年度查询方式，见 §4.5。
**EPM Table 1.1 是公开表格，不是 API 字段定义**；其结构不得当作 API 契约——取整后两者数值一致，但字段名称与口径以 API 返回为准。

### 4.3 数据契约

- `series_meta`：series_id、指标名、来源表（如 EPM Table 1.1）、频率、地理、单位、起始年份、修订策略。
- `observation`：series_id、period、value、unit，以及以下**逻辑目标**（不是已确认的 API 原生字段）：
  - `release_date`：API 提供时直接使用；不提供时记录本系统观察到的发布日期或数据版本，并标注来源；
  - `status`：API 提供时直接使用；不提供时依据官方发布说明判定；无法判定用 `unknown`；
  - `dataset_version`：不凭空构造；保留原始响应快照哈希与获取时间。

### 4.4 定义与口径（已核验）

1. **Net generation**：`gross generation less the electrical energy consumed at the generating station(s)`；
   抽水蓄能抽水计入厂用电并从毛发电中扣除（EIA Glossary）。
2. **月度与年度**：2016–2025 的 Annual Totals 是完整 12 个月合计；2026 只有 1–8 月 Year to Date，
   **没有 2026 年度值**。
3. **初值与终值**：**API 不返回** `release_date`、`revision`、`status`、`last_updated` 或任何 preliminary/final 字段，因此无法从数据层判断某期数值是否已最终确定。2026 年数据的状态一律记 `unknown`；2026-01…08 明确为部分年度（YTD），不生成 2026 年度值。
   "Totals may not equal sum of components because of independent rounding" 来自 EIA 公开表格说明，是展示层舍入提示，不是 API 字段，也不能用于判定初值/终值。
4. **单位**：千兆瓦时（Thousand Megawatthours）；转 TWh 需显式换算并记录。
5. **样本**：2024 年 652,156；2025 年 734,928；2026 年 8 月 70,937（千兆瓦时）。

### 4.5 请求与响应样本（已取样，2026-11-01）

EIA API key 已通过进程环境变量提供，真实请求/响应样本已取得。证据：`data/eia-sample-2026-11-01/`（本地，gitignored），
逐项判定见该目录 `validation_report.md` §10。本轮共 16 次只读请求。

**已确认（来自真实响应）**

| 项 | 实际值 |
|---|---|
| route | `/v2/electricity/electric-power-operational-data`（曾误写为 `electricity-power-operational-data`，该拼写返回 404） |
| apiVersion | 2.1.14 |
| 频率与格式 | monthly（`YYYY-MM`）、quarterly、annual（`YYYY`） |
| 期间范围 | startPeriod 2001-01；endPeriod 2026-08 |
| 查询参数 | `frequency`、`data[0]`、`facets[location][]`、`facets[sectorid][]`、`facets[fueltypeid][]`、`start`、`end`、`length`、`offset` |
| 返回字段 | 数据行：`period`、`location`、`stateDescription`、`sectorid`、`sectorDescription`、`fueltypeid`、`fuelTypeDescription`、`generation`、`generation-units`；响应层：`total`、`dateFormat`、`frequency`、`description` |
| 字段类型 | **全部为字符串**，包括 `generation` 与 `response.total` |
| 单位字段 | `generation-units` = `thousand megawatthours`（= GWh） |
| 排序 | 按 `period` 降序 |
| 分页 | 单次上限 5000 行；`length` 小于 `total` 时返回 `warnings: incomplete return`；完整性按「累计行数 == `total`」判断，**`warnings` 不是截断信号** |
| 错误结构 | 404：`{"error":"Not found.","code":404}`（`error` 为字符串）；无 key：403 `{"error":{"code":"API_KEY_MISSING",...}}`（`error` 为对象）；**无效 facet：200 + `total:"0"` 空集，不报错** |
| 对账 | 月度合计与年度端点逐位相等；2024 = 652,155.92 GWh、2025 = 734,928.49 GWh，取整后与 EPM Table 1.1 一致 |
| 2026 | 月度有 2026-01…08；annual 端点请求至 2026 只返回 2024、2025，**无 2026 年度值** |

**验证范围限定**：以上结论仅对 route `electric-power-operational-data`、指标 `generation`、facet 组合
`location=US` + `sectorid=99` + `fueltypeid=COW` 成立。

**仍未验证**：其他 route 与其他 data 字段；`ALL` / `COL` / `sectorid=98` / 州级与 Census Region 的实际行为；
API 配额与速率限制；2026 年数据的 preliminary/final 状态；最新一期发布滞后；其他数据集的修订机制；
商业使用与再分发条款。

`release_date` / `status` / `dataset_version` 在任何样本中均未出现，按 §4.3 的"API 不提供"分支处理（见 §4.4 第 3 条）。

### 4.6 失败、限流与修订

- key 缺失 → 该来源整体跳过，不降级为"无数据"。
- 429/5xx/超时 → 退避重试；失败按来源记录。
- 修订：同一 series+period 出现新 release_date/status 时保留旧值，新增版本；不覆盖。
  若 API 不提供 release_date/status，则以响应快照哈希 + `retrieved_at` 记录观察版本，不得声称这是原生修订状态。
- YTD 与年度：禁止把 YTD 当年度值；派生规则必须显式。
- 舍入：保留原始值；展示时按规则舍入并标注。

### 4.7 权利与成本

| 权利 | 结论 | 依据 / 限制 |
|---|---|---|
| API 用于开发服务 | 允许 | EIA API ToS：可用于 "develop a service to search, display, analyze, retrieve, view" 数据 |
| EIA 官方数据/信息产品 | **允许使用与分发；需注明来源与发布日期** | EIA Copyrights and Reuse Policy：美国政府作品属公共领域；EIA 允许使用和分发其数据、文件、数据库、报告、图表 |
| 商业展示（官方数据） | 在遵守署名等条件下有官方政策依据 | 公共领域 + EIA 授权使用声明；页面未单列商业条款，但不构成限制 |
| 第三方授权内容、图片、标志 | **单独处理，不得默认授权** | 私有授权材料可能受版权保护；照片需 EIA/权利人许可；EIA 标志为商标 |
| API 服务规则 | 不得暗示 EIA 背书、不得擅用标志、不得修改后仍称 EIA 数据 | API ToS |
| 修改/误述 | 不得修改后仍声称来源为 EIA | API ToS |
| 可用性 | as-is / as-available，无持续可用保证 | API ToS |
| 历史数据 | 因数据集而异（如 SEDS 自 1960） | 数据目录 |

边界：官方数据可再分发（需署名与发布日期）；第三方内容、照片与标志不在该授权范围内，未确认前不使用。
成本：API 免费，需 key；维护成本来自数据集变更与修订处理。

---

## 5. 共同数据质量规则

1. **来源可追溯**：每条记录保留 source_url 与 raw_ref。
2. **原始值优先**：换算、派生、聚合都在展示层，且带公式与标记。
3. **缺失不填零**：null + quality_flags。
4. **修订不覆盖**：保留历史版本与 release/filed 时间。
5. **单位显式**：原始单位入库；换算规则单独记录。
6. **口径随记录**：期间类型、频率、地理、统计对象与记录绑定。
7. **幂等**：同一外部 ID 重复抓取不产生重复记录。
8. **可复现**：固定 retrieved_at、规则版本与映射表版本。

---

## 6. 运行与失败处理（设计层）

- 逐来源隔离：SEC 失败不影响 EIA，反之亦然。
- 限速：SEC 官方上限 10 req/s，**系统目标 ≤5 req/s**；EIA 以官方配额为准，未知时保守。
- 熔断与重试：连续失败停止该来源本轮；记录 cause。
- 密钥：EIA key 只从环境变量读取；日志脱敏。
- 运行预算：单轮请求数与耗时上限，超限则跳过并记录。
- 失败分类：`auth` / `rate_limit` / `not_found` / `schema` / `timeout` / `server` / `rights`。

---

## 7. 权利边界汇总

| 权利 | SEC EDGAR | EIA |
|---|---|---|
| 存储 | SEC 创作内容允许；企业申报保留原样 | 允许 |
| 商业使用 | 仅限 SEC 创作内容；企业申报中的第三方材料另议 | 官方数据允许（署名）；第三方材料另议 |
| 再分发 | 仅限 SEC 创作内容 | 官方数据允许（署名与发布日期）；第三方材料另议 |
| 署名与标志 | 遵守速率与 UA | 需署名；不得暗示背书；不得使用 EIA 标志 |
| 历史数据 | 可按公司获取；批量每日更新 | 因数据集而异 |

实施前必须解决：SEC 申报中的第三方材料边界；EIA 数据集中的第三方内容（图片、附件、标志）。
官方 EIA 数据的使用与再分发已有政策依据；第三方材料未确认前不使用。

---

## 8. 成本与维护

| 项 | SEC EDGAR | EIA |
|---|---|---|
| API 费用 | 0 | 0（需 key） |
| 存储 | 小（结构化观测） | 小到中（时间序列） |
| 主要维护 | XBRL 标签映射、修订申报 | 数据集/API 版本、修订与初值终值 |
| 运行频率 | 每日或按需 | 月度/年度发布后 |

---

## 9. 独立验收标准

### 9.1 SEC EDGAR

1. **收入与资本开支分开验收**：
   - 收入：10 家公司中至少 9 家能取得年度与季度收入观测；
   - 资本开支：先建立 10 家公司的样本矩阵，记录标签、单位、期间类型与是否来自标准 taxonomy；
     对缺少标准标签或需要维度信息的公司标记 `unsupported` 或 `requires_filing_parse`，不静默填补。
2. 同一指标使用显式标签映射；映射表可审计。
3. 至少处理一份正式修订（10-K/A 或 10-Q/A）与一份"后续申报重述旧期间"的案例；
   `filing_relation` 与 `selection_status` 正确，历史不被覆盖。
4. YTD 派生满足 §3.4 规则 4 的全部六个条件，公式、输入与标记可复现。
5. 请求速率目标 ≤5 req/s（不超过官方 10 req/s），UA 合规，无 403/429 未处理。
6. 缺失值不填 0；单位不混算；自定义 taxonomy/维度化事实标 `requires_filing_parse`。
7. 原始记录可回溯（accession + URL + 哈希）。

### 9.2 EIA

1. 取得一个完整序列（至少 24 个月 + 2 个年度值），单位与期间正确。
2. 2024/2025 年度值与公开表格一致；2026 只按 YTD 处理，不生成年度值。
3. net generation 定义与厂用电扣除规则有记录。
4. 初值/终值/修订状态随观测保存；修订不覆盖历史。
5. 无 key 或 429 时整体跳过并记录，不伪造数据。
6. key 不出现在日志、报告或仓库。
7. 原始值与换算值的区别可追溯。
8. 实施前已用真实 API 样本确认 route、facets、返回列与月度/年度查询方式。
9. 若 API 不提供 release_date/status，使用观察到的发布日期与快照哈希；不得伪造原生修订状态。

### 9.3 跨来源

- SEC 与 EIA 的失败互不影响。
- 两个来源的记录都能回到原始 URL 与抓取时间。
- 不把 Ember 与 EIA 的数值接近当作独立验证。

---

## 10. 实施前审批条件

1. G-D1 已关闭（设计评审通过）；以下为**实施审批**条件，不是设计评审条件。
2. EIA 真实 API 响应样本已取得，route/facets/返回列/月度与年度查询方式确认。
3. EIA 数据集的第三方内容边界已核对；官方数据按 Copyrights and Reuse Policy 署名后使用/再分发，第三方材料未确认前不使用。
4. SEC 10 家公司样本矩阵完成：收入与资本开支分别记录，标注 unsupported / requires_filing_parse；标签映射表初版完成。
5. 样本量、失败注入与验收标准确认。
6. 明确不改变现有日报、评分与证据门槛；接入作为独立通道。

未满足以上条件，不进入实施。

---

## 11. 未解决问题

| 编号 | 问题 | 影响 | 下一步 |
|---|---|---|---|
| D-1 | EIA 官方数据与第三方材料的边界 | 官方数据可依政策使用/分发（署名）；第三方图片、附件、标志需单独处理 | 逐数据集核对第三方材料；官方数据署名后再分发，第三方未确认不使用 |
| D-2 | EIA API route/facets/返回列/月度与年度查询 | **已取样（2026-11-01）**，仅限单一 route / 单一指标 / 单一 facet 组合；其他 route、字段与地理层级仍未验证 | 见 §4.5；扩展前重新取样，不以公开表格代替 |
| D-3 | SEC 标签映射跨公司差异 + Company Facts 覆盖边界（自定义 taxonomy/维度化事实不在内） | 财务指标不可比或缺失 | 10 家公司样本矩阵；unsupported/requires_filing_parse 标记 |
| D-4 | SEC 修订与后续比较数据 | 历史被覆盖或状态误判 | filing_relation + selection_status；版本化 |
| D-5 | EIA 序列选择与修订策略 | 时间序列不一致 | 先做一个序列，再扩 |
| D-6 | 存储与运行成本（原问题：成本缺乏量化依据） | **已完成初步量化（2026-11-01）**：见 `docs/COST_QUANTIFICATION_2026-11-01.md` | 剩余事项：U1–U6 未知项与快照保留策略待后续验证或决策；处理方式见本节末说明 |
| D-7 | EIA API 若无 release_date/status，修订状态只能观察 | 可能误判修订 | 快照哈希 + 观察时间；unknown 不猜 |
| D-8 | SEC 申报文件中的第三方材料 | 再分发风险 | 仅对 SEC 创作内容做商用/再分发判断 |

> **D-6 处理方式**：实施设计阶段引用 `docs/COST_QUANTIFICATION_2026-11-01.md` 的量化结果；
> 其中的 [实测] / [估算] / [未知] 标记必须保留，**不得把估算当成实测**。
> 该条目的关闭仅指"成本已有量化依据"，不表示配额、长期存储增长或模型运行成本已经得到验证。

---

## 12. 下一步

G-D1 已关闭。下一阶段是**实施前条件准备**（§14），不是实施；实现仍需单独批准。
当前不写连接器、不改数据库、不启动 R0。

## 13. 修订记录

### v0.8（2026-11-01）

本次仅同步阶段状态：G-D1 设计评审通过、G-D2 批准独立通道第一阶段实施。
不改变任何技术决策、数据契约与实施前条件判定；条件 5 仍为 A `PASS` / B `NOT_VERIFIED` / 合并 `NOT_VERIFIED`。

| # | 修订 | 位置 |
|---|---|---|
| 18 | 状态行与阶段边界改为指向 G-D2 授权记录；条件 5-B 明确在实施阶段通过故障注入、并发与超时验证 | 文件头、§14 |

### v0.7（2026-11-01）

本次仅记录实施前条件 5 的只读审查结果与七项实施边界。
不改变设计目标与数据契约，不改变 G-D1 已关闭、设计通过、尚未批准实施的状态，也不触发实施审批。

| # | 修订 | 位置 |
|---|---|---|
| 16 | 实施前条件 5 拆为 A/B 两项：A `PASS`（只读代码审查），B `NOT_VERIFIED`；合并判定 `NOT_VERIFIED`，未登记 PASS_VERIFIED | §14 |
| 17 | 写入独立通道七项实施边界；运行隔离、并发安全、超时与故障注入明确划归实施阶段验收 | §14 |

### v0.6（2026-11-01）

本次为状态记录纠正：同步条件 3 的实际验证状态、更新 D-6 的关闭方式。
不改变设计目标、数据契约、其他实施前条件，也不扩大任何完成范围；条件 5 仍为待确认。

| # | 修订 | 位置 |
|---|---|---|
| 14 | 实施前条件 3 由"待完成"更正为 `PASS_VERIFIED — 失败注入样本集与验收规则完整性；A1–A7 连接器行为待实施阶段验证。`，并保留四条边界（25 样本逐样本通过、M1–M6 全 PASS、A1–A7 全 NOT_VERIFIED、不代表连接器或 R0 已验证） | §14 |
| 15 | D-6 改为"原问题 / 当前状态 / 剩余事项"三段式并补处理方式，不删除该条目；关闭的是"缺量化依据"，不是配额与长期成本 | §11 |

### v0.5（2026-11-01）

本次仅同步实施前条件 4 的验证状态，不改变设计目标、数据契约与其他实施前条件；条件 1–3、5 的状态不变。

| # | 修订 | 位置 |
|---|---|---|
| 13 | 实施前条件 4 更新为 `PASS_VERIFIED — 存储、请求量与运行成本量化完成；估算假设及未知项 U1–U6 见 COST_QUANTIFICATION_2026-11-01.md。`；并注明完成不等于配额、长期存储增长与模型运行成本已验证 | §14 |

### v0.4（2026-11-01）

本次仅同步 EIA 真实 API 样本验证的事实与状态，不改变设计目标、数据契约或其他实施前条件；不构成实施批准，也不构成 EIA 全面接入许可。

| # | 修订 | 位置 |
|---|---|---|
| 10 | EIA API key 与真实响应样本已取得：route、facets、返回列、字段类型、单位、分页、错误结构按实际响应同步 | §4.2、§4.5、§11 D-2 |
| 11 | 移除未经 API 字段证实的初值/终值判断，改为 `unknown` 语义；2026 年定性为部分年度，不生成年度值 | §4.4 第 3 条 |
| 12 | 实施前条件 2 更新为 `PASS_VERIFIED — 单一 route / 单一指标 / 单一 facet 组合`，同时保留未验证项 | §14 |

### v0.3（2026-11-01）

| # | 修订 | 位置 |
|---|---|---|
| 9 | 按 EIA Copyrights and Reuse Policy 精确化 D-1：官方数据属公共领域，可署名使用/再分发；第三方图片、附件、标志单独处理；商业展示对官方数据有政策依据 | §4.7、§7、§11 D-1 |

### v0.2（2026-11-01）

| # | 修订 | 位置 |
|---|---|---|
| 1 | 明确 Company Facts/Concept 只覆盖非自定义 taxonomy 且适用于整个申报主体的事实；维度化事实不在内 | §3.2、§3.4 规则 9 |
| 2 | 将 `status` 拆为 `filing_relation` 与 `selection_status`，区分正式修订与后续比较数据 | §3.3、§3.4 规则 5、§3.5 |
| 3 | 补全 YTD 派生的六个条件；不满足则保留原始 YTD | §3.4 规则 4、§9.1 |
| 4 | EIA API ToS：允许开发服务与署名；商业与再分发未明确授权，需查 Copyrights and Reuse Policy（v0.3 已按官方政策精确化） | §4.7、§7 |
| 5 | EIA 的 release_date/status/dataset_version 标为逻辑目标，未取样前不当作原生字段 | §4.3、§4.5、§4.6 |
| 6 | 收窄 SEC 权利表述：企业申报不等于 SEC 创作内容；第三方材料另议 | §3.6、§7 |
| 7 | SEC 请求目标改为 ≤5 req/s（官方上限 10） | §3.1、§6、§9.1 |
| 8 | EIA API route/facets/列/月度年度查询标为待样本确认；表格字段不等于 API 字段 | §4.2、§4.5、§10 |

## 14. 实施前条件准备（G-D1 关闭后；G-D2 已批准第一阶段实施）

| # | 条件 | 状态 |
|---|---|---|
| 1 | SEC 10 家公司样本矩阵与标签映射初版（收入/资本开支分开，标注 unsupported / requires_filing_parse） | **已完成**：`docs/SEC_SAMPLE_MATRIX_2026-11-01.md`；正式映射表待实施设计固化 |
| 2 | EIA API key 与真实请求/响应样本（route、facets、分页、字段、月度/年度查询） | **PASS_VERIFIED — 单一 route / 单一指标 / 单一 facet 组合**：`data/eia-sample-2026-11-01/validation_report.md` §10；未验证项见该报告 §10.11，不构成 EIA 全面接入许可 |
| 3 | 两个来源的失败注入与验收样本 | **PASS_VERIFIED — 失败注入样本集与验收规则完整性；A1–A7 连接器行为待实施阶段验证。**：25 个样本逐样本验收通过；M1–M6 全部 PASS；A1–A7 全部 NOT_VERIFIED。不代表连接器已经实现或通过测试，也不代表 R0 发布行为已经验证。见 `tests/validation/RESULTS_2026-11-01.md` |
| 4 | 存储、请求量与运行成本量化 | **PASS_VERIFIED — 存储、请求量与运行成本量化完成；估算假设及未知项 U1–U6 见 COST_QUANTIFICATION_2026-11-01.md。** |
| 5 | 确认接入为独立通道，不影响现有日报、评分与证据门槛 | **合并判定 NOT_VERIFIED**。A：现有 RSS → LLM → 评分 → 日报链路不依赖独立来源数据，独立表不会自动进入正常分析与日报 = `PASS`（依据只读代码审查）；B：新来源故障与现有 RSS 任务完全隔离 = `NOT_VERIFIED`（尚无独立通道实现，无运行故障测试）。七项实施边界见本节末；证据见 `docs/INDEPENDENT_CHANNEL_AUDIT_2026-11-01.md` §8。**B 项将在实施阶段通过故障注入、并发与超时验证后重新判定**，在此之前保持 `NOT_VERIFIED` |

以上条件满足后才进入实施审批；G-D1 关闭不等于实施批准。

> **条件 4 的边界**：登记为 PASS_VERIFIED 表示量化已完成，**不表示**下列任何一项已被验证——
> EIA/SEC 的实际配额与限流阈值（U1–U3）、长期存储增长（U4）、快照保留期限（U6，待决策），
> 以及模型运行成本的实际增幅（U5，取决于新来源是否进入分析路径，属待决策项）。
> `docs/COST_QUANTIFICATION_2026-11-01.md` 中的 [实测] / [估算] / [未知] 标记在后续引用时必须保留，
> **不得把估算改写为实测**。

**独立通道实施要求（条件 5，七项边界）**

1. **独立表与命名空间**：不得写入现有 `articles`、`analyses`、`analysis_history`、`analysis_sections`、`runs`。
   写入这五张表的任意一张，都会通过事件去重、多来源佐证、`--render-only` 重渲染与熔断告警四个入口影响现有链路。
2. **独立入口与独立计划任务**：自有 module `main()`，且不放在 `cli.main()` 的任何 `try` 块内。
3. **优先使用独立 SQLite 数据库文件**；若必须共用同一文件，须显式设置 `journal_mode=WAL` 与 `busy_timeout` 并验证并发写。
4. **独立配置**：不与 RSS 的 `freshrss_feed_id` 混用，`source_type` 明确区分。
5. **默认不进入现有 LLM 分析流程**：是否进入必须由显式开关控制，默认关闭。
6. **独立记录运行状态**：不写入现有 `runs` 表，避免污染 `consecutive_failures` 的熔断与告警判断。
7. **不修改 `evidence.py`、`scoring.py`、`config/scoring.toml`**，证据门槛与评分规则保持不动。

> **未完成事项**：运行隔离、并发安全、超时与故障注入属于**实施阶段验收**，不在本轮完成范围内。
> 条件 5 的 B 项（故障完全隔离）因此保持 `NOT_VERIFIED`。

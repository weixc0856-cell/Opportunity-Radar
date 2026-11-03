# Source Pilot Value Review

日期：2026-11-02
范围：Federal Register 17 条文档、BLS 9 个 series / 971 条观测、现有 RSS 126 篇文章 / 117 个事件
性质：只读评估。未重新采集，未调用 GDELT，未修改生产/Pilot 数据、代码、配置或调度。

证据标记：

- `[事实]`：直接来自当前 SQLite、run summary 或原始记录。
- `[推断]`：基于当前数据的分析判断，不是来源方的结论。
- `[假设]`：尚未验证，需要下一阶段实验。
- `[NOT_EVALUATED]`：现有数据不足，不能合理判断。

---

## 1. 评估范围与数据快照

### 1.1 Federal Register

| 项目 | 当前值 |
|---|---:|
| 文档 | 17 |
| 版本 | 17（全部 initial） |
| 机构 | 9 个 watch / 8 个机构组合；实际返回文档的机构为 FDA、FCC、DOE、Commerce、EPA |
| 类型 | RULE 5、PRORULE 4、NOTICE 8 |
| 发布日期 | 2026-10-26 至 2026-11-02 |
| 修正/更正关系 | 17 条均无 `correction_of`/`corrections` |
| RSS 精确标题/URL 匹配 | 0/17 |

### 1.2 BLS

| 项目 | 当前值 |
|---|---:|
| series | 9 |
| 观测 | 971 |
| 版本 | 971（全部 initial） |
| 月度 / 季度 | 933 / 38 |
| 缺失值 | 3（`value_raw='-'`，未当 0） |
| 采集窗口 | 2017–2026（API v1 的单次 10 年窗口） |
| 真实修订 | 未观测到；run 9–11 全部 unchanged |

### 1.3 RSS 对照

| 项目 | 当前值 |
|---|---:|
| 文章 | 126 |
| 事件 | 117 |
| 多文章事件 | 0 |
| 新闻/社区/官方来源 | 15 个启用来源，12 个来源族 |
| 现有宏观来源 | BEA 3、Fed 2、ONS 3 |
| BLS series 文章 | 0（RSS 没有 BLS 序列） |

---

## 2. Federal Register 逐条评估

> 以下为摘要/元数据的初步评估；实际逐条验证（RSS 时间与影响对象）见 §10–§11。两者冲突时以 §10–§11 为准。

> 判断口径：`信息增量` 看是否提供 RSS 未覆盖的一手政策信息；`行动价值` 看是否有明确主体、日期或可执行入口。仅凭标题/摘要，未读全文时标 `abstract only`；摘要为空标 `title only`。RSS 匹配是在当前 126 篇文章内的标题/URL 精确检查，不代表外部世界没有其他报道。
>
> **HIGH 的含义**：下文的 HIGH 仅指**基于摘要和元数据识别出的高信息潜力**，不是已验证的高商业价值。全文未审查，企业影响未验证；不得把 HIGH 当作商业结论。

| # | document_number / 来源 | 日期 / 类型 / 机构 | 主题与明确相关性 | 影响对象 | 可行动信息 | RSS 同事件 | 证据 | 信息增量 | 行动价值 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | [2026-21818](https://www.federalregister.gov/documents/2026/10/26/2026-21818/space-modernization-for-the-21st-century) | 10-26 / PRORULE / FCC | “Space Modernization”；摘要仅说 FNPRM 寻求进一步改革，未给出具体条款 | 卫星/频谱相关企业（推断） | comments 2026-11-25 | 无 | abstract only，摘要过泛 | LOW | UNKNOWN |
| 2 | [2026-21820](https://www.federalregister.gov/documents/2026/10/26/2026-21820/modernizing-the-ability-of-consumers-to-control-robocalls) | 10-26 / PRORULE / FCC | TCPA 机器人电话；撤销请求时限、双向短信、撤销全部、关联方 | 电话营销、金融、通信服务商 | comments 2026-11-25 | 无 | abstract only | MEDIUM | MEDIUM |
| 3 | [2026-21821](https://www.federalregister.gov/documents/2026/10/26/2026-21821/enhancing-the-ability-of-consumers-to-control-the-robocalls) | 10-26 / RULE / FCC | 消费者撤销机器人电话同意；金融欺诈提醒豁免 | 电话营销、金融机构、通信平台 | effective 2026-11-25 | 无 | abstract only | MEDIUM | MEDIUM |
| 4 | [2026-21884](https://www.federalregister.gov/documents/2026/10/27/2026-21884/critical-material-list-addition-of-helium) | 10-27 / NOTICE / DOE | 氦加入 DOE Critical Material List；摘要明确提到半导体制造、天然气基础设施泄漏测试、量子计算、医疗/科研、数据中心供应链 | 半导体、数据中心、能源、医疗、量子 | 无评论/生效日期；政策清单变化 | 有主题邻近（数据中心/芯片），无同事件 | abstract only；明确供应链表述 | HIGH | MEDIUM |
| 5 | [2026-21896](https://www.federalregister.gov/documents/2026/10/27/2026-21896/notice-of-publication-of-us-resources-management-industry-listing-and-opportunity-to-apply-for-the) | 10-27 / NOTICE / Commerce | 美国 Resources Management Industry Listing；水/污水、废物/回收（含 critical minerals recycling）、空气质量、监测、气象 | 环保/资源管理/回收/监测企业 | comments 2026-12-11；可申请 listing | 无 | abstract only | MEDIUM | MEDIUM |
| 6 | [2026-21912](https://www.federalregister.gov/documents/2026/10/28/2026-21912/agency-information-collection-activities-proposed-collection-comment-request-food-and-drug) | 10-28 / NOTICE / FDA | PRA 信息收集；FDA Rapid Response Surveys | FDA 监管流程 | comments 2026-12-28 | 无 | abstract only | LOW | LOW |
| 7 | [2026-21913](https://www.federalregister.gov/documents/2026/10/28/2026-21913/agency-information-collection-activities-submission-for-office-of-management-and-budget-review) | 10-28 / NOTICE / FDA | PRA 信息收集；Color Additive Certification | FDA 监管流程 | comments 2026-11-27 | 无 | abstract only | LOW | LOW |
| 8 | [2026-21914](https://www.federalregister.gov/documents/2026/10/28/2026-21914/agency-information-collection-activities-proposed-collection-comment-request-application-for) | 10-28 / NOTICE / FDA | PRA 信息收集；FDA Fellowship/Traineeship | FDA 监管流程 | comments 2026-12-28 | 无 | abstract only | LOW | LOW |
| 9 | [2026-21953](https://www.federalregister.gov/documents/2026/10/28/2026-21953/electronic-submission-template-for-investigational-device-exemption-ide-applications-draft-guidance) | 10-28 / NOTICE / FDA | IDE 电子提交模板 draft guidance | 医疗器械 sponsor、CRO | comments 2026-12-28 | 无 | abstract only | MEDIUM | LOW |
| 10 | [2026-22082](https://www.federalregister.gov/documents/2026/10/29/2026-22082/additional-reconsideration-standards-of-performance-for-new-reconstructed-and-modified-sources-and) | 10-29 / PRORULE / EPA | 油气行业 NSPS/排放指南修订；拟撤销 Super Emitter Program，调整井场、液体卸载、控制器、泵、泄漏、储罐等 | 油气生产/设备/服务商、排放监测 | comments 2026-12-16 | 有主题邻近（能源价格），无同事件 | abstract only；条款较多 | HIGH | MEDIUM |
| 11 | [2026-22179](https://www.federalregister.gov/documents/2026/10/30/2026-22179/medical-devices-general-and-plastic-surgery-devices-classification-of-the-software-aided-adjunctive) | 10-30 / RULE / FDA | 软件辅助皮肤癌辅助诊断设备，Class II 特殊控制 | 医疗软件/器械厂商 | effective 2026-10-30 | 无 | abstract only；未明确 AI | MEDIUM | MEDIUM |
| 12 | [2026-22180](https://www.federalregister.gov/documents/2026/10/30/2026-22180/medical-devices-radiology-devices-classification-of-the-radiology-software-for-referral-of-findings) | 10-30 / RULE / FDA | 肺纤维化放射软件，Class II | 医疗影像软件/器械厂商 | effective 2026-10-30 | 无 | abstract only；未明确 AI | MEDIUM | MEDIUM |
| 13 | [2026-22181](https://www.federalregister.gov/documents/2026/10/30/2026-22181/medical-devices-anesthesiology-devices-classification-of-the-spinal-imaging-system-for-neuraxial) | 10-30 / RULE / FDA | 脊柱成像系统，Class II | 医疗器械厂商 | effective 2026-10-30 | 无 | abstract only | MEDIUM | MEDIUM |
| 14 | [2026-22182](https://www.federalregister.gov/documents/2026/10/30/2026-22182/medical-devices-anesthesiology-devices-classification-of-the-over-the-counter-device-to-assess-risk) | 10-30 / RULE / FDA | OTC 睡眠呼吸暂停风险评估设备，Class II | 家用医疗设备厂商 | effective 2026-10-30 | 无 | abstract only | MEDIUM | MEDIUM |
| 15 | [2026-22203](https://www.federalregister.gov/documents/2026/10/30/2026-22203/essential-drug-delivery-performance-characteristics-for-devices-intended-to-deliver-drugs-and) | 10-30 / NOTICE / FDA | 药物递送装置性能特征 revised draft guidance | 药械组合、药物递送厂商 | comments 2027-01-28 | 无 | abstract only | MEDIUM | LOW |
| 16 | [2026-22302](https://www.federalregister.gov/documents/2026/11/02/2026-22302/foreign-trade-zone-ftz-17-notification-of-proposed-production-activity-honeywell-aerospace-us-llc) | 11-02 / NOTICE / Commerce/FTZ | FTZ 17；Honeywell Aerospace US LLC；飞机部件；Olathe, Kansas | Honeywell Aerospace、航空制造、FTZ | 无 abstract；docket `B-125-2026` | 无 | title only，abstract 为空 | LOW/UNKNOWN | UNKNOWN |
| 17 | [2026-22337](https://www.federalregister.gov/documents/2026/11/02/2026-22337/unleashing-the-power-of-unlicensed-ultra-wideband-devices-petition-of-robert-bosch-llc-for-amendment) | 11-02 / PRORULE / FCC | UWB 规则现代化；跟踪、自动化、精确定位、健康监测、公共安全；Bosch/AAI 请愿 | UWB/物联网/汽车/消费电子 | comments 2027-01-04；记录 effective 2026-12-02 | 无 | abstract only | HIGH | MEDIUM |

### 2.1 FR 结构与价值分布

[事实]

- 17 条中 **3 条高信息增量**：2026-21884（氦/半导体供应链）、2026-22082（油气排放规则）、2026-22337（UWB）。
- **9 条中等**：2 条 robocall、1 条 RMIL、1 条 IDE、4 条 FDA 设备分类、1 条药物递送指南。
- **5 条低/不足**：3 条 FDA PRA 行政通知、1 条 FCC space 摘要过泛、1 条 FTZ Honeywell 摘要为空。
- 明确提及 AI 的 FR 文档：**0 条**。2026-22179/22180 是软件/影像设备，但摘要未说 AI，不能推断为 AI 政策。
- 明确提及半导体/芯片/数据中心：**1 条**（2026-21884）。
- 明确涉及能源/油气：**2 条**（2026-21884、2026-22082）。
- 明确涉及贸易/制造/FTZ：**2–3 条**（2026-21896、2026-22302，氦供应链可算邻近）。
- 明确涉及医疗器械/药物递送：**6 条**（2026-21953、22179、22180、22181、22182、22203）。
- 纯行政/信息收集：**3 条**（2026-21912/21913/21914）。

[推断]

- FR 的增量主要不是“AI/芯片新闻”，而是**一手监管文件、评论截止日、生效日和行业适用范围**。这类信息 RSS 当前没有精确同事件覆盖。
- 17 条样本很小，且摘要不足以证明商业影响；`HIGH/MEDIUM` 只是**基于摘要/元数据的信息潜力**，不是商业价值。
- 3 条 HIGH（2026-21884、2026-22082、2026-22337）均未做全文审查；企业影响、条款细节和最终政策效果均为 `[NOT_EVALUATED]`。

---

## 3. BLS 9 个指标的价值分析

**定位**：BLS 当前只作为**宏观背景数据层**。以下描述性变化不构成商业机会判断，也不构成因果结论。真实历史修订未观测，修订识别效果保持 `[NOT_EVALUATED]`。

> 以下均为当前数据的描述性变化；不构成因果判断。月度与季度分开；失业率/生产率为百分点差，其他为百分比变化。

| series | 指标 | 最新期 | 最新值 | 上年同期 | 变化 | 近 3 期方向 | 价值判断 |
|---|---|---:|---:|---:|---:|---|---|
| `CES0000000001` | 非农就业 | 2026-09 | 159,044 千人 | 158,548 | +0.31% YoY；+152 千人 vs 2026-06 | 近 3 月总体上行 | 持续就业扩张背景；非具体机会 |
| `LNS14000000` | 失业率 | 2026-09 | 4.2% | 4.4% | -0.2 pp | 4.2/4.1/4.1/4.2，稳定 | 宏观背景；单指标不足以判断转折 |
| `CES0500000003` | 平均时薪 | 2026-09 | $37.81/h | $36.70 | +3.02% YoY；+$0.22 vs 2026-06 | 连续上行 | 工资成本持续上升；对企业成本分析有用 |
| `CUSR0000SA0` | CPI-U SA | 2026-09 | 336.298 | 324.245 | +3.72% YoY；+3.73 index points vs 2026-06 | 近 3 月加速 | 通胀背景；不直接给行业机会 |
| `CUUR0000SA0` | CPI-U NSA | 2026-09 | 336.940 | 324.800 | +3.74% YoY；+2.99 index points vs 2026-06 | 近 3 月加速 | 与 SA 方向一致；不能与 SA 混合 |
| `JTS000000000000000JOL` | 职位空缺 | 2026-08 | 7,079 千人 | 6,919 | +2.31% YoY；-458 千人 vs 2026-05 | 近 3 月下行 | 劳动力需求近期降温；与招聘/离职结合看 |
| `JTS000000000000000HIL` | 招聘 | 2026-08 | 5,192 千人 | 5,145 | +0.91% YoY；-60 千人 vs 2026-05 | 近 3 月波动偏弱 | 招聘动能不强；宏观背景 |
| `JTS000000000000000QUL` | 离职 | 2026-08 | 3,066 千人 | 3,095 | -0.94% YoY；-87 千人 vs 2026-05 | 近 3 月下行 | 员工主动流动降温；劳动力市场降温的辅助信号 |
| `PRS85006092` | 非农生产率（季度年化 % 变化） | 2026-Q2 | 1.4% | 4.2% | -2.8 pp；Q1 0.8% | 季度波动大 | 不能把单季当趋势；需连续季度观察 |

### 3.1 可解释的共同变化

[推断]

- 近 3 个月：职位空缺、招聘、离职均下行；非农就业仍在增长，失业率稳定，时薪继续上升。
- 这组描述更接近“劳动力需求降温、但就业和工资仍有韧性”，而不是简单的“劳动力市场崩坏”。
- CPI 近 3 个月上行；工资同比 +3.02%、CPI 同比 +3.72%，两者都是正增长，但不能据此推断工资是通胀原因。
- 生产率最新季度 1.4%，低于上年同期 4.2%；季度波动大，不能由此断言趋势。

### 3.2 持续性 vs 单期波动

[推断]

- 持续性较强：非农就业、平均时薪、CPI 的同比方向；但“持续”只指当前序列，不代表未来。
- 近期方向：JOLTS 三项（空缺/招聘/离职）连续数月偏弱，值得继续观察。
- 单期波动风险：生产率（季度年化）从 5.2% → 1.6% → 0.8% → 1.4%，不能用一个季度定性。
- 失业率 4.1–4.2% 区间稳定，尚不足以判断拐点。

### 3.3 对产业环境和商业决策的价值

[推断]

- **可用**：工资成本、劳动力供给、通胀背景、招聘/离职热度，适合做行业或企业分析的环境变量。
- **不可直接用**：没有行业、地区、公司层面的 BLS 细分；不能直接推出某个行业的机会或某家公司的行动。
- **不能做**：把 BLS 的宏观变化直接映射为商业机会；当前 9 个 series 都是总量指标。

### 3.4 BLS 总体判断

- 信息增量：**MEDIUM**（RSS 没有 BLS 序列；971 条观测是结构性补充）。
- 分析价值：**MEDIUM**（可做描述性宏观背景，不能做行业/公司结论）。
- 商业行动价值：**LOW**（没有直接可执行对象）。
- 真实修订识别：**NOT_EVALUATED**（run 9–11 无真实修订）。

---

## 4. 与 RSS 的增量比较

### 4.1 FR → RSS

[事实]

- 17 条 FR 文档与 126 篇 RSS 文章的规范化标题/URL 精确匹配为 **0/17**。
- **0/17 的边界**：这只是规范化标题/URL 的精确匹配结果；不代表不存在同事件报道，也不代表没有主题相关报道。外部媒体覆盖状态仍为 `UNKNOWN`；下面的“主题邻近”只是人工相似性提示，不是同事件确认。
- 当前 RSS 没有 FR 的 document_number、docket、评论截止日或生效日字段。
- 主题邻近但非同事件的文章包括：

| RSS article_key（前缀） | 标题 | 与 FR 的关系 |
|---|---|---|
| `84673459924e1626...` | Big Tech’s Data Center Blitz Is Burning Through Cash and Scaring Wall Street | 与 2026-21884 的半导体/数据中心供应链主题邻近；不是同一事件 |
| `0de680b82ffb0bb6...` | US tech stocks see sharp falls as AI spending nears $1tn | 与半导体/数据中心资本开支主题邻近；不是同一事件 |
| `d28adb7c...` | Intel’s Shares Plunge 20% as A.I. Hinders Some Parts of Its Business | 芯片公司事件；与 FR 监管文件无同事件关系 |
| `33157f235e4ddfa3...` | Heating oil costs 'more than double' ahead of winter | 与 2026-22082 能源主题邻近；不是同一条规则 |
| `a8b687140113e1f7...` | Wanted: Robot-Dog Walkers. $20/Hour. | 机器人主题；与 FR 无同事件关系 |

[推断]

- FR 提供了 RSS 当前没有的**一手政策文本、机构、docket、评论/生效日期**；这是明确的信息增量。
- 但“RSS 没有”只代表当前 126 篇语料没有；外部媒体是否报道、报道是否更早：`[NOT_EVALUATED]`。

### 4.2 BLS → RSS

[事实]

- RSS 的宏观来源只有 BEA 3 篇、Fed 2 篇、ONS 3 篇；没有 BLS series、没有 2017–2026 连续观测。
- RSS 有 BEA GDP/Personal Income、Fed 新闻稿、ONS trade；BLS 有就业、失业率、时薪、CPI、JOLTS、生产率。
- 现有 RSS 中没有“unemployment”“CPI”“JOLTS”“productivity”对应的 BLS 序列文章。

[推断]

- BLS 的增量是**结构化时间序列**，不是新闻事件；它能把 RSS 的宏观叙事变成可追溯的数值背景。
- 但 BLS 没有行业/公司维度；不能单独产生商业机会。
- 与 BEA/Fed/ONS 的关系是互补，不是独立双源；不能把 BLS 数值与 BEA 新闻当两份独立证据。

### 4.3 跨来源关联

[事实]

- Pilot `link_candidates` 当前为 **0**。
- RSS 事件中 **0 个多文章事件**；没有 FR/BLS 与 RSS 事件的已确认关联。
- 没有 FR ↔ BLS 的自动关联记录。

[推断]

- 当前没有证据支持“FR 政策 → BLS 宏观变化”或“BLS 变化 → RSS 事件”的跨来源链条。
- 主题上可形成假设，但必须保留为独立信息；不能为了证明多源架构而强行关联。

[假设]

- FR 的 EPA 油气规则与 BLS 就业/工资之间可能存在行业传导，但 BLS 没有能源行业细分，当前无法验证。
- FR 的氦/半导体材料与 BLS 制造业就业/工资之间可能存在传导，但 BLS 没有半导体行业细分，当前无法验证。
- FR 的 UWB/汽车/物联网规则与 BLS 制造业就业之间可能存在传导，但当前没有行业序列，无法验证。

---

## 5. 跨来源关联的实际证据

| 候选关系 | 证据 | 结论 |
|---|---|---|
| FR 2026-21884（氦/半导体） ↔ BLS 就业/工资 | FR 摘要明确提到半导体/数据中心；BLS 只有总量就业/工资 | **无直接证据**；只能做主题假设 |
| FR 2026-22082（油气规则） ↔ BLS 就业/CPI | FR 是油气排放规则；BLS 无能源行业细分 | **无直接证据** |
| FR 2026-22337（UWB/汽车/IoT） ↔ BLS 制造业 | FR 摘要提到跟踪/自动化/汽车等应用；BLS 无行业/产品细分 | **无直接证据** |
| FR 2026-21896（RMIL）/2026-22302（FTZ） ↔ BLS | 主题为资源管理/航空制造；BLS 无对应行业序列 | **无直接证据** |
| FR/BLS ↔ RSS 事件 | 0 条 link_candidates；0 个多文章事件 | **无已确认关联** |

**结论**：当前只能确认“不同来源各自提供不同类型的信息”，不能确认“它们已经形成可验证的跨来源情报链”。

---

## 6. 低价值、重复及证据不足的案例

### FR

- **低价值行政通知**：2026-21912、2026-21913、2026-21914（FDA PRA 信息收集），主要是一般行政流程，商业相关性低。
- **证据不足**：2026-21818（摘要仅说 FNPRM 寻求改革，未给具体条款）；2026-22302（abstract 为空，仅标题/FTZ docket）。
- **重复/更正**：17 条无相同 document_number，无 correction；未观察到重复。
- **主题重复但非重复事件**：2026-21820/21821 同属 robocall 议题，但一份 PRORULE、一份 RULE，不能当同一条。

### BLS

- **缺失值**：2025-10 的 `CUSR0000SA0`、`LNS14000000`、`CUUR0000SA0` 为 `-`，保留为 `missing_value`，未当 0。
- **单期波动**：`PRS85006092` 季度年化变化从 5.2% 到 1.6% 到 0.8% 到 1.4%，不能用一个季度判断趋势。
- **真实修订**：未观测到；不能评价修订识别的实际效果。
- **粒度不足**：9 个 series 都是总量，没有行业/地区/公司拆分，不能直接支持具体商业机会判断。

---

## 7. FR、BLS 价值等级

| 维度 | Federal Register | BLS |
|---|---|---|
| 数据获取能力 | **PASS**（9/9 watch 配置；17 文档；版本 17） | **PASS**（9 series；971 观测；版本 971） |
| 信息增量 | **MEDIUM**（3 HIGH 仅指摘要/元数据信息潜力，9 MEDIUM、5 LOW/UNKNOWN；0 个 RSS 精确同事件） | **MEDIUM**（RSS 无 BLS 序列；971 条结构化观测） |
| 分析价值 | **MEDIUM**（5 条全文、12 条摘要；行业 14/17、具体企业 3/17） | **MEDIUM**（可做描述性宏观背景；无行业/公司粒度） |
| 商业行动价值 | **LOW**（16/17 有评论/生效日期；仅 3 条点名企业，实际决策价值未验证） | **LOW**（宏观背景，不能直接转为机会） |
| **总体** | **MEDIUM** | **MEDIUM** |

**明确不把技术接入成功等同于 HIGH。** 当前没有证据证明两类来源已经改善实际商业决策。

---

## 8. 是否值得长期维护

### Federal Register

**建议：保留，选择性维护。**

- 保留 9 个 watch / 8 个机构；当前 17 条中 3 条高信息增量、9 条中等。
- 对 3 条 FDA PRA 行政通知可考虑降级/合并到低频观察；但这属于下一阶段配置决策，不在本次修改。
- 需要增加：摘要/全文抽取、公司/行业映射、评论/生效日期提醒；否则行动价值仍低。
- 维护成本低：无 key、请求量小；主要成本是主题/机构过滤和人工复核。

### BLS

**建议：保留，长期维护。**

- 9 个 series 成本低、无 key、结构稳定；971 条观测已证明解析/版本链路。
- 适合作为宏观背景层，不适合直接产生机会。
- 需要增加：发布日历、真实修订跟踪、行业/地区细分（后续单独批准）；当前不扩源。
- 不需要增加更多 series 之前，先把这 9 个用进分析流程验证价值。

### GDELT

保持 `LIVE_BLOCKED / NOT_VERIFIED`；不纳入本次价值结论。没有真实数据，不能评价。

---

## 9. 假设状态（H1–H7）

**范围约束**：此前优先的两个问题已执行完成，结果见 §10–§12；不再把它们重复列为下一阶段待验证任务。H3–H7 保持未启动；不得为了验证多源架构而强行建立 FR/BLS/RSS 关联。

| 假设 | 需要的证据 | 当前状态 |
|---|---|---|
| H1：FR 的高信息增量文档（2026-21884、2026-22082、2026-22337）能产生 RSS 未覆盖的可行动政策信号 | 全文/条款抽取、行业/企业映射、评论/生效日期 | **COMPLETE（有限）**：见 §10–§12；0 SAME_EVENT，14/17 行业，3 条文档点名企业；时间增量未证明 |
| H2：FR 的评论截止日/生效日能作为及时提醒，而不是事后新闻 | 比较 FR 日期与 RSS/新闻首次提及时间 | **COMPLETE**：0/17 SAME_EVENT；无法证明 FR 更早；外部覆盖 UNKNOWN |
| H3：BLS 的就业/工资/CPI/JOLTS/生产率变化能形成比 RSS 更稳定的宏观背景 | 把 9 个 series 接入分析模板，在标注事件上评估解释力 | `[NOT_STARTED]` |
| H4：BLS 能帮助解释 RSS 的 AI/数据中心资本开支叙事 | 用就业/工资/CPI/生产率与 RSS 事件做时间对齐，不推断因果 | `[NOT_STARTED]` |
| H5：FR 与 BLS 可形成政策→宏观链条 | 需要行业/地区细分或外部数据；当前 BLS 总量无法对应 FR 行业 | `[NOT_STARTED]`；当前无证据 |
| H6：BLS 真实修订识别有效 | 下一次 BLS 发布后重复采集，观察 value/flags 变化和版本 | `[NOT_STARTED]`；run 9–11 无修订 |
| H7：FR/BLS 的商业价值足以长期维护 | 用具体分析任务/决策场景评估，不以采集量衡量 | `[NOT_STARTED]` |

---

## 10. 实际验证一：FR 与 RSS 时间先后

### 10.1 方法与边界

- 检查范围：现有 17/17 条 FR 文档；现有 126 篇 RSS 文章。
- FR 时间只使用 `published_at`（发布日期），**不使用评论截止日或生效日**作为首次公开时间。
- RSS 时间使用当前本地 `articles.published`（FreshRSS 记录时间），**不代表全网首次报道**。
- 匹配依据：规范化标题/URL 精确匹配 + 标题/分析文本/主张引文的词边界搜索 + 人工复核。
- `SAME_EVENT` 必须是同一政策事件；主题词相似只算 `RELATED`。
- `UNMATCHED` 只表示现有 RSS 未发现，不代表外部世界没有报道。

### 10.2 逐条结果

| document_number | FR 发布日期 | RSS 匹配 | RSS 记录 ID / 时间 | 匹配依据 | 时间比较 | 置信度/边界 |
|---|---|---|---|---|---|---|
| 2026-21818 | 2026-10-26 | **RELATED** | `ba6eb471f17f066479231a4bc710ed2448a249a582e5d629f953a50a7094b557`（2026-10-25T09:28Z，event `evt-52a60af44c05e2c8`） | RSS 为 Starlink/卫星规则；FR 为 FCC 空间/地球站规则；不是同一政策事件 | RSS 早约 0.6 天；**不计数**（非 SAME_EVENT） | 主题相关，非同一事件 |
| 2026-21820 | 2026-10-26 | UNMATCHED | — | 搜索 robocall/TCPA/telephone consumer，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-21821 | 2026-10-26 | UNMATCHED | — | 搜索 robocall/revocation，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-21884 | 2026-10-27 | **RELATED** | `84673459924e1626ae2574e56f2c4deed355dd28f5a88a1d6e4ddfe55e51e1c2`（2026-10-29T22:11Z，event `evt-135412bfe1c158f7`）；`d28adb7c…`（Intel，10-29） | RSS 为数据中心/芯片；FR 为氦/半导体供应链；不是同一事件 | FR 早约 2.9 天（相对相关报道）；**不计数** | 主题相关，非同一事件 |
| 2026-21896 | 2026-10-27 | UNMATCHED | — | 搜索 resources management/recycling/wastewater，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-21912 | 2026-10-28 | UNMATCHED | — | 搜索 FDA/rapid response survey，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-21913 | 2026-10-28 | UNMATCHED | — | 搜索 color additive/FDA，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-21914 | 2026-10-28 | UNMATCHED | — | 搜索 FDA/fellowship/traineeship，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-21953 | 2026-10-28 | UNMATCHED | — | 搜索 IDE/investigational device/medical device，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-22082 | 2026-10-29 | **RELATED** | `33157f235e4ddfa31546f501d0fe797c0da56ec858786d96380210eed0dadffd`（2026-10-25T07:12Z，event `evt-eb5398f3be23da15`） | RSS 为取暖油价格；FR 为油气排放规则；不是同一事件 | RSS 早约 3.7 天；**不计数** | 主题相关，非同一事件 |
| 2026-22179 | 2026-10-30 | UNMATCHED | — | 搜索 skin cancer/medical device/software，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-22180 | 2026-10-30 | UNMATCHED | — | 搜索 fibrotic lung/radiology software，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-22181 | 2026-10-30 | UNMATCHED | — | 搜索 spinal imaging，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-22182 | 2026-10-30 | UNMATCHED | — | 搜索 sleep apnea/OTC device，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-22203 | 2026-10-30 | UNMATCHED | — | 搜索 drug delivery/combination product，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-22302 | 2026-11-02 | UNMATCHED | — | 搜索 Honeywell/foreign-trade/aircraft components，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |
| 2026-22337 | 2026-11-02 | UNMATCHED | — | 搜索 ultra-wideband/UWB/Bosch，无命中 | N/A | 当前 RSS 内未发现；外部 UNKNOWN |

**补充**：`0/17` 的规范化标题/URL 精确匹配仍成立；上表的 RELATED 是人工主题相邻，不是同事件。`2026-21818` 的 RSS 记录是 Starlink/卫星主题，不是 FCC 空间现代化规则；`2026-21884`/`2026-22082` 同理。

### 10.3 汇总

| 指标 | 结果 |
|---|---:|
| 实际检查 | 17/17 |
| SAME_EVENT | **0/17** |
| RELATED | **3/17**（2026-21818、2026-21884、2026-22082） |
| UNMATCHED | **14/17** |
| UNKNOWN（现有 RSS 证据不足） | 0/17 |
| 确认 FR 早于 RSS 同事件报道 | **0/17**（无 SAME_EVENT，无法计算同事件时间差） |
| FR 早于最近 RELATED 报道 | 1/17（2026-21884，约 2.9 天；非同一事件，不计入增量） |

**结论**：现有 RSS 中**没有确认的 FR 同事件报道**；因此本次数据**不能证明 FR 在时间上早于 RSS 同事件报道**。FR 的发布日期只作为政策信号时间；评论截止日/生效日没有用于时间先后比较。

---

## 11. 实际验证二：FR 政策影响对象识别

### 11.1 方法与证据边界

- 17/17 条均做主题/行业审查。
- **全文审查 5 条**：2026-21818、2026-21884、2026-22082、2026-22337、2026-22302。
- **摘要/元数据审查 12 条**：2026-21820、21821、21896、21912、21913、21914、21953、22179、22180、22181、22182、22203。
- 官方原文链接见下表；仅做内部证据摘要，未把全文写入数据库，不公开转载全文。
- `[原文明确]` = 官方文本明确写出；`[推断]` = 根据政策内容判断；`[NOT_EVALUATED]` = 摘要/元数据不足。
- 具体企业只在官方文本明确点名时计入；行业协会/请愿人不自动等同于受影响企业。

### 11.2 逐条影响对象

原始官方链接见 §2 同 document_number 行。

| document_number | 政策主题 | 原文明确的行业/企业类别 | 明确点名的具体企业/组织 | 产品/技术/活动 | 影响类型 | 行动时间 | 证据状态 |
|---|---|---|---|---|---|---|---|
| 2026-21818 | FCC 空间/地球站规则现代化 | 有线/无线/卫星电信（NAICS 517111/517112/517410/517810）、NGSO/GSO 运营者、地球站/终端/物联网/无人机 | **SpaceX、HawkEye 360** | 空间站、地球站、NGSO/GSO、VTSS、终端、无人机、星间链路 | 许可/监管改革、评论 | comments 11/25；replies 12/28；effective NOT_STATED | **全文**；原文明确 |
| 2026-21820 | TCPA 机器人电话 | 电话营销、金融机构、通信服务商 | 无 | 撤销请求、双向短信、撤销全部、关联方 | 合规约束 | comments 11/25 | 摘要；行业明确 |
| 2026-21821 | 机器人电话同意撤销规则 | 电话营销、金融机构、通信平台 | 无 | 撤销同意、金融欺诈提醒豁免 | 合规约束、生效 | effective 11/25 | 摘要；行业明确 |
| 2026-21884 | 氦加入 DOE Critical Material List | 半导体制造、天然气基础设施泄漏测试、量子计算、医疗/科研、数据中心供应链 | 无私营企业 | 氦、半导体、AI/数据中心基础设施 | 政策清单/供应链信号；无合规义务 | 无评论/生效日期 | **全文**；原文明确 |
| 2026-21896 | U.S. Resources Management Industry Listing | 水/污水、废物/回收（含 critical minerals recycling）、空气质量、监测、气象 | 无 | 资源管理产品/服务、国际项目 | 市场准入/曝光、申请 | comments 12/11 | 摘要；行业明确 |
| 2026-21912 | FDA PRA Rapid Response Surveys | 无明确行业 | 无 | 信息收集/调查 | 行政流程 | comments 12/28 | 摘要；`NOT_EVALUATED` |
| 2026-21913 | FDA PRA Color Additive Certification | 无明确行业；食品/化妆品仅为推断 | 无 | 颜色添加剂认证信息 | 行政流程 | comments 11/27 | 摘要；`NOT_EVALUATED` |
| 2026-21914 | FDA PRA Fellowship/Traineeship | 无明确行业 | 无 | 信息收集 | 行政流程 | comments 12/28 | 摘要；`NOT_EVALUATED` |
| 2026-21953 | FDA IDE 电子提交模板 | 医疗器械 sponsor、CRO | 无 | IDE 申请、电子提交 | 流程/效率 | comments 12/28 | 摘要；行业明确 |
| 2026-22082 | EPA 油气 NSPS/排放指南 | 原油/天然气生产、处理、输储、分销；井场、处理厂、压缩机站；业主/运营者 | 行业协会 API、AXPC、TXOGA、MOGA、ASTM（非受影响运营企业） | 甲烷/VOC/GHG；液体卸载、控制器、泵、泄漏、储罐、LDAR/OGI | 合规/排放约束；拟撤销 Super Emitter Program | comments 12/16；hearing 11/13（原文另有 11/16 表述）；effective NOT_STATED | **全文**；行业明确，具体企业未点名 |
| 2026-22179 | 软件辅助皮肤癌诊断设备 Class II | 医疗设备/软件制造商 | 无 | 软件辅助诊断设备 | 监管分类/特殊控制 | effective 10/30 | 摘要；行业明确；未明确 AI |
| 2026-22180 | 肺纤维化放射软件 Class II | 医疗影像软件/设备制造商 | 无 | 放射软件 | 监管分类 | effective 10/30 | 摘要；行业明确；未明确 AI |
| 2026-22181 | 脊柱成像系统 Class II | 医疗器械制造商 | 无 | 脊柱成像系统 | 监管分类 | effective 10/30 | 摘要；行业明确 |
| 2026-22182 | OTC 睡眠呼吸暂停风险评估设备 Class II | 家用医疗设备制造商 | 无 | OTC 设备 | 监管分类 | effective 10/30 | 摘要；行业明确 |
| 2026-22203 | 药物递送装置性能指南 | 药械组合/药物递送开发商 | 无 | 药物递送装置 | 指南/开发流程 | comments 2027-01-28 | 摘要；行业明确 |
| 2026-22302 | FTZ 17 Honeywell 生产活动 | 飞机/航空电子/电子组件；FTZ 17 | **Honeywell Aerospace US LLC** | 飞机部件、航电、电子组件、测试设备 | FTZ 生产/关税 | comments 12/14；effective NOT_STATED | **全文**；原文明确 |
| 2026-22337 | UWB 规则现代化 | UWB 设备制造商、汽车、消费电子、工业自动化、医疗、公共安全、频谱用户 | **Robert Bosch LLC、Alliance for Automotive Innovation**；历史 waiver 例子 Rod Radar、Proceq、Curtiss-Wright | UWB 设备、雷达、成像、AI sensing、机器人、自动驾驶、无人机 | 拟议放松监管/技术要求 | comments 12/02；replies 2027-01-04；effective NOT_STATED（DB 的 `effective_on=2026-12-02` 与全文不符，不能当生效日） | **全文**；原文明确 |

### 11.3 汇总

| 指标 | 结果 |
|---|---:|
| 实际检查 | 17/17 |
| 全文审查 | 5/17 |
| 摘要/元数据审查 | 12/17 |
| 能明确识别行业/企业类别 | **14/17** |
| 能明确点名具体企业 | **3/17**（2026-21818、2026-22302、2026-22337） |
| 行业/企业影响 `NOT_EVALUATED` | **3/17**（2026-21912、21913、21914） |
| 有具体评论/生效日期 | 16/17（2026-21884 无评论/生效日期） |
| 仅在摘要层面、具体企业不可识别 | 12/17（不等于行业不可识别） |

### 11.4 关键发现

1. **HIGH 3 条的全文核查结果**：
   - 2026-21884：行业明确（半导体、天然气基础设施、量子、医疗/科研、数据中心），**无具体私营企业**；没有评论/生效日期。
   - 2026-22082：行业与设备/活动明确，点名的是行业协会而非受影响运营企业；评论截止 12/16。
   - 2026-22337：行业和具体企业/组织明确（Bosch、Alliance for Automotive Innovation），评论 12/02、回复 2027-01-04；DB 的 `effective_on` 与全文不一致。
2. **原先证据不足的 2 条**：
   - 2026-21818：全文明确 SpaceX、HawkEye 360；可识别卫星/地球站/电信行业。
   - 2026-22302：全文明确 Honeywell Aerospace US LLC；可识别航空部件/FTZ。
3. **FDA PRA 3 条**：摘要只能确认行政信息收集流程，无法确认具体行业/企业影响，保持 `NOT_EVALUATED`。
4. **具体企业识别有限**：17 条中只有 3 条明确点名具体企业；其余多为行业类别、监管流程或行业协会。

---

## 12. 实体角色核验

### 12.1 方法与边界

- 核验对象：2026-21818、2026-22302、2026-22337 中出现的具体实体。
- 原文依据：Federal Register 官方全文（不写回数据库，不公开转载全文）。
- 只有官方文本明确写出角色时才计入 `DIRECTLY_REGULATED` / `APPLICANT` / `PETITIONER` / `COMMENTER` / `INDUSTRY_ASSOCIATION`。
- “企业名称出现”不等于“受政策影响”；“潜在受影响”是根据政策适用范围推断，单独标记。
- 行业协会不按受影响企业计数。

### 12.2 逐实体角色

| 实体 | document_number | 原文角色 | 明确依据 | 潜在受影响（推断） | 角色状态 |
|---|---|---|---|---|---|
| SpaceX | 2026-21818 | `MENTIONED_THIRD_PARTY`；正式角色 `UNKNOWN` | “SpaceX suggests that we align the Commission's rules for earth stations with the part 2 rules.”（§III.D ¶26）；文档未称其为 commenter/petitioner/applicant | 卫星/地球站运营者，可能受 FCC 规则影响（推断） | 非直接监管；正式角色 UNKNOWN |
| HawkEye 360 | 2026-21818 | `MENTIONED_THIRD_PARTY`；正式角色 `UNKNOWN` | “HawkEye 360 requested that the Commission include adding or changing RF sensing capabilities”（§III.D ¶30）；未标注其正式身份 | RF sensing/卫星运营者，可能受影响（推断） | 非直接监管；正式角色 UNKNOWN |
| Honeywell Aerospace US LLC | 2026-22302 | `APPLICANT`（提交人/通知人；原文未使用 applicant 一词） | “Honeywell Aerospace US LLC submitted a notification of proposed production activity to the FTZ Board”；“for its facility in Olathe, Kansas within FTZ 17.” | FTZ 生产活动运营者，可能获益/受影响（推断） | 明确提交人；非直接监管 |
| Robert Bosch LLC | 2026-22337 | `PETITIONER` | “Robert Bosch LLC filed a Petition for Rulemaking requesting that the Commission modernize the UWB rules.”；“the Petition for Rulemaking filed by Robert Bosch LLC … are granted” | UWB 设备制造商，可能受影响（推断） | 明确请愿人；非直接监管 |
| Alliance for Automotive Innovation | 2026-22337 | `PETITIONER`（joint petitioner）+ `INDUSTRY_ASSOCIATION` | “Alliance for Automotive Innovation, the Car Connectivity Consortium, the FiRa Consortium … (collectively, the Joint Petitioners) filed a Petition for Rulemaking”；caption 作 “Petition of Alliance for Automative Innovation et al.” | 代表汽车行业成员，不按受影响企业计数 | 行业协会；联合请愿人；非企业 |
| Rod Radar | 2026-22337 | `MENTIONED_THIRD_PARTY`（prior waiver example） | “more recent waiver authorizations such as Rod Radar”；“a specific waiver (e.g., Rod Radar, Proceq, or Curtiss-Wright)…” | 不推断为本次规则直接影响对象 | 仅被提及 |
| Proceq | 2026-22337 | `MENTIONED_THIRD_PARTY`（prior waiver example） | 同上 | 不推断为本次规则直接影响对象 | 仅被提及 |
| Curtiss-Wright | 2026-22337 | `MENTIONED_THIRD_PARTY`（prior waiver example） | 同上 | 不推断为本次规则直接影响对象 | 仅被提及 |

### 12.3 统计

| 口径 | 数量 | 说明 |
|---|---:|---|
| 重点核验实体 | 5 | SpaceX、HawkEye 360、Honeywell、Bosch、Alliance for Automotive Innovation |
| 文件中出现的具体企业（含 22337 prior waiver 例子） | **7** | SpaceX、HawkEye 360、Honeywell、Bosch、Rod Radar、Proceq、Curtiss-Wright |
| 文件中出现的行业协会 | **1** | Alliance for Automotive Innovation |
| 明确属于直接监管对象的企业 | **0** | 三个文件均未把上述企业明确标注为“directly regulated entity” |
| 明确属于申请人/提交人/请愿人的企业 | **2** | Honeywell（提交人）、Bosch（请愿人）；AAI 为行业协会/联合请愿人，不计企业 |
| 明确属于评论者的企业 | **0** | 原文没有把 SpaceX/HawkEye 标注为 commenter |
| 仅能推断潜在受影响的企业 | **4** | SpaceX、HawkEye 360、Honeywell、Bosch（均为推断，不是原文明确结论） |
| 无法确认正式角色的实体 | **2** | SpaceX、HawkEye 360；仅有“suggests/requested”描述 |

### 12.4 对原 3/17 口径的修正说明

- 原报告的 **3/17** 是“17 条文档中有 3 条至少点名一个具体企业/组织”的**文档级**统计。
- 实体级核验后：
  - 7 个具体企业名称出现；
  - 其中 0 个被原文明确标注为直接监管对象；
  - 2 个企业有明确的申请人/提交人/请愿人角色（Honeywell、Bosch）；
  - 4 个企业只能推断为潜在受影响（SpaceX、HawkEye、Honeywell、Bosch）；
  - 2 个正式角色 UNKNOWN（SpaceX、HawkEye）；
  - 1 个行业协会（AAI）不计入受影响企业。
- **3/17 不应被表述为“3 家受影响企业”**；它只是“3 条文档点名了具体企业/组织”。本次不为了保留原数字而降低标准。
- **4 家“推断潜在受影响”不得与 2 家“明确申请人/请愿人”合并**：前者是政策适用范围推断，后者是原文明确程序角色；两类都不是“明确直接监管”。本报告的 0 家明确直接监管企业是主结论。

---

## 13. 结论摘要

### 13.1 本次实际验证的回答

| 问题 | 有证据的回答 |
|---|---|
| 17 条中确认存在 RSS 同事件报道 | **0/17** |
| FR 早于 RSS 同事件报道 | **0/17**；无 SAME_EVENT，无法计算同事件时间差 |
| 能明确识别行业影响对象 | **14/17** |
| 文档级点名具体企业 | **3/17**（2026-21818、2026-22302、2026-22337） |
| 实体级具体企业/协会 | **7 家企业 + 1 家协会**；0 家明确直接监管；2 家企业明确申请人/请愿人；4 家仅推断潜在受影响；2 家正式角色 UNKNOWN |
| 证据不足/无法判断行业或企业影响 | **3/17**（2026-21912/21913/21914 的 FDA PRA 行政通知） |
| FR 的时间增量是否被支持 | **当前不支持**；RSS 无同事件，无法证明 FR 更早 |
| FR 的影响对象识别是否被支持 | **部分支持**；14 条可识别行业；3 条文档点名企业；实体角色见 §12；12 条仅摘要、3 条影响不可判断 |

### 13.2 是否改变 MEDIUM 评级

**不改变。**

- Federal Register：**MEDIUM**。它提供了 RSS 之外的一手政策文本、行业/日期信息，且在 3 条中能点名具体企业；但当前 RSS 没有同事件报道，无法证明时间增量；多数文档仍只有行业类别，商业行动价值未验证。
- BLS：**MEDIUM**，结论不变（宏观背景层；修订未观测）。
- 不因为 3 条 HIGH 或 3 条文档点名企业而升级为 HIGH。
- H1/H2 已完成（§10–§12）；不再重复列为待验证任务。H3–H7 未启动；不新增来源。

### 13.3 实际检查数量与未检查项

- FR：17/17 检查；5 条全文，12 条摘要/元数据。
- RSS：126 篇现有文章检索；0 条 SAME_EVENT；3 条 RELATED。
- 未检查：12 条 FR 全文、外部新闻覆盖、FR/BLS 因果关系；这些均标 `NOT_EVALUATED` 或 `UNKNOWN`。
- 实体角色：7 家具体企业 + 1 个行业协会；0 家明确直接监管；2 家企业明确申请人/请愿人；4 家仅推断潜在受影响；2 家正式角色 UNKNOWN。

**本次只新增/更新 [SOURCE_PILOT_VALUE_REVIEW.md](SOURCE_PILOT_VALUE_REVIEW.md) 与阶段状态文档；未重新采集，未调用 GDELT，未重跑 FR/BLS，未修改代码/数据库/配置/调度，未启动新来源。**

- **FR：MEDIUM。** 提供了 RSS 没有的一手政策文本、日期和机构信息；3 条高信息增量、9 条中等、5 条低/不足；行业影响 14/17、文档级点名企业 3/17（实体级 7 家企业 + 1 家协会），商业行动价值仍 LOW。
- **BLS：MEDIUM。** 提供了 RSS 没有的 9 个结构化宏观序列和 971 条观测；信息增量明确，但只是宏观背景，不能直接转化为商业机会；真实修订未观测。
- **RSS 增量：** FR 精确同事件 0/17；BLS series 在 RSS 中为 0；增量存在，但不是“同事件多源佐证”。
- **跨来源关联：** 当前 0 条 link_candidates、0 个多文章事件；没有证据支持 FR↔BLS 或 FR/BLS↔RSS 的已确认链条。
- **不扩源：** 当前应先做价值验证，不接入第四个来源；GDELT 保持闲置。
- **不修改：** 本次只新增本报告；生产/Pilot 数据、代码、配置、调度均未改变。

**评审通过；Source Pilot 正式冻结（FROZEN / CLOSED）。H1/H2 已完成，H3–H7 未启动；不再追加 FR 审计，不继续增加来源。下一阶段单独定义情报产品输出与价值验收标准。**

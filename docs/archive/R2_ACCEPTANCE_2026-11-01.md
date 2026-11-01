# R2 主张核验（规则 r2-v1）— 实施、离线验证与 G6 评审材料

日期：2026-11-01
状态：**规则与核验模块已实现，离线验证完成；未在生产库运行，未改变生产提示词与发布门禁**
上游：`docs/PRD.md` §4.4（FR-V1–V8）、`docs/IMPLEMENTATION_PLAN.md` R2

---

## 1. 交付内容

| 组件 | 文件 | 作用 |
|---|---|---|
| 结构化主张契约 | `opportunity_radar/claim_contract.py` | 字段定义、词表、逐字段降级为偏差；`CONTRACT_VERSION = r2-v1` |
| 单位与数值规则 | `opportunity_radar/units.py` | 数量解析、比例词、单位族、缩放换算、百分比/百分点区分 |
| 核验引擎 | `opportunity_radar/verify.py` | 逐条核验、引文支持分类、冲突检测、结果持久化；`RULES_VERSION = r2-v1` |
| 持久化 | schema v4 | `claim_verifications`（追加式）、`claim_conflicts`；`claims.verified_at`、`verification_basis` |

## 2. 契约 r2-v1

| 字段 | 规则 |
|---|---|
| `subject` / `predicate` | 必填；缺失则该条主张被丢弃，其他主张保留 |
| `kind` | fact / source_interpretation / system_inference / hypothesis / forecast / opinion / unknown |
| `value_num` | 数值或可解析字符串；不可解析 → 偏差并置空，主张保留 |
| `unit` | `%`、`pp`、货币、`megawatthours` 等；未知单位 → 偏差并保留原值 |
| `currency` | ISO 代码；unit 为货币时自动推导 |
| `period` | `YYYY` / `YYYY-MM` / `YYYY-MM-DD` / `YYYY-Qn` / `起/止`；无法识别 → 偏差并置空 |
| `comparison` | level / yoy / qoq / mom / period_change / percentage_point_change / share / unknown |
| `seasonality` | seasonally_adjusted / not_seasonally_adjusted / unknown |
| `revision` | original / revised / preliminary / amendment / subsequent_comparative / unknown |
| `quote` | 数值主张必须有引文，否则记偏差 |

原则：**任何一个字段不合规只降级该字段**，不丢整篇分析。

## 3. 核验规则 r2-v1

| 检查 | 规则 | 失败后果 |
|---|---|---|
| `value_in_quote` | 主张数值（按其单位缩放后）出现在引文的同类数量中 | rejected |
| `unit` | 引文单位与主张单位同族；百分比与百分点必须一致 | rejected |
| `period` | 主张期间与证据定位中的 period/period_end 一致 | rejected |
| `comparison` | 主张的比较口径与引文措辞不矛盾（yoy/mom/qoq） | rejected |
| `quote_support` | direct / indirect / unsupported / contradiction | contradiction 即 rejected |

状态判定：

- **rejected**：任一项硬性检查失败。
- **verified**：至少一项通过且无失败项。
- **unverifiable**：骨架主张（无结构化字段）、无证据、或所有检查都无从适用。

`verified` 的含义是**主张与其证据记录一致**，不是"该事实为真"。对 XBRL 事实而言这是映射正确性检查；
报告的 `basis` 会区分 `structured_quote_support`。

## 4. 离线验证（生产库副本）

| 库 | 主张 | 结果 | 偏差 |
|---|---|---|---|
| 生产 RSS 库 | 220（全部 `extractor=skeleton`） | **unverifiable 220** | 0 |
| 摄取库（SEC/EIA） | 2,753 | **verified 2,753** | 0 |

- **旧数据兼容**：RSS 的骨架主张一律 `unverifiable`，依据 `skeleton_no_structured_fields`，
  不会因为引文存在就变成"已核验"。
- **幂等**：第二次运行不新增 `claim_verifications` 行；只有输入（主张字段或证据引文）变化时才追加。
- **可追溯**：`claim_verifications → claims → claim_evidence → evidences → locator`：
  例 `ver-7814c42c… → cl-000d7cfb… → ev-099ec74a…`，定位含 accn `0001045810-19-000144`、
  CIK、tag、期间。

### 4.1 跨来源冲突（FR-V5）

真实数据检出 **114 条冲突**，全部是同一主体+指标+期间+单位的数值不一致。示例：

```
COCA COLA CO · capex · 2017-01-01/2017-12-31 · 1,750,000,000 vs 1,675,000,000
  revisions: subsequent_comparative / original
```

这是真实的重述：同一期间的资本开支在后续申报中被改写。冲突记录只记录事实，不判断哪个值应当采信。

## 5. 测试

| 项 | 数值 |
|---|---|
| 新增 | `tests/test_verify.py`（24 项） |
| 全量 | **673 项通过**（R1 后 649） |

覆盖：数值不符、引文无同类数值、单位族不符、百分比 vs 百分点、期间不符、同比/环比措辞矛盾、
骨架主张不得verified、无证据、能量单位缩放、契约偏差、幂等、证据变化后追加历史、
冲突记录、同值不算冲突、dry-run 不写库、核验结果可回溯到证据。

## 6. G6 评审需要确认的事项

1. **规则版本**：`claim_contract.CONTRACT_VERSION = 'r2-v1'`，`verify.RULES_VERSION = 'r2-v1'`。
   确认后该版本号随每次核验写入记录，后续修改必须升版。
2. **是否启用结构化提示词（v7）**：当前生产提示词仍是 v6，只产出散文事实，因此 RSS 主张全部
   `unverifiable`。启用 v7 才能产生可核验的数值主张；本批**未修改**任何提示词。
3. **`verified` 是否可以影响发布**：当前发布门禁（R0）只依赖覆盖率，与核验无关。是否让未核验
   主张阻断发布，属于 R3/R0 的独立决策，本批未做。
4. **冲突处理策略**：114 条真实冲突目前只被记录，不参与排序或展示。需要确认：
   修订申报是否应默认覆盖原值、冲突是否应在日报中提示、是否需要人工裁定流程。
5. **百分比/百分点口径**：规则已区分 `%` 与 `pp`，但生产提示词尚未要求模型区分；启用前需在契约
   里明确要求。
6. **`indirect` 支持类别**：当前规则只产出 direct / unsupported / contradiction；`indirect`
   （引文间接支持）尚未定义判定条件，需要确认判定标准后再实现。

## 7. 未做与限制

- 未在生产库运行核验，未修改 `runs`、日报或门禁。
- 未实现派生值（公式/输入）核验（FR-V8 的 P1 部分）。
- 单位换算只支持同族缩放，不含汇率；跨货币比较一律 `unverifiable`。
- 冲突检测只在同一数据库内进行；RSS 与 SEC/EIA 分库，跨库冲突需先有实体与期间对齐（R1 已有实体，
  但 SEC 主张没有事件归属）。

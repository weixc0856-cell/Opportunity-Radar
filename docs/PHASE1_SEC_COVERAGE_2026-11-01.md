# 第一阶段 — SEC 覆盖与标签映射报告

日期：2026-11-01
授权：G-D2
数据来源：`data.sec.gov` companyconcept API，真实请求 20 次，User-Agent 已声明联系方式
落库：`data/ingest/opportunity_radar_ingest.sqlite3`（独立库）

---

## 1. 覆盖率

| 指标 | 覆盖 | 说明 |
|---|---|---|
| 收入 | **10 / 10** | 全部公司取得可用标签 |
| 资本开支 | **9 / 10** | JPMorgan 无标准标签 → `unsupported`，未猜测 |
| 事实行数 | **2,719** | 收入 1,783（含 TSLA 备选标签 49）、资本开支 936 |
| 修订行 | **28** | `form` 以 `/A` 结尾，标记 `filing_relation=amendment` |
| 选择状态 | 1,254 `current_selected` / 1,465 `superseded` | 旧值保留，不删除 |

## 2. 逐公司结果

| 公司 | CIK | 收入 | 资本开支 | 备注 |
|---|---|---|---|---|
| Apple | 0000320193 | 117 | 105 | |
| Microsoft | 0000789019 | 136 | 232 | |
| NVIDIA | 0001045810 | 280 | 35 | 资本开支标签与其他公司不同 |
| JPMorgan | 0000019617 | 149 | **0（unsupported）** | 银行口径，未映射 |
| ExxonMobil | 0002115436 | 4 | 2 | 6 行均标 `requires_filing_parse` |
| Tesla | 0001318605 | 335 | 142 | 收入含 `Revenues` 286 + 备选 49 |
| Caterpillar | 0000018230 | 345 | 58 | |
| Coca-Cola | 0000021344 | 114 | 173 | |
| UnitedHealth | 0000731766 | 268 | 154 | |
| TSMC | 0001046179 | 35 | 35 | IFRS taxonomy，仅年度 |

## 3. 数据质量规则的实际表现

1. **单位**：全部 `USD`，未混算；`pure`/`shares` 事实未出现在本阶段标签集合中。
2. **期间**：`start`/`end` 原样保留；无 `start` 的行标 `instant`。
3. **YTD**：同一财年的累计期原样入库，**未派生季度值**（六条件helper已实现并测过，但不持久化）。
4. **选择状态**：每个 `(cik, tag, unit, start, end)` 只有一条 `current_selected`，按 `filed` + `accn` 排序，确定性。
5. **缺失**：ExxonMobil 仅 4 + 2 条，标 `requires_filing_parse`，未补造。
6. **自定义 taxonomy / 维度化事实**：未请求、未猜测，本阶段不覆盖。

## 4. 幂等性

连续运行 2 次：`sec_facts` 保持 2,719 行，无重复；重复观察只更新 `last_seen_at` 与标志位。

## 5. 未覆盖

- 自定义 taxonomy 与维度化（分部）事实。
- 后续申报重述旧期间（`subsequent_comparative`）——需要 submissions 接口，本阶段未实现，因此非 `/A` 的新 accession 一律记为 `original`，不冒充修订。
- 完整 10-K 文本解析。

# 第一阶段 — EIA 数据质量与分页验证报告

日期：2026-11-01
授权：G-D2
数据来源：EIA API v2，真实请求 2 次；key 只从进程环境变量读取
落库：`data/ingest/opportunity_radar_ingest.sqlite3`（独立库）

---

## 1. 范围

| 项 | 值 |
|---|---|
| route | `/v2/electricity/electric-power-operational-data/data/` |
| 指标 | `generation`（Utility Scale Electricity Net Generation） |
| facet | `location=US`、`sectorid=99`、`fueltypeid=COW`（白名单，代码内硬约束） |
| 期间 | monthly 2024-01 – 2026-08；annual 2024 – 2025 |
| 观测 | 34 条（月度 32 + 年度 2） |

超出白名单的 facet（`ALL`、`COL`、`sectorid=98`、州级）在构造查询时即被拒绝，不会发出请求。

## 2. 对账（真实数据）

| 年 | 月度合计（GWh） | 年度端点（GWh） | 差值 | EPM Table 1.1 | 取整后一致 |
|---|---|---|---|---|---|
| 2024 | 652,155.92065 | 652,155.92065 | 0.00000 | 652,156 | ✅ |
| 2025 | 734,928.49178 | 734,928.49178 | 0.00000 | 734,928 | ✅ |
| 2026 | 458,608.52553（8 个月） | 无年度值 | — | — | 部分年度，不生成年度观测 |

## 3. 时间口径

- 月度观测 `period_kind=monthly`，年度观测 `period_kind=annual`，两者分开存储。
- 2026 年只有 1–8 月：以 `year_to_date()` 计算，返回 `months_observed=8`、`is_partial_year=true`，
  **不写入任何 2026 年度观测**。
- 原始值以字符串保存（如 `"652155.92065"`），解析后的浮点另存，先舍入再做任何展示。

## 4. 分页与完整性

- 实现按 `offset += len(data)` 循环，直到累计行数等于 `response.total`。
- 累计行数与 `total` 不相等时抛 `truncation`，**不落库**。
- `total=0` 抛 `empty_result`；无效 facet 的 200 空集因此不会被当成"数值为 0"。
- 本轮 32 行由单页返回（`length=5000`）；四页分页逻辑由本地样本覆盖测试（offset 0/10/20/30）。

## 5. 快照与修订

- 每次请求的原始响应按 SHA-256 存入 `data/ingest/snapshots/eia/<hash>.json`，同哈希不重复写。
- `eia_observation_versions` 记录每个 `(series_id, period, snapshot_hash)` 的取值：
  首次 `first_observed`，值变化时新增 `observed_change` 并给当前行打标。
- API 不返回 `release_date` / `revision` / `status` / `last_updated`，因此**不伪造**任何修订状态；
  观测发生变化只表示"本系统观察到了差异"，不等于官方公告修订。

## 6. 幂等性

连续运行 3 次：`eia_observations` 保持 34 行，`eia_observation_versions` 保持 34 行，未产生重复或伪修订。

## 7. 未验证

- API 配额与限流阈值仍未实测（本轮未触发 429）。
- 发布滞后（`endPeriod` 到实际可见）未知。
- 其他 route、data 字段、地理层级未覆盖。

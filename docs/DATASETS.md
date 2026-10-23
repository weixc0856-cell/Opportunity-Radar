# 数据集登记（结构化宏观数据）

`config/datasets.csv` 登记**结构化时间序列**，与 `config/sources.csv` 的文章来源分开。

## 为什么分开

一条时间序列不是一篇文章：

- 它有**统计期间**（2025-12）、**单位**（百分比）、**口径**（季调/非季调）和**修订**；
- 它不能被 `scoring.py` 的 A/B/C 通道评分，也不该出现在"今天发生了什么"的条目流里；
- 它的许可、配额和更新节奏与 RSS 来源完全不同。

把 FRED 或 Eurostat 伪装成一条 RSS，只会得到一个永远不产出、也无法解释的登记行。

## 字段

| 字段 | 含义 | 规则 |
|---|---|---|
| `dataset_id` | 稳定 ID | 唯一、非空 |
| `institution` | 官方机构 | 必填 |
| `name` | 数据集名称 | 必填 |
| `access_kind` | `api` / `api_key` / `download` | 必须是枚举值 |
| `endpoint` | 真实端点 | 必须 HTTPS；API key 用 `{API_KEY}` 占位，**绝不**提交真实密钥 |
| `homepage` | 官方入口 | HTTPS |
| `indicator` | 指标名称 | 审批前必填；一个裸数字不是指标 |
| `unit` | 单位 | 审批前必填 |
| `frequency` | `daily/weekly/monthly/quarterly/annual/irregular` | 枚举 |
| `seasonality` | 季调口径 | 自由文本，例如 `not seasonally adjusted` |
| `latest_period` | 最近观测期间 | 审批前必填 |
| `latest_value` | 最近观测值 | 记录观测值，不做二次计算 |
| `latest_updated` | 数据集自身的更新时间 | ISO 日期；与探测日期不同要解释 |
| `last_checked_at` | 本机最近一次实测日期 | 审批前必填 |
| `license_status` | `unknown` / `confirmed_attribution` / `confirmed_public_domain` / `restricted` | `approved` 时不能是 `unknown` |
| `terms_url` | 许可/版权页面 | 审批时必须是实际读过的页面 |
| `quota_notes` | 配额与限制 | 自由文本 |
| `status` | `candidate` / `approved` / `blocked` / `retired` | 见下 |
| `notes` | 事实与未决问题 | `blocked` 必须说明原因 |

## 状态与审批门

- `candidate`：已登记，未核实许可，**不调用**。
- `blocked`：明确无法接入（缺 API key、条款不允许、端点不可用），必须写原因。
- `approved`：同时满足——`license_status` 已确认、`terms_url` 是读过的页面、`indicator/unit/frequency/latest_period` 齐全、`last_checked_at` 已记录、端点不含 `{API_KEY}` 占位。
- `retired`：停用但保留历史与原因。

审批**不**意味着数据正确、口径合适或可以对外发布；它只表示"本机可以按登记的方式读取"。

## 命令

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.datasets
.\.venv\Scripts\python.exe -m opportunity_radar.datasets --check
.\.venv\Scripts\python.exe -m opportunity_radar.datasets --check eurostat-hicp-ea --json
```

`--check` 只探测 `approved` 数据集，读取 JSON-stat，打印**最新期间与数值**，便于发现"接口还活着但序列停更"。

它**不能**证明：指标口径正确、数值已修订到最新、许可覆盖再发布、或读数可以直接写进报告。这些必须人工核对原始发布页。

## 当前登记（2026-10-23）

| dataset_id | 机构 | 状态 | 观测 |
|---|---|---|---|
| `eurostat-hicp-ea` | Eurostat | approved | 2026-10-23 探测 HTTP 200，最新期间 **2025-12 = 2.0%**，数据集 `updated` 为 2026-02-06 |
| `fred-gdp` | FRED | blocked | 需要注册 API key；本机未配置，**未调用** |

Eurostat 的许可结论来自其 copyright notice：统计数据的再利用被授权，条件是**注明来源**（编辑内容为 CC BY 4.0）。该页面是人工阅读后记录的，不是从 URL 可达性推断的。

**注意**：欧统局接口返回的最新期间（2025-12）早于探测日期约 10 个月。可能是发布/镜像滞后，也可能是参数口径问题。在解释这个数字之前，必须回到 Eurostat 发布日历核对；本仓库不据此下任何结论。

## 未做

- 不存时间序列、不做缓存、不做修订对比；
- 不做单位换算或派生指标；
- 不把数值自动写进日报。日报仍是事件流，数字需要人工放进上下文。

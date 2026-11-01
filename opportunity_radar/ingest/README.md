# 独立摄取通道（SEC / EIA）

授权：G-D2（`docs/archive/IMPLEMENTATION_AUTHORIZATION_2026-11-01.md`）。第一阶段只做数据获取、规范化、存储、质量验证。

## 边界（不可自行放宽）

- 独立 SQLite 文件，**拒绝**任何解析到 `data/opportunity_radar.sqlite3` 的路径。
- 独立进程与入口，`cli.py` 不引用本包。
- 不写 `articles` / `analyses` / `analysis_history` / `analysis_sections` / `runs`。
- 不进入现有 LLM 分析、评分、证据门槛与日报。

## 配置（全部为环境变量，模板不含真实值）

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `OR_INGEST_DB_PATH` | 否 | `data/ingest/opportunity_radar_ingest.sqlite3` | 必须与生产库不同 |
| `OR_INGEST_REPORT_DIR` | 否 | `reports/ingest` | 运行报告目录 |
| `OR_INGEST_SEC_USER_AGENT` | SEC 必填 | — | 必须含真实联系方式，SEC 要求声明 |
| `OR_INGEST_EIA_API_KEY` | EIA 必填 | 回退 `EIA_API_KEY` | 只从进程环境读取 |
| `OR_INGEST_TIMEOUT_SECONDS` | 否 | `30` | 单请求超时 |
| `OR_INGEST_SEC_MAX_RPS` | 否 | `5` | 上限被硬性夹在 ≤5 req/s |
| `OR_INGEST_EIA_BASE_URL` | 否 | `https://api.eia.gov/v2` | |
| `OR_INGEST_SEC_BASE_URL` | 否 | `https://data.sec.gov` | |

## 运行

```
.venv\Scripts\python.exe -m opportunity_radar.ingest.eia_main
.venv\Scripts\python.exe -m opportunity_radar.ingest.sec_main
```

退出码：`0` 全部成功，`1` 部分或全部失败（明细写 `ingest_failures`），`2` 配置错误。

## 结构

| 文件 | 作用 |
|---|---|
| `config.py` | 环境变量、生产库路径拒绝 |
| `http.py` | 传输、gzip 解码、限速、9 类失败分类、有界重试 |
| `store.py` | 独立 schema、幂等写入、快照、版本、运行/失败记录 |
| `labels.py` | SEC 10 家公司显式标签映射 |
| `sec.py` / `eia.py` | 客户端与规范化 |
| `sec_main.py` / `eia_main.py` | 两个独立入口 |

## 数据口径要点

- 缺失值写 `NULL`，不写 0；空结果（`total=0`）抛 `empty_result`，不当成零值。
- EIA 单位缺失或不等于 `thousand megawatthours` 时整批拒绝。
- EIA 分页以「累计行数 == `total`」判定，不足为 `truncation`。
- SEC 选择状态：同一 `(cik,tag,unit,start,end)` 只保留一条 `current_selected`，其余 `superseded`，旧值不删除。
- YTD 差分需同时满足六个条件，否则不派生；第一阶段不持久化派生季度值。
- 2026 年只有 8 个月：作为「部分年度」计算，**不生成年度观测**。

# 第一阶段最终运行验收：完整日报与 SEC/EIA 摄取并发

日期：2026-11-01
授权：G-D2
性质：**只执行、只验证、只报告**——本轮未修改任何项目代码、配置或数据库结构

---

## 1. 运行环境

| 项 | 状态 |
|---|---|
| FreshRSS `127.0.0.1:8088` | **UP**（HTTP 200） |
| 本地模型 `127.0.0.1:8080` | 运行前 **DOWN** → 用 `deploy/windows/start-model.ps1` 启动（权重与二进制均在本地，未改配置）→ `/health` 返回 `{"status":"ok"}` |
| 解释器 | `.venv\Scripts\python.exe`，Python 3.13.14 |
| 摄取配置 | 独立库 `data/ingest/opportunity_radar_ingest.sqlite3`，SEC User-Agent 取自既有 `.env` 联系方式，EIA key 取自进程环境 |

---

## 2. 两个进程

| 进程 | 命令 | 启动 (UTC) | 结束 (UTC) | 耗时 | 退出码 |
|---|---|---|---|---|---|
| **A 完整日报** | `python -m opportunity_radar.cli --dry-run` | 04:51:20 | 05:01:51 | 10m31s | **0** |
| **B EIA 摄取** | `python -m opportunity_radar.ingest.eia_main` | 04:51:30 | 04:52:1x | ≈2s | **0** |
| **B SEC 摄取** | `python -m opportunity_radar.ingest.sec_main` | 04:52:1x | 04:52:19 | ≈45s | **0** |

**重叠确认**：B 的整个执行窗口（04:51:30–04:52:19，49 秒）完全落在 A 的运行窗口内。

关于入口：使用 `--dry-run`，即完整链路（FreshRSS 抓取 → 模型调用 → 分析 → 评分 → 渲染 → 写 `runs`），仅跳过 SMTP 发信。
没有使用 `--render-only` 或 `--sample`，没有使用 mock 模型。跳过发信是刻意的：向真实收件人发信是外部副作用，验收运行不触发。

---

## 3. 日志与异常

| 检查 | 结果 |
|---|---|
| A 退出码 | 0，日志末行 `Saved to reports\latest-digest.txt and latest-digest.html; no email sent.` |
| A 异常 | 无 Traceback、无 ERROR |
| B 退出码 | EIA 0 / SEC 0 |
| B 输出 | EIA `success requests=2 records=34 errors=0`；SEC `success requests=20 records=2719 errors=0` |
| **SQLite 锁错误** | **0 次**（两份日志均无 `database is locked` / `OperationalError`） |
| 模型调用失败 | 0（run 14 `error_count=0`） |

A 的日报实际产出：抓取 20 篇，分析 10 篇，引文定位 32 条可定位 / 0 条无法定位，数据质量 E1 8 + E2 2。

---

## 4. 运行前后指纹

### 4.1 生产库（`data/opportunity_radar.sqlite3`）

| 项 | 运行前 | 运行后 |
|---|---|---|
| 字节 | 1,925,120 | 2,150,400 |
| SHA-256 | `8c8194659af7c763…` | `e18272e69fcaea50…` |
| 表数量 | 13 | 13（**无新增表**） |
| `integrity_check` | — | **ok** |

行数变化：

| 表 | 前 | 后 | 差值 | 归因 |
|---|---|---|---|---|
| articles | 110 | 117 | +7 | 本轮新抓取 |
| article_versions | 116 | 123 | +7 | 同上，一篇文章一个内容版本 |
| analyses | 99 | 108 | +9 | 10 次分析，其中 1 篇是既有文章的重新分析（REPLACE，不增行） |
| analysis_history | 104 | 114 | +10 | 每次分析一条历史 |
| analysis_sections | 658 | 756 | +98 | 10 次分析 × 约 9.8 个段落 |
| runs | 13 | 14 | +1 | **仅 A 一条** |
| deliveries | 26 | 26 | **0** | `--dry-run` 未发信 |
| analysis_failures | 7 | 7 | **0** | 本轮无失败 |

新增 run 记录：`(14, 'dry_run', 20, 10, 0, 'done', exit_code=0, 'No email sent (dry run)')`。

### 4.2 摄取库（`data/ingest/opportunity_radar_ingest.sqlite3`）

| 项 | 运行前 | 运行后 |
|---|---|---|
| 字节 | 1,482,752 | 1,482,752（**未变**） |
| 表数量 | 8 | 8 |
| `integrity_check` | — | **ok** |
| `ingest_runs` | 11 | 13（+2：EIA、SEC 各一次） |
| `ingest_failures` | 20 | 20（全部为本轮之前的历史记录） |
| `sec_facts` | 2,719 | **2,719** |
| `eia_observations` | 34 | **34** |
| `eia_observation_versions` | 34 | **34** |
| `raw_snapshots` | 22 | **22** |

**幂等性**：SEC 与 EIA 重跑后事实/观测/版本/快照数量全部不变；文件字节数也不变（内容哈希相同，不重复写快照）。

---

## 5. SEC/EIA 数据隔离证据

| 检查 | 方法 | 结果 |
|---|---|---|
| 业务表是否出现摄取标记 | 在 `articles` / `analyses` / `analysis_sections` 的文本列中搜索 `eia:`、`sec-edgar`、`electric-power-operational-data`、`companyconcept` | **0 命中** |
| 日报文本是否含摄取标记 | 同上，搜索 `reports/latest-digest.txt` | **0 命中** |
| 生产库表结构 | 对比运行前后表清单 | 13 → 13，**无摄取表** |
| `runs` 来源 | 新增 1 条，`stage='done'`、`message='No email sent (dry run)'` | 仅来自 A |
| 摄取写入目标 | `ingest_runs` +2 | 仅写入独立库 |

---

## 6. 日报输出

| 文件 | 运行前 SHA-256 | 运行后 SHA-256 |
|---|---|---|
| `reports/latest-digest.txt` | `2865eab118a3…` | `073f007b172a…` |
| `reports/latest-digest.html` | `f567adadb8b9…` | `f6e812b49919…` |

输出变化属预期：本轮新分析 10 篇文章。**没有同状态的历史基线**可做逐字对比，因此"与基线逐字一致"这一条无法验证，只能验证"正常生成、内容符合既有链路、不含摄取数据"。

---

## 7. 验收状态

| # | 项 | 判定 | 证据 |
|---|---|---|---|
| 1 | 两进程正常退出 | `PASS_VERIFIED` | A=0，B(EIA)=0、B(SEC)=0 |
| 2 | 无锁错误/事务错误/异常退出/模型失败 | `PASS_VERIFIED` | 日志 0 命中；run 14 error_count=0 |
| 3 | 摄取数据只在独立库 | `PASS_VERIFIED` | 生产库 0 命中摄取标记；无摄取表 |
| 4 | 未进入业务表 | `PASS_VERIFIED` | articles/analyses/analysis_sections 全部 0 命中 |
| 5 | 日报正常生成 | `PASS_VERIFIED` | 20 篇抓取 / 10 篇分析 / 引文 32 条可定位 / 输出已写 |
| 6 | 生产库变化可解释 | `PASS_VERIFIED` | 逐表差值均有归因，见 §4.1 |
| 7 | `runs` 新增仅来自日报 | `PASS_VERIFIED` | 仅 run 14，dry_run |
| 8 | 摄取数据完整且幂等 | `PASS_VERIFIED` | 2,719 / 34 行不变，版本与快照不变 |
| 9 | 两库完整性 | `PASS_VERIFIED` | 两库 `PRAGMA integrity_check` = ok |
| 10 | Git 无本轮修改 | `PASS_VERIFIED` | dirty 52 → 52，HEAD `e79dff92` 未变 |

补充：

| 项 | 判定 |
|---|---|
| **完整日报与 SEC/EIA 摄取并发** | **`PASS_VERIFIED`** |
| **条件 5-B：独立通道运行隔离** | **`PASS_VERIFIED`** |
| 日报与历史基线逐字一致 | `NOT_VERIFIED`（无同状态基线，不伪造） |

---

## 8. 第一阶段最终判定

**`PASS_VERIFIED`（10/10 项）。**

理由：本轮是真实运行证据——完整日报（真实 FreshRSS、真实本地模型、真实写库）与两个真实摄取进程在时间上重叠执行，
两库完整性正常、无锁错误、数据零交叉、摄取幂等、生产库变化逐项可归因、Git 未变。
此前保持 `PARTIAL` 的唯一缺口（完整日报并发）已关闭，条件 5-B 因此升为 `PASS_VERIFIED`。

---

## 9. 未解决与非阻塞限制

1. **无同状态字节基线**：无法证明日报输出与"上一次相同输入的输出"逐字一致，只能证明正常生成且不含摄取数据。
2. **真实 429 未触发**：按要求不主动制造限流，限流路径仅由 mock 覆盖。
3. **`rights` 无真实触发点**：策略函数已测，但本阶段没有遇到真实的未清权内容。
4. **模型由本轮启动**：llama-server 仍在本机运行，未做关闭处理；这属于环境状态，不是项目变更。
5. `--dry-run` 跳过了 SMTP 发信，因此"发信路径"本轮未验证（此前 26 条 deliveries 来自历史运行）。

---

## 10. 本轮改动

**无。** 未修改任何项目代码、测试、配置、数据库结构或定时任务；未提交 Git。
新增文件仅为本地证据：`data/ingest/evidence/`（日志与时间戳，`data/*` 已 gitignore）。

# R0 运行可靠性与发布门禁 — 实施与验收记录

日期：2026-11-01
授权：R0 开发任务（2026-11-01），阈值、重试口径与 HOLD 行为由该授权直接给出
状态：**代码实现完成，测试通过，真实故障注入运行通过**；R1 未启动
上游设计：`docs/IMPLEMENTATION_PLAN.md` §5（R0 工作分解）

---

## 1. 范围

实现并验收 11 项要求：传输层重试、运行级健康复查、熔断与 `not_attempted`、
覆盖率计算、PASS / PASS_WITH_LIMITATIONS / HOLD 门禁、HOLD 邮件隔离、报告披露、
`runs` 持久化发布字段、`analysis_failures` 持久化原因与尝试次数、管理台展示、
故障注入与端到端验证。

未改动：评分权重与规则、E0/E1/E2 证据规则、SEC/EIA 独立通道、来源配置与来源范围、
定时任务、`config/scoring.toml`、`config/sources.local.csv`。

---

## 2. 实施契约（已冻结）

### 2.1 覆盖率

```
coverage = analyzed / queued
queued   = analyzed + failed + not_attempted
```

`queued` 是本轮真正进入分析队列的条目：已分析过且内容未变的（`skipped`）和
同事件重复（`duplicate_events`）不计入分母。`queued = 0` 时 coverage 记为 1.0 ——
完整运行但没有新内容仍属正常可发布，这一点是门禁的硬性要求，不允许被覆盖率误伤。

`not_attempted` 只由熔断产生：模型不可达后，剩余本应分析的条目逐条记录为未尝试，
不从计数中消失。

### 2.2 阈值

| 状态 | 条件 | 行为 |
|---|---|---|
| `PASS` | coverage ≥ 0.8 | 正常发送 |
| `PASS_WITH_LIMITATIONS` | 0.5 ≤ coverage < 0.8 | 发送，报告正文与 HTML 必须披露覆盖率与失败原因 |
| `HOLD` | coverage < 0.5，或存在阻断性完整性故障 | 不发订阅邮件、不发告警邮件；本地报告与运行记录保留 |

阻断性完整性故障指运行级异常（渲染/写库失败、未捕获异常）与 `model_unavailable`
在启动阶段被判定；它们与覆盖率无关，直接 HOLD。

**记录的解释**：熔断本身不单独触发 HOLD，它通过把剩余条目计入分母来降低覆盖率。
理由：授权把"阻断性完整性故障"与"覆盖率不足"列为两个独立触发条件，而模型中途死亡
的后果已经由覆盖率完整表达；若熔断一律 HOLD，覆盖率高但末尾中断的运行就无法与
真正失败的运行区分。

### 2.3 重试口径

**`attempts` 指实际发出的 HTTP 请求数，包含第一次请求。** 因此"最多 3 次重试"等于
最多 4 次尝试，运行记录里不会出现两种读法。

| 失败类型 | 判据 | 重试次数 | 最大尝试 |
|---|---|---|---|
| 连接重置 | `ConnectionResetError` / `ConnectionAbortedError` / `BrokenPipeError` | 3 | 4 |
| 连接被拒绝 | `ConnectionRefusedError`、无法解析的主机 | 3 | 4 |
| 超时 | `socket.timeout` / `TimeoutError` | 1 | 2 |
| HTTP 429 | 响应码 429 | 3，优先 `Retry-After` | 4 |
| HTTP 5xx | 500–599 | 3 | 4 |
| HTTP 4xx | 400–499（429 除外） | 0 | 1 |

退避 2 / 5 / 10 秒（`OR_LLM_RETRY_BACKOFF`）。`Retry-After` 超过
`OR_LLM_RETRY_AFTER_MAX`（默认 30 秒）按上限截断；单篇文章累计退避超过
`OR_LLM_RETRY_MAX_SECONDS`（默认 120 秒）立即放弃，避免一次限流把整轮拖住。

**JSON 解析恢复与传输层重试相互独立**：解析失败仍走原有的"换提示词重发"路径，
不由传输层重试处理；该路径上的失败会把两次调用的请求数累加进 `attempts`。

### 2.4 熔断

- 触发条件一：一次连接级失败（重置/拒绝/超时）后复查 `/health`，不可达即熔断。
- 触发条件二：连续 3 次连接级失败即熔断，即使 `/health` 仍在应答。
- 5xx 与 429 不触发熔断：服务器仍在应答，问题由单次调用的重试预算处理。
- 熔断后剩余条目记录为 `cause='circuit_open', attempts=0`。

### 2.5 HOLD 的边界

`HOLD` 判断位于 `send_decision` 之前、所有投递分支（含"无新内容"与"重复报告"）之前，
是唯一可以阻止订阅邮件的位置。HOLD 路径不写 `deliveries` 行、不调用邮件发送函数、
不调用告警函数。

后果说明：由于所有失败路径现在都是 HOLD 路径，`_alert()` 在 R0 之后不会再有调用点。
这是授权的直接要求（"HOLD 不发送失败告警邮件"），不是遗漏；函数保留供未来非 HOLD
路径使用。

---

## 3. 代码改动

| 文件 | 改动 | 原因 |
|---|---|---|
| `opportunity_radar/publication.py` | **新增** | 门禁规则、覆盖率、阻断原因、披露文案；纯函数，可单测 |
| `opportunity_radar/analyzer.py` | 失败分类、有界重试、`Retry-After`、退避预算、`ModelCallError` | 传输层此前无重试，一次连接重置即整篇失败 |
| `opportunity_radar/config.py` | 7 个新配置项 + `_ratio` / `parse_backoff` | 阈值与重试必须可配且可校验 |
| `opportunity_radar/store.py` | `runs` 增 4 列、`analysis_failures` 增 2 列、`finish_run` 新参数、`parse_causes` | 发布状态与失败原因必须可追溯 |
| `opportunity_radar/cli.py` | 熔断、`not_attempted`、覆盖率与门禁、HOLD 隔离、启动即失败记 HOLD、报告披露断言 | 主流程 |
| `opportunity_radar/digest.py` | 标题前置覆盖率、正文"运行完整性"行、空报告原因 | 不完整运行必须自我披露 |
| `opportunity_radar/render_html.py` | 覆盖率披露块 | HTML 是读者实际看到的版本 |
| `opportunity_radar/analytics.py` | 漏斗新增"熔断未尝试" | 否则漏斗数字对不上 |
| `opportunity_radar/admin_server.py` | `/api/status` 增加 `publication` | 管理台展示 |
| `admin/assets/app.js` | 运行行显示发布状态/覆盖率/未尝试 | 同上 |
| `tools/e2e_verify.py` | `--fault-mode {schema,server,reset,refuse}`、发布门禁校验 | 端到端故障注入 |
| `.env.example` | 记录新配置项与口径 | 可复现 |

新增测试文件：`tests/test_publication.py`、`tests/test_run_gate.py`。

---

## 4. 数据库迁移

附加式，不改既有列、不重命名、不删除：

| 表 | 新增列 |
|---|---|
| `runs` | `publication_status TEXT`、`coverage REAL`、`failed_causes TEXT`（JSON）、`not_attempted INTEGER` |
| `analysis_failures` | `cause TEXT`、`attempts INTEGER` |

- 新库由 `CREATE TABLE` 直接建全；旧库由 `PRAGMA table_info` 检测后 `ALTER TABLE ADD COLUMN`。
- 旧行保持原值，新列为 `NULL`；`finish_run` 用 `COALESCE` 写入，省略发布参数的老调用不会抹掉已有值。
- 已验证：生产库副本（13 张表、`runs` 14 行、`analysis_failures` 7 行）打开即完成迁移，
  历史行可正常读取，`PRAGMA integrity_check` = ok。

---

## 5. 测试

| 项 | 数值 |
|---|---|
| 全量 | **570 项通过**（R0 前 511 项） |
| 新增 | 59 项 |
| 新增文件 | `test_publication.py`（11）、`test_run_gate.py`（9） |
| 扩展文件 | `test_analyzer.py`（重试与分类 15）、`test_cli.py`（门禁与无绕过 5）、`test_config.py`（4）、`test_digest.py`（3）、`test_store.py`（4）、`test_e2e_verify.py`（9） |

`test_run_gate.py` 不使用 mock 替身来验证门禁本身：它替换的只有外部世界（FreshRSS、
模型、SMTP、来源登记），store、迁移、评分、报告、运行记录都是真实代码。

---

## 6. 场景验证矩阵

| 场景 | 预期 | 验证方式 | 结果 |
|---|---|---|---|
| 模型启动即不可用 | HOLD，不发信 | 全链路测试 + 真实 CLI 进程对关闭端口运行 | 通过：写入 `model_unavailable` 的 HOLD 运行记录，退出码 3，无投递 |
| 模型运行中途被杀 | 熔断，剩余 `not_attempted` | **真实运行**（§7） | 通过：1 次 `connect_refused`（attempts=4）+ 3 次 `circuit_open` |
| 全部分析失败 | HOLD | 全链路测试 | 通过：coverage 0.0 → HOLD，无投递 |
| coverage ≥ 0.8 | PASS | 全链路测试 | 通过：coverage 1.0 → PASS，正常发送 |
| 0.5 ≤ coverage < 0.8 | PASS_WITH_LIMITATIONS | 全链路测试 | 通过：coverage 0.6 → 发送且正文含"覆盖率 60%" |
| coverage < 0.5 | HOLD | 全链路测试 + **真实运行** | 通过：0.4 与 0.333 均 HOLD |
| 完整正常运行 | 正常发布 | 全链路测试 | 通过：无"运行完整性"行 |
| HTTP 429 | 遵循 Retry-After | 单元测试（含上限截断与 HTTP-date 回退） | 通过 |
| HTTP 503 | 有界重试 | 单元测试 + `tools/e2e_verify.py --fault-mode server` 全流程 | 通过：2 篇各 4 次尝试后失败，HOLD，0 投递 |
| ConnectionReset | 有界重试 | 单元测试 + 真实 CLI 进程对断连服务器运行 | 通过：`connect_reset`，每次 4 次尝试，HOLD，0 投递 |
| 运行级完整性异常 | HOLD | 代码路径 + 报告校验测试 | 通过：未捕获异常写 `integrity` 原因并记 HOLD |
| HOLD | 本地报告保留、订阅邮件不发 | **真实运行**（§7） | 通过：报告与归档均存在，`deliveries` 为空，SMTP sink 收到 0 封 |

补充验证：

| 项 | 结果 |
|---|---|
| 邮件发送失败与分析失败不混淆 | 未改动的分离路径保留：投递失败记 `partial_failed` 与逐收件人 `deliveries` 行 |
| HOLD 不能从其他入口绕过 | 静态断言：HOLD 分支位于 `send_decision` / `send_email_detailed` / `store.delivery` 之前 |
| 旧数据库安全迁移 | 生产库副本实测（§4） |
| 历史 `runs` 读取 | 同上，14 行历史运行正常读出 |
| `--render-only` 确定性 | 生产库副本连续两次渲染，SHA-256 相同，退出码 0 |
| 重复运行不重复发信 | 幂等键逻辑未改动，且 HOLD 不产生投递行 |

---

## 7. 真实运行：模型中途被终止

环境：FreshRSS `127.0.0.1:8088`（UP）、本地模型 `127.0.0.1:8080`（真实启动）、
独立数据库 `data/r0-evidence-2026-11-01/run.sqlite3`、本地 SMTP sink
`127.0.0.1:2525`（只在本机接收并记录，不向任何真实收件人投递）。

| 时刻（本地） | 事件 |
|---|---|
| 15:58:45 | 日报启动（`python -m opportunity_radar.cli`，`OR_MAX_ARTICLES=6`） |
| 16:00:55 / 16:01:55 | 第 1、2 篇分析写入数据库 |
| 16:02:09 | **强制终止 llama-server 进程**（PID 29032），`/health` 随即不可达 |
| 16:02:32 | 第 3 篇分析失败：`connect_refused`，`attempts=4`（1 次初始 + 3 次重试） |
| 16:02:34 | 健康复查失败 → 熔断，剩余 3 篇记为 `circuit_open`（`attempts=0`） |
| 16:02:34 | 发布暂缓：coverage 33% < 50%，未发送订阅邮件 |
| 16:02 | 进程退出，退出码 **1** |

运行记录（`runs`）：

```
status=partial_failed  article_count=6  analyzed_count=2  error_count=1
publication_status=HOLD  coverage=0.3333  not_attempted=3
failed_causes={"circuit_open": 3, "connect_refused": 1}
exit_code=1  message="HOLD: 分析覆盖率 33% 低于 50%; subscription email skipped"
```

失败明细（`analysis_failures`）：1 行 `connect_refused` / `attempts=4`，
3 行 `circuit_open` / `attempts=0`。

**邮件未发送的证据**：`deliveries` 表 0 行；本地 SMTP sink 记录文件不存在
（sink 只在收到 `DATA` 后追加记录，0 条即 0 封）。

**报告保留**：`reports/latest-digest.txt`、`reports/latest-digest.html` 与
`reports/archive/` 下的归档均生成；正文与 HTML 都写明覆盖率 33%、失败 1 篇、
熔断未尝试 3 篇、失败原因与 `HOLD`。

**数据库完整性**：运行库 `PRAGMA integrity_check` = ok。

**生产库未被触碰**：运行前后 `data/opportunity_radar.sqlite3` 的 SHA-256 均为
`e18272e69fcaea50…`，字节数 2,150,400，行数 articles 117 / analyses 108 / runs 14 /
analysis_failures 7，完全一致。

### 7.1 端到端工具（`tools/e2e_verify.py`）

`--fault-mode server`（每次补全返回 503 + `Retry-After`，`/health` 仍应答）实跑整条链路：

```
preflight     : 5/5 PASS（FreshRSS 27 feeds、池 8 篇、模型健康）
happy run     : exit=0 status=dry_run analyzed=2 → PASS, coverage=1.0, 全部检查 PASS
fault run     : exit=1 status=analysis_failed analyzed=0 failed=2
                → HOLD, coverage=0.0, hold_sends_nothing PASS, 报告含失败说明
result        : pass
```

另外两种故障（断连、关闭端口）用同一批 CLI 参数直接驱动真实进程验证，结果见
`data/r0-evidence-2026-11-01/fault-modes/results.json`：`server` 模式 3 篇全部
`http_5xx`（每次 4 次尝试）、`reset` 模式 3 篇全部 `connect_reset`（每次 4 次尝试）、
`refuse` 模式退出码 3 且运行记录为 `model_unavailable` 的 HOLD；三者 `deliveries` 均为 0，
`integrity_check` 均为 ok。

两种验证方式覆盖不同的东西：`e2e_verify.py` 走的是工具自身的入口与检查清单；
直接驱动覆盖同样的 CLI 与门禁，但不经过该工具的调度代码。

---

## 8. 未完成事项与风险

1. **端到端工具未纳入 CI**：`server` 模式本轮完整跑通，`reset` / `refuse` 由直接驱动
   验证；CI 只跑单元测试（含三个故障服务器的行为测试），不跑需要真实模型的端到端流程。
2. **阈值 0.8 / 0.5 的实际运行只覆盖了 HOLD 一侧**：PASS 与 PASS_WITH_LIMITATIONS
   由全链路测试验证（真实 store、评分、报告，替换模型）。用真实模型逐档跑到三个
   覆盖率区间需要数十分钟的模型时间，本轮未做。
3. **告警邮件通道暂时休眠**：见 §2.5。若未来需要"长期连续失败告警"，它必须是
   HOLD 之外的新决策，不能顺手恢复。
4. **单篇退避预算固定 120 秒**：模型极慢时可能出现"重试预算耗尽"这类失败，
   与真正的连接失败共用 `timeout` / `connect_*` 分类，报告里只能看到原因与尝试次数。
5. **未改动 `IMPLEMENTATION_PLAN.md` §5 的 R0 状态**：该文件属于本轮之外的
   文档修订工作，本记录单独存在，不改动其余 48 个未提交路径。
6. 生产环境中仍有一个自 2026-10-29 起运行、一直未退出的日报进程
   （PID 9988）。本轮观察到了它，但没有权限依据去终止或修改它；它可能影响未来
   生产库写入与并发判断，建议单独排查。

---

## 9. 与既有设计的差异

| 设计文档（`IMPLEMENTATION_PLAN.md` §5） | 本次实施 | 原因 |
|---|---|---|
| `analysis_failures` 增 `cause`/`attempts` | 同 | — |
| `runs` 增 `publication_status`/`coverage`/`failed_causes` | 另增 `not_attempted` | HOLD 需要区分"失败"与"从未尝试" |
| 熔断后剩余文章记 `not_attempted` | 同，并逐条写 `analysis_failures` | 要求"所有失败均可追溯" |
| 阈值 0.8 / 0.5 | 同（授权确认） | — |
| 未规定 HOLD 的告警邮件 | HOLD 不发告警 | 授权明确要求 |
| 未规定启动期模型不可用的记录 | 写 HOLD 运行记录后退出 3 | "模型启动即不可用 → HOLD"需要可追溯记录 |

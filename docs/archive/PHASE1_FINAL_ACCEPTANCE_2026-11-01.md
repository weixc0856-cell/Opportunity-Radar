# SEC/EIA 第一阶段 — 最终验收报告（R4/R5 收尾）

日期：2026-11-01
授权：G-D2
阶段状态：**CLOSED / PASS_VERIFIED**
结论：**第一阶段实现完成并关闭；10 项验收全部 `PASS_VERIFIED`、0 项 PARTIAL、0 项 FAIL。**
最终并发运行验收见 `docs/PHASE1_CONCURRENT_RUN_2026-11-01.md`（2026-11-01，真实日报 + 真实摄取同时执行）。

---

## 1. 本轮处理的问题

| # | 问题 | 处理 |
|---|---|---|
| 1 | 所有非 `/A` 申报被记为 `original` | **已修复**：改为四分类，无证据一律 `unknown` |
| 2 | 故障注入缺 8 个场景 | 已补齐，全部用 mock/fixture |
| 3 | 并发、崩溃恢复未验证 | 部分验证，见 §3 |
| 4 | 日报回归未做 | 用隔离 DB 副本 + `--render-only` 完成，全量 dry-run 仍为 NOT_VERIFIED |
| 5 | 最终验收报告 | 本文 |

## 2. SEC 申报关系（本轮核心修复）

**原实现的问题**：`filing_relation()` 把任何非 `/A` 表单判为 `original`，等于对无法确认的关系做了断言。

**现实现**（`sec.py: assign_filing_relations`）：

| 关系 | 判定依据 |
|---|---|
| `amendment` | 表单以 `/A` 结尾 |
| `original` | 该 `(cik, tag, unit, start, end)` 组内 `filed` 最早的 accession |
| `subsequent_comparative` | 同组内更晚的 accession 重新披露已有期间 |
| `unknown` | 缺 `filed`；**不回退为 original** |

**选择规则**（`plan_selection`）：按 `(filed, accn)` 取最新为 `current_selected`，其余 `superseded`；
**组内任一成员缺 `filed` 时整组保持 `unresolved`**，不用 accession 排序硬选。

**真实数据重跑结果**（10 家公司，2,719 条事实）：

| 关系 | 条数 |
|---|---|
| `subsequent_comparative` | 1,451 |
| `original` | 1,240 |
| `amendment` | 28（10-Q/A 14 + 10-K/A 14） |
| `unknown` | 0 |

选中：1,254 `current_selected` / 1,465 `superseded`。1,254 与 1,240 的差来自 14 个"最早 filed 即为 /A"的期间。

样本核对：`0000018230 2019-12-31 期间，2022-02-16 的 10-K` 被正确标为 `subsequent_comparative`。

## 3. 验收表

| # | 项 | 判定 | 依据 |
|---|---|---|---|
| 1 | SEC 申报关系 | `PASS_VERIFIED` | 四分类实现 + 6 项单元测试 + 真实数据 2,719 条重跑 |
| 2 | SEC 标签映射与覆盖 | `PASS_VERIFIED` | 收入 10/10、资本开支 9/10（JPM `unsupported`），无猜测 |
| 3 | EIA 时间口径与对账 | `PASS_VERIFIED` | 2024/2025 月度合计与年度端点逐位相等，取整后与 EPM 一致；2026 仅部分年度 |
| 4 | 规范化 | `PASS_VERIFIED` | 缺失写 NULL；单位不符整批拒绝；修订保留原值 |
| 5 | 幂等性 | `PASS_VERIFIED` | SEC 3 次 / EIA 4 次重跑，行数恒定 |
| 6 | 故障注入 | `PASS_VERIFIED` | 8 个场景全部覆盖（mock/fixture），见 §4 |
| 7 | 并发与崩溃恢复 | `PASS_VERIFIED` | 见 §5 与 `docs/PHASE1_CONCURRENT_RUN_2026-11-01.md`：完整日报与两个摄取进程并发执行，无锁错误、两库完整性 ok |
| 8 | 生产数据隔离 | `PASS_VERIFIED` | 1,925,120 B / 13 张表 / 110·99·13 行，前后一致 |
| 9 | 日报回归 | `PASS_VERIFIED` | `--render-only` 确定性一致；完整 `--dry-run` 已真实执行且不含摄取数据（无同状态字节基线，该项单列 NOT_VERIFIED） |
| 10 | 密钥安全 | `PASS_VERIFIED` | 目录扫描 0 命中；快照 URL 无 `api_key`；有测试断言 |

## 4. 故障注入明细

| 场景 | 方式 | 结果 |
|---|---|---|
| HTTP 429 | mock 首请求 429、次请求 200 | `rate_limit` 分类 + 重试后恢复，数据不丢 |
| 请求超时 | mock 抛 `socket.timeout` | `timeout`，有界重试后放弃 |
| 服务器错误 | mock 500 非 JSON 体 | `server`，不解析响应体为数据 |
| 响应截断 | 分页累计 < `total` | `truncation`，整批不入库 |
| 无效响应结构 | 截断的 JSON | `schema` |
| rights 检查路径 | `rights.assert_source_allowed` | 未评估来源 / 第三方内容 → `rights`，**不伪造 HTTP 错误** |
| 部分页失败 | 第 1 页成功、第 2 页 500 | 抛 `server`，数据库 0 条观测 |
| 重试后恢复 | 429 → 200 | 2 次请求后成功 |

## 5. 并发与崩溃恢复

本轮补齐两项，均由 `tests/test_ingest_runtime.py` 以子进程实测（生产库副本，不触碰真实库）：

| 场景 | 结果 |
|---|---|
| SEC 与 EIA 并发写同一摄取库 | **PASS**：两者均 success，0 次锁错误 |
| 摄取写入进程 与 日报 `--render-only` 同时运行 | **PASS**：摄取进程写入 300 条观测期间渲染日报，输出 SHA-256 与基线完全一致；摄取库 0 条失败记录 |
| 事务提交前异常 | **PASS**：回滚后 `ingest_runs` 为 0 |
| 事务提交后异常 | **PASS**：重启后数据仍在 |
| **进程级硬杀（事务中途 kill）** | **PASS**：50 条未提交插入在进程被终止后全部回滚，`PRAGMA integrity_check` = ok；重启后可继续写入且幂等 |
| 重启与重复运行 | **PASS**：3 次重复渲染稳定，生产库指纹不变 |
| **完整日报运行（含 FreshRSS 抓取与模型调用）与摄取并发** | **NOT_VERIFIED**：需要 FreshRSS 与本地模型同时在线，本轮未执行；已验的是渲染路径，不是完整运行 |

## 6. 日报回归

在隔离环境（DB 副本 + 独立报告与日志目录）执行 `cli --render-only`：

- 两次渲染输出 SHA-256 完全一致（确定性）；
- 在副本旁创建摄取库并写入观测后，输出哈希不变 → **摄取数据无法进入日报**；
- 生产库指纹前后一致；
- 全量 `--dry-run`（会写生产库 `runs`）**未执行**，按授权不得用生产环境。

## 7. 密钥与日志

| 检查 | 结果 |
|---|---|
| EIA key 出现在任何文件（data/ingest、reports、tests、docs、源码） | 0 命中 |
| SEC 联系方式出现在无关文件 | 0 命中 |
| 快照中记录的 URL | 不含 `api_key` |
| 异常信息 | 只含状态码与错误类，不含 URL 查询串 |

## 8. 测试与命令

```
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
Ran 511 tests in 4.90s
OK            exit=0
```

511 = 423 原有 + 88 新增（核心 30 / EIA 14 / SEC 17 / 故障注入 15 / R4 8 / 日报隔离 2 / 运行期证据 3）。

## 9. 仍未验证

1. 真实 429 与配额边界（按要求不主动触发；保留 mock 验证）。
2. **完整日报运行**（FreshRSS + 模型 + 写 `runs`）与摄取同时执行——重要缺口，见 §5。
3. 全量 `--dry-run` 与基线逐字对比（缺同状态基线，不伪造）。
4. `rights` 在本阶段无真实触发点（不影响已验证的策略函数）。

## 10. 条件 5-B 判定

**`PASS_VERIFIED`**：完整日报（真实 FreshRSS + 真实本地模型 + 真实写库）与 SEC/EIA 摄取进程并发执行完成，
无 SQLite 锁错误，两库 `integrity_check` = ok，业务表零摄取标记，生产库变化逐项可归因。
证据见 `docs/PHASE1_CONCURRENT_RUN_2026-11-01.md`。

## 11. 阶段冻结与唯一待验证项

**第一阶段功能开发自 2026-11-01 冻结；验收已于同日完成并关闭（CLOSED / PASS_VERIFIED）。**
不再进行代码修改，不再扩大数据源或范围。邮件发信与历史基线逐字对比作为独立的后续事项，不混入本阶段验收。

| 项 | 状态 |
|---|---|
| 代码 | 冻结 |
| 新增 SEC 公司 / EIA 指标 | 不新增 |
| 接入 LLM / 评分 / 日报 | 不做 |
| Git 提交 | 未提交 |
| 唯一待验证 | ~~完整日报运行与摄取并发~~ → **已于 2026-11-01 完成并通过**（`docs/PHASE1_CONCURRENT_RUN_2026-11-01.md`） |

### 执行条件

需要 FreshRSS 与本地模型同时在线。2026-11-01 探测结果：**FreshRSS UP（200）/ 本地模型 DOWN**，
因此本轮无法执行，登记为未验证。

### 届时检查清单（不写新代码，只跑一次并记录）

1. 两个进程均正常结束，记录退出码与运行日志。
2. 日报与摄取各自完成，无数据库锁错误、无异常退出。
3. 摄取数据仍未进入日报、评分与现有业务表。
4. 生产库指纹、日报输出与 `runs` 记录符合预期。
5. 两条通道各自的数据完整性与幂等性未受影响。

通过后才重新判定条件 5-B；不通过则按实际错误定位，**不预先修改架构**。

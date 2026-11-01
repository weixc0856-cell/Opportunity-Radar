# 第一阶段 — 隔离、故障与并发验证报告

日期：2026-11-01
授权：G-D2
证据：`tests/test_ingest_core.py`、`tests/test_ingest_eia.py`、`tests/test_ingest_sec.py`、`tests/test_ingest_faults.py`

---

## 1. 数据隔离

| 检查 | 方法 | 结果 |
|---|---|---|
| 独立数据库文件 | `assert_isolated_db` 拒绝解析到 `data/opportunity_radar.sqlite3` 的路径 | **PASS**（含 symlink 解析后的同一路径） |
| 生产库未被写入 | 运行前后对比字节数、表清单、行数 | **PASS**：1,925,120 B 不变；articles 110 / analyses 99 / runs 13 不变 |
| 生产库无摄取表 | `sqlite_master` 中无 `ingest_*` / `sec_*` / `eia_*` | **PASS** |
| 现有链路不引用本包 | `cli.py` 源码中不含 `ingest` / `sec_main` / `eia_main` | **PASS**（有测试断言） |
| 独立运行记录 | `ingest_runs` / `ingest_failures`，与 `runs` 无关 | **PASS** |

## 2. 失败分类

9 类失败均有对应实现与样本：`auth` / `rate_limit` / `not_found` / `server` / `timeout` / `schema` / `truncation` / `empty_result` / `rights`。
`rights` 在本阶段没有实际触发点（不涉及第三方内容），仅保留分类。

| 样本 | 期望分类 | 实测 |
|---|---|---|
| EIA-01（403 无 key） | `auth` | ✅ |
| EIA-04（429） | `rate_limit` | ✅（3 次有界重试后抛出） |
| EIA-05（500 非 JSON） | `server` | ✅ |
| EIA-06（超时） | `timeout` | ✅ |
| EIA-07（200 空集） | `empty_result` | ✅ |
| EIA-09（缺单位） | `schema` | ✅ 整批拒绝 |
| EIA-10（数值型） | 接受 + `schema_drift` | ✅ |
| EIA-11（缺 total） | `schema` | ✅ |
| EIA-12（分页不足） | `truncation` | ✅ |
| SEC-01/02/03/04（403/404/429/500） | 对应分类 | ✅ |
| SEC-05（超时） | `timeout` | ✅ |
| SEC-06（无事实） | 无错误 + `no_facts` | ✅ 未写 0 |
| SEC-07（units 非对象） | `schema` | ✅ |

`auth` 与 `not_found` **不重试**；`rate_limit` / `server` / `timeout` 有界重试（默认 3 次，指数退避）。

## 3. 并发与锁

| 场景 | 方法 | 结果 |
|---|---|---|
| 两个摄取进程同时写同一摄取库 | SEC（20 请求）与 EIA（2 请求）并行运行 | **PASS**：两次运行均 `success`，`ingest_failures` 中 **0 条** 含 `lock` |
| 与 RSS 日报并发 | 结构性隔离（不同文件），未同时运行生产日报 | **NOT_VERIFIED**（见 §6） |

重跑幂等：SEC 连续 2 次 → `sec_facts` 恒为 2,719；EIA 连续 3 次 → `eia_observations` 恒为 34、版本表恒为 34。

## 4. 实测发现的缺陷（已修复）

**gzip 未解码。** 首次真实 SEC 运行 20 个请求全部失败，错误分类为 `schema`，
细节为 `'utf-8' codec can't decode byte 0x8b`。原因：客户端声明 `Accept-Encoding: gzip`，
而 `urllib` 不自动解压。已在传输层加入 `Content-Encoding` 处理（gzip / deflate）。
修复后同样 20 个请求全部成功。

该缺陷无法由静态检查或本地样本发现——样本是已解压的 JSON。这是本轮唯一一次真实服务端行为纠正。

## 5. 超时与崩溃

| 项 | 状态 |
|---|---|
| 超时分类与重试 | **PASS**（本地注入 `socket.timeout`） |
| 对真实服务的超时注入 | **NOT_VERIFIED**（未故意制造） |
| 进程崩溃后的半写状态 | **NOT_VERIFIED**（未做 kill -9 类测试） |
| 事务边界 | 每个写入方法各自一个 `with connect()` 事务；跨表批量不是单事务 |

## 6. 未验证项

1. 与真实 RSS 日报**同时运行**的压力场景（本轮只做了两个摄取进程之间的并发）。
2. 崩溃恢复与部分写入回滚。
3. 429 的真实触发与配额边界。
4. 长时间运行的锁等待表现。

## 7. 结论

隔离的**结构性保证**成立：独立文件、独立进程、独立表、无代码引用，生产库指纹前后一致。
故障**分类与幂等**有实测证据。
但"故障完全隔离"的**压力与崩溃场景**尚未覆盖，因此条件 5 的 B 项判定为 **PARTIAL**，不升为 PASS_VERIFIED。

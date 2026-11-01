# SEC/EIA 独立通道 — 第一阶段实施总结

日期：2026-11-01
授权：G-D2（`docs/IMPLEMENTATION_AUTHORIZATION_2026-11-01.md`）
状态：**第一阶段实现完成；验收见 §3，部分项为 PARTIAL / NOT_VERIFIED，未整体通过**

---

## 1. 交付物

| # | 交付物 | 位置 |
|---|---|---|
| 1 | SEC 客户端与规范化 | `opportunity_radar/ingest/sec.py`、`labels.py` |
| 2 | EIA 客户端与规范化 | `opportunity_radar/ingest/eia.py` |
| 3 | 独立 schema / 初始化 | `opportunity_radar/ingest/store.py` |
| 4 | 配置模板（不含真实密钥） | `opportunity_radar/ingest/README.md` |
| 5 | 独立运行入口 | `opportunity_radar/ingest/sec_main.py`、`eia_main.py` |
| 6 | 单元测试与故障注入测试 | `tests/test_ingest_*.py`（60 项） |
| 7 | SEC 覆盖与标签映射报告 | `docs/PHASE1_SEC_COVERAGE_2026-11-01.md` |
| 8 | EIA 数据质量与分页验证报告 | `docs/PHASE1_EIA_QUALITY_2026-11-01.md` |
| 9 | 隔离、故障与并发报告 | `docs/PHASE1_ISOLATION_AND_FAULTS_2026-11-01.md` |
| 10 | 本总结 | 本文 |

基础设施：`config.py`（配置与生产库拒绝）、`http.py`（传输、gzip、限速、失败分类、有界重试）。

## 2. 实际运行

| 运行 | 结果 |
|---|---|
| EIA 月度 + 年度 | `success`，2 请求，34 条观测，0 错误 |
| SEC 十家公司 | `success`，20 请求，2,719 条事实，0 错误 |
| SEC / EIA 并发写同一摄取库 | 两者均 `success`，0 次锁错误 |
| 幂等重跑 | SEC 2 次、EIA 3 次，行数不变 |
| 全量测试 | **511 项通过**（423 原有 + 88 新增），4.90 s |

> 本文件为 R1–R3 阶段总结；R4/R5 收尾后的**权威验收结果**见 `docs/PHASE1_FINAL_ACCEPTANCE_2026-11-01.md`。

## 3. 验收

| 验收项 | 判定 | 依据 |
|---|---|---|
| SEC API 请求/响应/覆盖率/标签映射可追溯 | `PASS_VERIFIED` | 20 次真实请求；2,719 条带 accn/taxonomy/tag/unit/form；覆盖 10/10 收入、9/10 资本开支 |
| EIA 分页/facet/时间口径/快照 | `PASS_VERIFIED` | 对账与 EPM 完全一致；白名单硬约束；2026 只作部分年度 |
| 规范化（缺失/单位/期间/修订） | `PASS_VERIFIED` | 缺失写 NULL 不写 0；单位不符整批拒绝；28 条修订行保留原值 |
| 幂等性 | `PASS_VERIFIED` | 重复运行不产生重复记录 |
| 故障注入 | `PASS_VERIFIED` | 8 个要求场景全部覆盖（mock/fixture）；真实 429 未触发（按要求不主动制造） |
| 并发与超时 | `PARTIAL` | 两摄取进程并发、摄取与日报渲染并发、进程硬杀回滚均已实测；完整日报运行并发与真实超时未测 |
| 数据隔离 | `PASS_VERIFIED` | 生产库字节数、表清单、行数前后一致 |
| 现有系统回归 | `PASS_VERIFIED` | 511 项全绿；`--sample` 离线日报退出码 0 |
| 日报回归（dry-run） | `NOT_VERIFIED` | 未运行 `--dry-run`（会写生产库 `runs`），改用 `--sample` + 代码未改动的静态证据 |
| 条件 5-B（故障完全隔离） | `PARTIAL` | 结构性隔离成立且有并发证据；压力与崩溃场景未覆盖 |

**不能把 511 项测试全绿等同于接入验收通过**：它们证明的是现有链路未被破坏，不是新通道的数据正确性。

## 4. 与授权边界的核对

| 禁止项 | 状态 |
|---|---|
| 接入现有 LLM 分析 | 未触碰 |
| 参与评分 / 证据门槛 | 未触碰 |
| 进入日报或 `--render-only` | 未触碰 |
| 修改 cli/store/digest/render_html/evidence/scoring/scoring.toml/sources.local.csv | **均未修改**（mtime 保持 2026-10-26 / 2026-10-23） |
| 写入现有业务表 | 未发生（生产库指纹一致） |
| 扩大 EIA 范围 | 未扩大，白名单硬约束 |
| 扩大 SEC 公司范围 | 仅样本矩阵 10 家 |
| 启动 R0 / 接入 Ember / 改定时任务 | 均未发生 |

## 5. 已知缺陷与限制

1. ~~`subsequent_comparative` 未实现~~ → **已在 R4 修复**：四分类（original / amendment / subsequent_comparative / unknown），无 `filed` 时为 `unknown`。见 `docs/PHASE1_FINAL_ACCEPTANCE_2026-11-01.md` §2。
2. **YTD 季度差分未持久化**：六条件判断已实现并测过，但第一阶段不写派生值（避免构造合成 accn）。
3. **`rights` 分类无实际样本**：本阶段不涉及第三方内容。
4. **真实 429、真实超时、崩溃恢复**未测。
5. **实测暴露并修复了一个缺陷**：SEC 返回 gzip 时未解压，20 个请求全失败；修复后全通过。

## 6. 下一步（需另行授权）

- 补真实超时、429 与崩溃恢复测试，把条件 5-B 从 `PARTIAL` 推进到可判定。
- 决定是否让新通道进入 LLM/评分/日报——这是**另一次独立审批**，本阶段未触碰。

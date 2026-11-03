# 项目状态（2026-11-03）

**结论：R0–R6 已接通同一条每日生产管线；生产库已迁移到 schema v9；每日任务 08:00
运行日报并自动生成到期的周报/月报。** 本文件只写当前事实；历史批次过程见 Git 与
`docs/archive/`。

## 1. 生产事实

| 项 | 值 |
|---|---|
| 生产库 | `data/opportunity_radar.sqlite3` |
| schema | **v9**（31 张表，含 Opportunity 四表） |
| SHA-256（迁移 + dry-run 后） | `13009299…30e2` |
| 迁移备份 | `data/archive/final-migration-2026-11-03/pre-v9-backup.sqlite3`（v5，SHA-256 `30a55fef…e3f`） |
| 迁移演练 | `data/archive/final-migration-2026-11-03/migration-rehearsal.sqlite3`（v9，行数/外键/完整性通过） |

当前主要记录：

| 表 | 行数 | 说明 |
|---|---:|---|
| `articles` | 150 | 已绑定 `source_id` 150/150 |
| `analyses` | 132 | v5 结构化分析 |
| `events` / `event_articles` | 132 / 132 | 一文章一事件；无多文章事件 |
| `evidences` | 303 | 全部有来源、引文与定位 |
| `claims` | 301 | `skeleton` 299（全部 `unverifiable`）+ `n5` 2（`verified`） |
| `claim_evidence` | 305 | 每条 Claim 至少一条证据 |
| `entities` / `entity_mentions` | 25 / 81 | 组织、政府、地点；定位 81/81 |
| `event_links` | 5 | 全部 `candidate`，不合并 |
| `opportunities` | 58 | 全部 `signal_detected`，来自 evidence-backed B 种子 |
| `opportunity_links` | 603 | article/event/evidence/claim/entity 追溯 |
| `runs` | 18 | 含本次统一管线 dry-run |
| `deliveries` | 29 | 27 sent + 2 skipped |

独立库：

| 库 | 内容 |
|---|---|
| `data/ingest/opportunity_radar_ingest.sqlite3` | SEC 2,719 facts / EIA 34 observations / 2,753 evidences+claims |
| `data/pilot/source_pilot.sqlite3` | BLS 971 observations / Federal Register 17 documents；GDELT 0 |
| `data/claim-pipeline/node_runs.sqlite3` | N0–N5 追加式留存 |
| `data/economic/economic.sqlite3` | 11 datasets / 1,005 observations / 1,804 derived metrics |
| `data/quality/quality.sqlite3` | R6 指标快照 |

## 2. 统一生产管线

`cli` 在分析完成后自动调用 `pipeline.py`，顺序固定，每步写入 `stats.pipeline`：

| 步骤 | 模块 | 写入 | 状态 |
|---|---|---|---|
| R1 回填 | `unified_main.backfill_rss` | events/evidences/claims | 已接通；阻断失败触发 HOLD |
| N0–N5 数值主张 | `pipeline.run_claim_pipeline` | claims/evidences/claim_evidence | 已接通；默认每轮 8 篇，模型每篇 2 次调用 |
| 实体与提及 | `unified_main.seed_entities_and_mentions` | entities/entity_mentions | 已接通，单一 extract 路径 |
| 来源谱系 | `unified_main.apply_lineage` | evidences.source_family/independence | 已接通 |
| 事件候选 | `unified_main.build_event_candidates` | event_links(candidate) | 已接通，不合并 |
| 核验 | `verify.verify` | claim_verifications + claims.state | 已接通 |
| Opportunity 发现 | `opportunity_discovery.discover` | opportunities/links/revisions | 已接通，只建 `signal_detected` |
| 经济数据 | `economic.refresh` | economic.sqlite3 | 已接通，BLS/EIA → 观测/修订/派生 |
| 质量快照 | `quality.record` | quality.sqlite3 + reports/quality | 已接通 |

N0–N5 只处理本轮成功分析、且 N1 找到数字候选的文章；上限、跳过数与每篇状态写入
`stats.pipeline.claim_pipeline`。未通过的 Claim 不写生产表，原因保留在管线结果。

## 3. R0–R6 验收矩阵

| 需求 | 实现 | 证据 | 状态 |
|---|---|---|---|
| R0 重试/熔断/覆盖率/HOLD | `analyzer.py`、`publication.py`、`cli.py` | 单元测试 + `tools/e2e_verify.py` 基线 + 生产 run 15/16 | **PASS_VERIFIED（历史真实运行）** |
| R1 Event/Evidence/Claim | `unified.py`、`linking.py`、`unified_main.py` | 生产库 117 events / 253 evidences / 253 claims；审计 PARTIAL（0 ERROR） | **PASS_VERIFIED** |
| R2 主张核验 | `verify.py`、`claim_contract.py`、N0–N5 | 全量 1021 测试；真实 BEA 文章 N5 8 条 Claim 全部 `verified` | **PASS_VERIFIED** |
| R2 v7 提示词 | `prompts/analyst_v7.md` | 影子运行，未切换 | **PARTIAL（影子）** |
| R3 编辑优先级 | `scoring.py` P0–P3/REJECT | 单元测试 + 日报排序字段 | **PASS_STATIC** |
| R4 周报/月报 | `period_report.py`、`cli --period` | 生成 weekly/monthly 文本+JSON；按文章发布时间取数 | **PASS_VERIFIED（生成）** |
| R5 经济数据引擎 | `economic.py` | 11 datasets / 1,005 observations / 1,804 derived；修订追加测试 | **PASS_VERIFIED（同步/派生）** |
| R6 质量与回测 | `quality.py` | 指标快照 + 30/90 天回测（18 runs，77.78% success）；版本对比；聚类/阅读指标 `NOT_MEASURED` | **PARTIAL（可测项 PASS）** |
| Opportunity 数据库 | `opportunity.py`、`opportunity_discovery.py` | 48 行 `signal_detected`，489 links，48 revisions | **PASS_VERIFIED（signal 层）** |
| Source Pilot | `pilot/` | FR 17 / BLS 971；GDELT 429 | **PARTIAL（GDELT 阻断）** |
| 每日自动化 | `run-digest.ps1 --period auto` | 计划任务 08:00；180 分钟上限 | **PASS_VERIFIED（配置）；真实 dry-run 见 §4** |

## 4. 真实验证

- **迁移演练**：v5 副本 → v9；行数、`PRAGMA integrity_check`、`foreign_key_check` 全部通过。
- **生产迁移**：v5 → v9，备份完整性通过；138/138 `source_id`；220 条旧 skeleton
  `period` 置空（新增 33 条 skeleton 共 253）；24 实体 / 69 mention / 4 candidate links。
- **审计**：`unified_main audit` 对生产库返回 **PARTIAL**，0 个 ERROR；WARN 为
  15 条谱系仅 `declared`、38 个事件无证据（均为 v4 分析跳过）。
- **N0–N5 真实验证**：BEA Personal Income 文章经真实 CPU-only 模型完成 N0–N5，
  8 条 Claim / 7 条 Evidence 写入隔离副本，`verify` 后 **8/8 verified**，0 rejected。
- **模型吞吐**：CPU-only（`-ngl 0`，64K）实测 **10.85 tok/s**；GPU/MoE 分层实测
  0.8 tok/s，已改回 CPU-only。
- **依赖**：`acceptance` 8/8（config、sources、FreshRSS 27 feeds、model、sqlite、
  report、mail_config、scheduler）。
- **测试**：全量 **1023 项通过**（1 项环境跳过）。
- **真实每日 dry-run**：运行 18（16:29–16:56）完成；取 20 / 分析 11 / 失败 0 / 覆盖率 1.0 / PASS；统一管线 9 步全部成功；N0–N5 处理 8 篇，写入 2 条 Claim；Opportunity +10；质量快照写入；未发送邮件（dry-run）。

## 5. 当前限制（不掩盖）

1. **事件聚合**：117 events / 117 articles，0 个多文章事件；独立来源佐证 0；转载
   `syndication_group` 仍为空。这是来源覆盖与正文相似度问题，不是模型问题。
2. **N2/N3 语义参考**：只有 10 篇人工参考；不能外推到全部语料。Google/Intel title-only
   与 Personal Income 0.2% DPI 仍有已知缺口。
3. **v7 提示词**：仍是影子；生产分析器是 v6。N0–N5 使用 r2-v4 契约。
4. **Opportunity**：只有 `signal_detected`；problem/buyer 是模型提示，不是确认事实；
   58 行没有经过人工 `problem_supported`/`buyer_identified`/`payment_verified` 提升。
5. **来源覆盖**：15 个启用 RSS 源；SEC/EIA 独立；GDELT 仍被 429 阻断；Federal Register
   与 BLS 仍是独立 Pilot，不进入日报。
6. **R6**：事件聚类 precision/recall 无可信标注基准，标 `NOT_MEASURED`；N1 benchmark
   是冻结静态结果，不是每日重跑。
7. **全文抓取**：所有来源 `full_text_fetch=none`；E2 只来自已声明 `full_text` 的来源。
8. **邮件**：HOLD 不发订阅/告警邮件；失败无自动重试。

## 6. 运行方式

- 计划任务：`OpportunityRadarDaily`，每天 08:00，180 分钟上限，`--period auto`。
- 服务：FreshRSS `127.0.0.1:8088`（Docker Compose）；模型 `127.0.0.1:8080/v1`
  CPU-only、64K、单 slot；SMTP 163:465 SSL。
- 生产迁移：`unified_main db-migrate --apply --backup <file>`；业务 CLI `migrate=False`，
  schema 低于 v9 直接报错。
- 日报：`reports/latest-digest.{txt,html}` + `reports/archive/YYYY/MM/DD/`。
- 周报/月报：`reports/weekly-*` / `reports/monthly-*`；经济库与质量库见 §1。

## 7. 文档

权威文档只剩：`README.md`、`docs/PRD.md`、`docs/ARCHITECTURE.md`、`docs/PROJECT_STATUS.md`、
`docs/OPERATIONS.md`、`docs/CLAIM_PIPELINE.md`、`docs/EVIDENCE_AND_LANES.md`、
`docs/SOURCE_POLICY.md`、`docs/SECURITY_PRIVACY_SOURCE_COMPLIANCE.md`、
`docs/E2E_VERIFICATION.md`。已取代的开发路线、Batch 说明、Pilot 研究与旧模块文档移到
`docs/archive/superseded-2026-11-03/`。

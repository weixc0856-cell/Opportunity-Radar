# 项目状态（2026-11-03）

**结论：R0–R6 已接通同一条每日生产管线；生产库已迁移到 schema v9；每日任务 06:00
运行日报并自动生成到期的周报/月报。** 本文件只写当前事实；历史批次过程见 Git 与
`docs/archive/`。

## 1. 生产事实

| 项 | 值 |
|---|---|
| 生产库 | `data/opportunity_radar.sqlite3` |
| schema | **v9**（31 张表，含 Opportunity 四表） |
| SHA-256（run 19 结束后） | `c6f19cf2…cad16` |
| 迁移备份 | `data/archive/final-migration-2026-11-03/pre-v9-backup.sqlite3`（v5，SHA-256 `30a55fef…e3f`） |
| 迁移演练 | `data/archive/final-migration-2026-11-03/migration-rehearsal.sqlite3`（v9，行数/外键/完整性通过） |

当前主要记录：

| 表 | 行数 | 说明 |
|---|---:|---|
| `articles` | 153 | 已绑定 `source_id` 153/153 |
| `analyses` | 135 | v5 结构化分析（V7 提示词） |
| `events` / `event_articles` | 135 / 135 | 一文章一事件；无多文章事件 |
| `evidences` | 338 | 全部有来源、引文与定位 |
| `claims` | 323 | `skeleton` 321（全部 `unverifiable`）+ `n5` 2（`verified`） |
| `claim_evidence` | 346 | 每条 Claim 至少一条证据 |
| `entities` / `entity_mentions` | 27 / 87 | 组织、政府、地点；定位 87/87 |
| `event_links` | 5 | 全部 `candidate`，不合并 |
| `opportunities` | 66 | 全部 `signal_detected`，来自 evidence-backed B 种子 |
| `opportunity_links` | 684 | article/event/evidence/claim/entity 追溯 |
| `runs` | 19 | 含 V7 全管线 dry-run（run 19） |
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

每日任务在 CLI 之前先运行 `deploy/windows/run-sources.ps1`：SEC、EIA、Federal Register、BLS
各自写入独立库（`data/ingest/`、`data/pilot/`），不写 RSS 业务表、不进入 LLM 与日报正文；
GDELT 记录为 `frozen`（HTTP 429），不自动重试。每个源的状态写入
`reports/sources/latest.json`，失败或未配置会打印在日报附录的“外部数据源同步”一行，并写入
`scheduler-run.log`。SEC 目前缺少 `OR_INGEST_SEC_USER_AGENT`，状态是 `not_configured`。

N0–N5 只处理本轮成功分析、且 N1 找到数字候选的文章；上限、跳过数与每篇状态写入
`stats.pipeline.claim_pipeline`。未通过的 Claim 不写生产表，原因保留在管线结果。

## 3. R0–R6 验收矩阵

| 需求 | 实现 | 证据 | 状态 |
|---|---|---|---|
| R0 重试/熔断/覆盖率/HOLD | `analyzer.py`、`publication.py`、`cli.py` | 单元测试 + `tools/e2e_verify.py` 基线 + 生产 run 15/16 | **PASS_VERIFIED（历史真实运行）** |
| R1 Event/Evidence/Claim | `unified.py`、`linking.py`、`unified_main.py` | 生产库 117 events / 253 evidences / 253 claims；审计 PARTIAL（0 ERROR） | **PASS_VERIFIED** |
| R2 主张核验 | `verify.py`、`claim_contract.py`、N0–N5 | 全量 1043 测试；真实 BEA 文章 N5 8 条 Claim 全部 `verified` | **PASS_VERIFIED** |
| R2 v7 提示词 | `prompts/analyst_v7.md` | 生产分析器；V6 保留回滚；run 19 以 V7 完成全管线 dry-run | **PASS_VERIFIED** |
| R3 编辑优先级 | `scoring.py` P0–P3/REJECT | 单元测试 + run 19 日报按 P0/P1 排序并打印优先级依据 | **PASS_VERIFIED（排序）** |
| R4 周报/月报 | `period_report.py`、`cli --period` | 生成 weekly/monthly 文本+JSON；按文章发布时间取数 | **PASS_VERIFIED（生成）** |
| R5 经济数据引擎 | `economic.py` | 11 datasets / 1,005 observations / 1,804 derived；修订追加测试 | **PASS_VERIFIED（同步/派生）** |
| R6 质量与回测 | `quality.py` | 指标快照 + 30/90 天回测（18 runs，77.78% success）；版本对比；聚类/阅读指标 `NOT_MEASURED` | **PARTIAL（可测项 PASS）** |
| Opportunity 数据库 | `opportunity.py`、`opportunity_discovery.py` | 48 行 `signal_detected`，489 links，48 revisions | **PASS_VERIFIED（signal 层）** |
| Source Pilot | `pilot/` | FR 17 / BLS 971；GDELT 429 | **PARTIAL（GDELT 阻断）** |
| 每日自动化 | `run-digest.ps1 --period auto` | 计划任务 06:00；180 分钟上限 | **PASS_VERIFIED（配置）；真实 dry-run 见 §4** |

## 4. 真实验证

- **迁移演练**：v5 副本 → v9；行数、`PRAGMA integrity_check`、`foreign_key_check` 全部通过。
- **生产迁移**：v5 → v9，备份完整性通过；138/138 `source_id`；220 条旧 skeleton
  `period` 置空（新增 33 条 skeleton 共 253）；24 实体 / 69 mention / 4 candidate links。
- **审计**：`unified_main audit` 对生产库返回 **PARTIAL**，0 个 ERROR；WARN 为
  15 条谱系仅 `declared`、38 个事件无证据（均为 v4 分析跳过）。
- **N0–N5 真实验证**：BEA Personal Income 文章经真实 CPU-only 模型完成 N0–N5，
  8 条 Claim / 7 条 Evidence 写入隔离副本，`verify` 后 **8/8 verified**，0 rejected。
- **模型吞吐**：CPU-only（`-ngl 0`，64K）实测 **10–13 tok/s**（run 19 全程 10.5–13.2）；
  GPU/MoE 分层实测 0.8 tok/s，已改回 CPU-only。run 19 总时长 54 分钟（20 篇分析 + N0–N5 8 篇），
  在计划任务 180 分钟上限内。
- **依赖**：`acceptance` 8/8（config、sources、FreshRSS 27 feeds、model、sqlite、
  report、mail_config、scheduler）。
- **测试**：全量 **1043 项通过**（1 项环境跳过，2026-11-03）。
- **端到端（2026-11-03）**：`tools/e2e_verify.py --limit 3` → `pass`。happy 运行：3 篇分析、
  覆盖率 1.0、PASS、文本/HTML/归档/哈希/计数全部一致；fault 运行（非法 category）：3 条失败
  入库、覆盖率 0、HOLD、0 投递、报告明确写出失败、退出码 1。E2E 同时验证了“缺失数据库按当前
  schema 创建”的路径。
- **真实每日 dry-run**：运行 18（16:29–16:56）完成；取 20 / 分析 11 / 失败 0 / 覆盖率 1.0 / PASS。
- **V7 全管线 dry-run（run 19，18:01–18:55）**：V7 生产提示词；取 20 / 分析 20 / 失败 0 /
  覆盖率 1.0 / PASS；9 个管线步骤全部 ok，0 警告、0 阻断；R1 回填 35 Evidence / 22 Claim；
  N0–N5 处理 8 篇（1 篇已处理、1 篇无数字候选、0 失败），本批 8 篇均为非经济数字段落，
  未产出 r2-v4 Claim；实体 70 条 mention；Opportunity 新建 8、已有 51；经济库同步成功；
  质量快照 `PASS_MEASURED`；未发送邮件（dry-run），退出码 0。

### 邮件版与完整版（2026-11-12）

- 邮件只发送第一至七节与附录说明。用生产库 `--render-only` 实测：邮件版 9.3 KB，完整版 93.6 KB，
  邮件正文不含附录 A/B/C。
- 附录按 `report_hash` 写入 SQLite `report_sections`（首次保存时自建表，不改 schema 版本），
  归档同时保存 `*.email.txt` / `*.email.html`；管理台 `GET /api/report/sections` 可读。
- 测试：全量 1069 项通过（1 项环境跳过，2026-11-12）。

### 发现层与展示层分离

`display.py` 为 Claim / Opportunity / 关联计算 `L0–L3` 展示等级与原因；日报在“数据概览”之后
固定输出“待观察信号（弱信号 / 未确认）”：低置信 Opportunity、有数字候选但无 r2-v4 Claim 的
文章、未确认的事件候选关联，以及 N0–N5 上限外的文章数。发现层不删除任何条目；该区块不改变
评分、发布门禁或存储。质量快照新增 `display` 计数（signal_detected、候选事件关联、有定位但
未核验的 Claim），用于检查“有用信息在哪一层被降级”。

## 5. 当前限制（不掩盖）

1. **事件聚合**：135 events / 135 articles，0 个多文章事件；独立来源佐证 0；转载
   `syndication_group` 仍为空。这是来源覆盖与正文相似度问题，不是模型问题。
2. **N2/N3 语义参考**：只有 10 篇人工参考；不能外推到全部语料。Google/Intel title-only
   与 Personal Income 0.2% DPI 仍有已知缺口。
3. **提示词**：生产为 v8（v7 + 面向人的字段一律简体中文，逐字引文保持原文）；
   v7 与 v6 保留回滚。N0–N5 使用 r2-v4 契约。
4. **Opportunity**：只有 `signal_detected`；problem/buyer 是模型提示，不是确认事实；
   66 行没有经过人工 `problem_supported`/`buyer_identified`/`payment_verified` 提升。
5. **来源覆盖**：29 个启用源（2026-11-08 经合规核验新增 14 个：BLS、Census、Google×3、
   Hugging Face、Microsoft×2、AWS、TechCrunch、MIT Technology Review、AMD IR、arXiv×2），
   每轮取数 40；SEC/EIA 独立；GDELT 仍被 429 阻断；Federal Register 与 BLS 每日同步到独立
   Pilot 库，但数据不进入日报正文。SEC 缺少 `OR_INGEST_SEC_USER_AGENT`，状态 `not_configured`。
   核验记录见 `docs/SOURCE_COMPLIANCE_REVIEW_2026-11-08.md`。
6. **政策线为空（已知缺口）**：注册表内唯一政策源为中国人民银行，只有 HTML 栏目页且
   `robots.txt` 为 `Disallow: /`，不可抓取。候选已核验但**未启用**：欧盟委员会新闻稿 RSS
   （CC BY 4.0）、UK GOV.UK 公告 Atom（OGL v3.0）可直接批准；中国政府网 RSS 条款限制较严，
   需人工确认。在新增并批准之前，日报的政策监管内容会一直为 0，报告不以此掩盖。
7. **R6**：事件聚类 precision/recall 无可信标注基准，标 `NOT_MEASURED`；N1 benchmark
   是冻结静态结果，不是每日重跑。
8. **全文抓取**：所有来源 `full_text_fetch=none`；E2 只来自已声明 `full_text` 的来源。
9. **邮件**：HOLD 不发订阅/告警邮件；失败无自动重试。
10. **主张结构**：323 条 Claim 中 321 条是 R1 `skeleton`（无 period、无数值，全部
   `unverifiable`），只有 2 条是 N0–N5 的 `n5` Claim。run 19 的 8 篇 N0–N5 输入都是
   非经济数字段落（HN/论坛/版本号），未产出 r2-v4 Claim。数值主张依赖 RSS 摘要本身包含
   数字；全文抓取仍全部关闭。

## 6. 运行方式

- 计划任务：`OpportunityRadarDaily`，每天 06:00，180 分钟上限，`--period auto`。
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

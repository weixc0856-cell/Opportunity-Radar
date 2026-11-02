# Opportunity Radar

本地优先的商业与产业情报系统。FreshRSS 管理订阅，Python 从 Fever API 取文章，本地
`llama-server` 做结构化初筛，SQLite 保存证据与运行记录，输出中文日报（文本 + HTML + JSON）。

三条链路，互不影响：

| 链路 | 入口 | 数据 | 状态 |
|---|---|---|---|
| RSS 日报 | `python -m opportunity_radar.cli` | `data/opportunity_radar.sqlite3` | 每日运行，带发布门禁 |
| SEC / EIA 结构化摄取 | `python -m opportunity_radar.ingest.sec_main`、`eia_main` | `data/ingest/opportunity_radar_ingest.sqlite3` | 独立进程，不进入日报 |
| 统一事件模型 | `python -m opportunity_radar.unified_main …` | 两库各自的 R1 表 | 已回填，日报已使用事件视图 |

运行期只依赖 Python 标准库（`sqlite3`、`urllib`、`tomllib`、`html`、`json`），
`pyproject.toml` 声明的依赖为空。

## 快速开始（Windows PowerShell）

1. 安装 Docker Desktop（WSL2）与 Python 3.11+，`py -3 -m venv .venv`。
2. `docker compose up -d`，在 `http://127.0.0.1:8088` 完成 FreshRSS 初始化并启用 Fever API。
3. 复制 `.env.example` 为 `.env`，填写 FreshRSS、模型、SMTP。来源登记放在
   `config/sources.local.csv`（`.gitignore` 排除），由 `OR_SOURCES_PATH` 指向；
   仓库模板 `config/sources.csv` 全部禁用。
4. 逐个核实来源的所有者、条款、内容保存要求后，填写 `permission_status=approved`、
   `reviewed_at`、`freshrss_feed_id`，设 `enabled=true`。`python -m opportunity_radar.source_audit`
   检查登记完整性。
5. 启动模型：`.\deploy\windows\start-model.ps1`（参数在脚本顶部；`-Foreground` 前台运行）。
   默认 64K 上下文 + q8_0 KV（本机 8 GB 显卡实测约 7.3 GB）；GPU offload 与 CPU MoE 分层沿用原配置。
   交互式启动器 `D:\AI\start_server.bat` 的默认档位也已改为 64K。
6. 试跑：`python -m opportunity_radar.cli --dry-run`。真实运行：`.\deploy\windows\run-digest.ps1`。
7. 注册每日任务：`.\deploy\windows\install-task.ps1`。
8. 测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests`。

## 数据流

```
FreshRSS ──Fever API──> articles ──> llama-server ──> analyses / analysis_sections
                                                        │
                                      评分（A/B/C 通道，config/scoring.toml）
                                                        │
                              事件归并（R1）──> events / evidences / claims
                                                        │
                                   发布门禁（覆盖率 + 熔断）──> PASS / HOLD
                                                        │
                          reports/latest-digest.{txt,html} + archive/*.items.json ──> 邮件

SEC XBRL ─┐
EIA API  ─┴─> 独立摄取库（原始快照 + 规范化事实）──> R1 claims/evidences（同库，不跨库）
```

## 日报

- 输出 `reports/latest-digest.txt`、`latest-digest.html`，并按 `reports/archive/YYYY/MM/DD/`
  归档文本、HTML、`.items.json`（分析快照）与 `.manifest.json`（运行 ID、报告哈希、统计）。
  `--render-only` 只刷新 latest，不新增归档，也不写数据库。
- 结构：执行摘要 → 三个编辑通道（A 商业/科技/经济、B 商业机会、C 技术观察）→ 数据概览 → 附录。
- **事件视图**：同属一个事件的报道只占一张卡片。卡片下依次给出：
  - `事件结构`：同事件报道 N 篇 · 报道来源 N 个 · 来源族 N 个 · 独立佐证：是/否（单篇单族时不打印）；
  - `事实主张`：事件关联的主张，逐条标注类型（事实/推断/…）与核验状态，并给出证据 ID、定位
    （`summary@起-止`）与来源 ID；超过两条时提示"另有 N 条主张，见归档 JSON"；
  - `候选关联`：条数、状态分布与依据，明确写明"未经确认，不作为已发生的事实"；
  - `同事件其他报道`：其余报道的媒体、标题与链接。
- 评分是确定性规则：先按来源声明的 `editorial_lanes` 与内容类型路由通道，再用该通道自己的
  0–5 分组件加权；权重、阈值、晋升门槛统一读自 `config/scoring.toml`。通道之间分数不可比较。
- 证据等级是显式枚举：`title_only` / `unlocated_quotes`（E0）、`rss_excerpt_only`（E1）、
  `full_text_verified` / `primary_source_located` / `multi_source_coverage`（E2）。E0 不进简报。
  只有来源登记声明 `full_text` 且人工复核过的来源才能进入 E2。
- `status` 是证据与评分的结论，`distribution`（`included` / `deferred`）只表示本期是否进入阅读区；
  来源单期配额只会让条目 deferred，不会改写成 filtered。

## 发布门禁（R0）

- 传输失败有界重试：连接类 3 次、超时 1 次、429 遵守 `Retry-After`（上限可配）；普通 4xx 不重试。
  `attempts` 记录实际请求次数（含首次）。
- 连接级失败后复查 `/health`；连续 3 次连接级失败即熔断，剩余文章记为 `not_attempted`。
- 覆盖率 = 成功分析 / 进入分析。`PASS ≥ 0.8`，`0.5–0.8` 为 `PASS_WITH_LIMITATIONS`（照常发送，
  报告披露覆盖率与失败原因），`< 0.5` 或运行级完整性异常为 `HOLD`。
- `HOLD` 不发送订阅邮件、不发告警邮件，本地报告与运行记录保留在 `runs`。
- 运行记录含 `publication_status`、`coverage`、`failed_causes`、`not_attempted`；
  `analysis_failures` 含 `cause` 与 `attempts`。

## SEC / EIA 独立通道

- `python -m opportunity_radar.ingest.sec_main`：10 家公司的 XBRL 事实，保留 accession、申报关系
  （original / amendment / subsequent_comparative / unknown）与选择状态。
- `python -m opportunity_radar.ingest.eia_main`：单一 route / 指标 / facet 组合的月度与年度发电量。
- 独立数据库、独立入口、独立运行记录；`cli.py` 不引用该包，SEC/EIA 数据不进入日报。
- 失败分 9 类（auth / rate_limit / not_found / server / timeout / schema / truncation /
  empty_result / rights），限速 ≤5 req/s，快照按内容哈希去重。

## 统一事件模型（R1）

```
python -m opportunity_radar.unified_main rss        # 文章 -> 事件、证据、主张骨架
python -m opportunity_radar.unified_main sec        # SEC 事实 -> 证据 + 结构化主张
python -m opportunity_radar.unified_main eia        # EIA 观测 -> 证据 + 结构化主张
python -m opportunity_radar.unified_main entities   # 公司实体与提及
python -m opportunity_radar.unified_main links --ingest-db <摄取库>   # 候选关联
python -m opportunity_radar.unified_main lineage    # 来源谱系 -> 证据
python -m opportunity_radar.unified_main report     # 各表计数与缺口
```

主张核验（R2 规则，离线运行）：

```
python -m opportunity_radar.verify --db <库> [--dry-run] [--limit N]
python -m opportunity_radar.verify --db <库> --summary          # 状态与支持关系分布
python -m opportunity_radar.verify --db <库> --audit            # 哪些检查执行了、哪些跳过，按来源分组
python -m opportunity_radar.verify --db <库> --conflicts        # 记录到的冲突，双方数值与依据
```

结构化提示词 `prompts/analyst_v7.md` 已存在，但**只在影子运行中使用**（`tools/shadow_v7.py`），
生产仍用 v6。`verify` 模块也尚未在生产库运行，未接入日报或门禁（待 G6）。

主张提取流水线（离线、只读）：

```
python tools/run_n1.py --limit 50
python tools/run_n1.py --limit 600 --benchmark data/r2-shadow/benchmark.json   # 人工基准召回
python tools/run_n2_n3.py --limit 50 --n3-limit 15                            # N2/N3 真实模型
python tools/run_n2.py --limit 20                                             # 仅 N2
python tools/run_n3.py --limit 20                                             # 仅 N3（需已留存 N2）
python tools/run_n4_n5.py --limit 50                                          # N4/N5（无模型调用）
python tools/run_n4_n5.py --fixture data/claim-pipeline/n2n3-fixtures.json --limit 2
python tools/run_n4.py --limit 20                                             # 仅 N4
python tools/run_n5.py --limit 20                                             # 仅 N5（需已留存 N4）
python tools/eval_numeric_tools.py      # 识别器对比，需安装 recognizers-text 的解释器
```

N0 处理标题与系统持有的完整 RSS 正文（正文抓取关闭），输出段落/句子 ID、全文偏移与原始 HTML 偏移；
N1 输出原子候选（类型、原始表达、全文位置、数量级/单位/币种分离）和复合表达组
（range / from_to / increase_decrease / comparison / temporal_comparison）。
N2 用本地 Qwen3-30B-A3B 判定每个候选的主体/指标/主张状态，N3 判定水平/变化/比较/区间等关系
并对每个 claim_value 给出处置；两者输出都经过程序校验（ID、枚举、覆盖、证据定位、比较口径守卫）。
N4 确定性地标准化数值/单位/数量级/币种/期间/baseline；N5 检查每个 N1 候选的处置并组装
r2-v4 影子 Claim，证据回指 N0，缺失期间/比较口径只记录不补造。
节点运行写入独立的追加式留存（`data/claim-pipeline/node_runs.sqlite3`），不写生产库；
影子 Claim 不进入生产 Claim 表、日报或核验。七夹具与 50 篇真实 RSS 影子运行已完成（Batch 12），影子 Claim 仍非已核实事实。
契约见 `docs/CLAIM_PIPELINE.md`。

核验把每条主张与它引用的证据对照：数值是否在引文里、单位是否同族、期间是否与证据记录一致、
百分比与百分点是否混用、比较口径是否与措辞矛盾。结果写入 `claim_verifications`（追加式），
并更新主张状态。`verified` 的含义是"主张与其证据一致"，不是"该事实为真"；散文骨架主张一律
`unverifiable`；有数值但无单位的主张也按 `unverifiable` 处理。主张契约 `r2-v4` 支持
`advance_estimate` 等修订状态与年度区间（`1997-2024`），并把模型的原始表达保留在
`unit_raw` / `period_raw` / `revision_raw` 里。**核验尚未在生产库运行，也未接入日报或门禁**（待 G6）。

- 六张表：`events`、`event_articles`、`evidences`、`claims`、`claim_evidence`、`event_corrections`；
  实体层：`entities`、`entity_aliases`、`entity_mentions`、`event_links`。
- 标识符是内容哈希，重复运行不产生第二条记录。
- 事件合并只有两条规则：规范化 URL 相同，或规范化标题相同且在 72 小时窗口内。其余是不同事件；
  共享关键词不合并。
- 候选关联（`event_links.status='candidate'`）从不自动合并；接受或拒绝写追加式 `event_corrections`。
- RSS 主张 `extractor='skeleton'`：v5 提示词只产出散文事实，数值字段为空，`verification_state`
  一律 `unverified`。SEC/EIA 主张 `extractor='structured'`，带数值、单位、期间与申报关系。

## 来源治理与谱系

- `config/sources.csv`：仓库模板，47 行，全部禁用。
- `config/sources.local.csv`：本机登记（`.gitignore` 排除）。字段含 `editorial_lanes`、
  `intelligence_lines`、`content_access_level`、`source_cap`、`full_text_fetch`。
- `config/source_lineage.csv`：来源谱系（入库，可 diff）——`source_family`、`lineage_kind`、
  `syndication_group`、`independence`、`basis`、`basis_source`、`review_status`。
  当前 15 个启用源 → 12 个来源族；BBC、NYT、Hacker News 各自的多个 feed 分别是同一族。
- 独立佐证 = 至少两个来源族，且这些族有已记录的独立性判断。未知来源不计入；共享联合发布组
  的不同机构只算一个单元。没有任何证据时 `syndication_group` 留空。

## 结构化数据与页面监测

- `config/datasets.csv` + `opportunity_radar/datasets.py`：时间序列数据集的独立登记，
  `python -m opportunity_radar.datasets --check` 探测最新期间；许可未核对的数据集保持 `blocked`。
- `config/page_watch.csv` + `opportunity_radar/page_monitor.py`：无 Feed 的官方页面低频变更监测，
  只保存链接与标题，先读 robots.txt，401/403/429 不重试，不执行 JavaScript。

## 运行与运维

- 计划任务：`.\deploy\windows\install-task.ps1`（每日 08:00）。启动器 `run-digest.ps1` 记录运行 ID、
  各阶段、CLI 进程号与退出码；启动器被外部终止时会留下 `reports/launcher-inflight.json`，
  下次运行会报出这条未完成记录。任务的电源设置显式关闭了"使用电池时停止"。
- 管理后台：`.\deploy\windows\start-admin.ps1` → `http://127.0.0.1:8090`，只监听回环地址，
  没有多用户认证。
- 邮件：端口 465 用 `OR_SMTP_SECURITY=ssl`，587 用 `starttls`；需要授权码而不是登录密码。
  逐收件人发送并记录在 `deliveries`；同一报告幂等，不重复发送。
- 验收：`python -m opportunity_radar.acceptance`；端到端与故障注入：
  `python tools\e2e_verify.py --limit 3 [--fault-mode schema|server|reset|refuse]`。

## 约束

- 未确认许可的来源保持禁用；不绕过登录、验证码、付费墙。
- 模型只做初筛：分数表示相对优先级，不是结论；营收、市场规模、法律判断必须核对原始来源。
- 邮件只含摘要与原始链接，不复制全文。
- `.env`、数据库、报告与日志不提交。

## 文档索引

| 文档 | 写什么 |
|---|---|
| `CLAUDE.md` | 工作规则：原则、边界、阶段纪律 |
| `docs/PRD.md` | 产品定义：用户、通道、功能需求、数据模型、质量框架 |
| `docs/IMPLEMENTATION_PLAN.md` | 开发路线：阶段、依赖、验收要点、审批门 |
| `docs/PROJECT_STATUS.md` | 当前事实：已交付、数据库现状、缺口 |
| `docs/ARCHITECTURE.md` | 模块职责与数据流 |
| `docs/OPEN_ISSUES.md` | 未解决的工程问题 |
| `docs/OPERATIONS.md` | 运行、排障、任务计划与归档 |
| `docs/EVIDENCE_AND_LANES.md` | 证据等级与通道评分规则 |
| `docs/SOURCE_POLICY.md` | 来源准入、治理字段、正文获取 |
| `docs/FULL_TEXT_FETCH.md`、`docs/PAGE_MONITORING.md`、`docs/DATASETS.md` | 三个子系统：正文抓取、页面监测、数据集登记 |
| `docs/E2E_VERIFICATION.md` | 端到端与故障注入 |
| `docs/SECURITY_PRIVACY_SOURCE_COMPLIANCE.md` | 安全、隐私与合规清单 |
| `docs/LOCAL_DAILY_ARCHIVE.md` | 本地日报归档说明 |
| `docs/archive/` | 历史记录：审计、设计评审、授权、验收（冻结） |

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

普通业务 CLI 以 `migrate=False` 打开 store：数据库版本低于代码要求时直接报错并提示
`db-migrate`，不会静默迁移。`audit`、`report`、`--render-only` 保持只读；`db-migrate --apply`
必须提供备份文件，迁移失败即停止。

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
   - 本地 LLM 只用 **8080** 一个端口。若 8080 已被正在开发的项目占用，脚本会等待并在日志 `reports\model-defer.log` 记录，不会另开端口或 kill 别人的进程。
   - 定时任务跑完后会停止自己启动的 llama-server，把 8080 释放给下一个使用者。
   项目实例默认 **CPU-only**（`-ngl 0`，64K，约 19 GB 内存），实测 10–13 tok/s；
   8 GB A750 留给 ComfyUI。GPU/MoE 分层模式在同一机器上实测约 0.8 tok/s，不要用于定时任务。
6. 试跑：`python -m opportunity_radar.cli --dry-run`。真实运行：`.\deploy\windows\run-digest.ps1`。
7. 注册每日任务：`.\deploy\windows\install-task.ps1`。
8. 测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests`。

## 数据流

```
FreshRSS ──Fever API──> articles ──> llama-server（CPU-only，64K）
                                        │
                         analyses / analysis_sections
                                        │
                 评分（A/B/C 通道 + R3 编辑优先级 P0–P3/REJECT）
                                        │
        ┌─────────────────────── 统一生产管线（pipeline.py）───────────────────────┐
        │ R1 回填 events/evidences/claims → N0–N5 数值主张 → 实体/谱系              │
        │ → 事件候选 → verify 核验 → Opportunity signal_detected → 经济引擎 → 质量  │
        └───────────────────────────────────────────────────────────────────────────┘
                                        │
                   发布门禁（覆盖率 + 熔断）──> PASS / HOLD
                                        │
        reports/latest-digest.{txt,html} + archive/*.items.json/manifest.json
                                        │
                    每日日报 ──> 邮件；每周周报、每月月报（--period auto）

SEC XBRL / EIA ──> 独立摄取库 ──> 经济数据引擎（data/economic/economic.sqlite3）
Federal Register / BLS Pilot ──> 独立 Pilot 库 ──> 经济数据引擎
```

## 日报

- 输出 `reports/latest-digest.txt`、`latest-digest.html`，并按 `reports/archive/YYYY/MM/DD/`
  归档文本、HTML、`.items.json`（分析快照）与 `.manifest.json`（运行 ID、报告哈希、统计）。
  `--render-only` 只刷新 latest，不新增归档，也不写数据库。
- 结构：执行摘要 → 三个编辑通道（A 商业/科技/经济、B 商业机会、C 技术观察）→ 数据概览 → 附录。
- **事件视图**：同属一个事件的报道只占一张卡片。事件证据状态分为 `EVIDENCE_BACKED`、
  `NO_EVIDENCE`、`INSUFFICIENT_EVIDENCE`；无 Evidence 的事件仍保留，但卡片明确显示“证据状态：无证据
  （仅线索，不作为已核实事实）”。文本、HTML 和邮件共用同一 `event_summary_lines`，归档 JSON 保留原始
  `event.evidence_status` 和 `event_context`。事件上下文不可用时，输出明确区分 `NOT_FOUND`、`UNAVAILABLE`、
  `READ_FAILED` 和 `SCHEMA_UNSUPPORTED`；文章自己的证据等级保留，但不会升级成事件级核验状态。
  生产库已是 schema v9；Opportunity 四表有 `signal_detected` 行（来自 evidence-backed B 种子），
  但没有 problem/buyer/payment 的人工提升。B 通道“值得验证的商业机会”本身仍是文章级候选，
  与 Opportunity 不是同一个概念。
  HTML 与文本都渲染 v5 facts/inferences/gaps/actions。卡片下依次给出：
  - `事件结构`：同事件报道 N 篇 · 报道来源 N 个 · 来源族 N 个 · 独立佐证：是/否（单篇单族时不打印）；
  - `事实主张`：事件关联的主张，逐条标注类型（事实/推断/…）与核验状态，并给出证据 ID、定位
    （`summary@起-止`）与来源 ID；超过两条时提示"另有 N 条主张，见归档 JSON"；
  - `候选关联`：条数、状态分布与依据，明确写明"未经确认，不作为已发生的事实"；
  - `同事件其他报道`：其余报道的媒体、标题与链接。
- **待观察信号（弱信号 / 未确认）**：日报在“数据概览”之后固定给出一块降级展示区：
  低置信 Opportunity（`signal_detected`，含 confidence 与追溯链接数）、有数字候选但未形成
  r2-v4 Claim 的文章、以及未确认的事件候选关联。每条都带 `L2·弱信号·原因` 标记，写明
  “弱信号不等于事实，也不计入发布门禁”。发现层保留全部条目；这里只决定展示，不删除、
  不改评分、不改发布门禁。完整列表在归档 JSON 的 `stats.watchlist`。
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
python -m opportunity_radar.unified_main extract    # 标题/证据/主张 -> 实体提及与关系
python -m opportunity_radar.unified_main links --ingest-db <摄取库>   # 候选关联
python -m opportunity_radar.unified_main candidates # 事件候选：强/弱候选，不自动合并
python -m opportunity_radar.unified_main b-candidates --db <库>  # 只读：B 种子映射 + 人工复核 JSON/Markdown
python -m opportunity_radar.unified_main b-review validate --manifest <清单> --db <库>  # 只读校验
python -m opportunity_radar.unified_main b-review preview --manifest <清单> --db <库>   # 只读创建预览
python -m opportunity_radar.unified_main b-review apply --manifest <清单> --db data/archive/p0-batch12-validation/opportunity_radar.sqlite3 --apply  # 显式创建
python -m opportunity_radar.unified_main lineage    # 来源谱系 -> 证据
python -m opportunity_radar.unified_main sources    # 文章 -> source_id（只补绑定，不猜测）
python -m opportunity_radar.unified_main periods --dry-run --json   # 检查旧 skeleton Claim 的 period
python -m opportunity_radar.unified_main periods --apply            # 置空错误 period（先备份并获批准）
python -m opportunity_radar.unified_main audit --db <库>  # 只读端到端一致性审计
python -m opportunity_radar.unified_main db-migrate --db <库>  # 预览 schema 迁移，不写库
python -m opportunity_radar.unified_main db-migrate --db <库> --apply --backup <备份>  # 显式迁移
python -m opportunity_radar.unified_main report     # 各表计数、完整性与缺口
```

主张核验（R2 规则，离线运行）：

```
python -m opportunity_radar.verify --db <库> [--dry-run] [--limit N]
python -m opportunity_radar.verify --db <库> --summary          # 状态与支持关系分布
python -m opportunity_radar.verify --db <库> --audit            # 哪些检查执行了、哪些跳过，按来源分组
python -m opportunity_radar.verify --db <库> --conflicts        # 记录到的冲突，双方数值与依据
```

生产分析器使用 `prompts/analyst_v7.md`（`OR_PROMPT_PATH`）。v6 文件保留仅用于回滚；
`tools/shadow_v7.py` 已改为 V6/V7 对照工具，不再是第二套生产版本。N0–N5 与 `verify` 通过
统一管线接入每日运行；`verified` 只表示主张与其证据一致，不等于事实为真。

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
N2 用本地 Qwen3-30B-A3B 先判定候选的经济相关性（economic / non_economic / uncertain），
再判定主体/指标/主张状态；subject 的文档内缩写、部分 predicate 和 bounded amount 有确定性
规范化；N3 判定水平/变化/比较/区间等关系并对每个 claim_value 给出处置，期间可由同句或标题同月
确定性补齐；rate/change、period_change 与缺失候选有提示词、程序纠正和一次覆盖重试。两者输出
都经过程序校验（ID、枚举、覆盖、证据定位、比较口径守卫、输出预算）。
N4 确定性地标准化数值/单位/数量级/币种/期间/baseline，并保留期间原文与定位；N5 检查每个 N1
候选的处置，按 r2-v4 语义字段合并重复 Claim 后组装 Claim，证据回指 N0，缺失期间/比较口径
只记录不补造。
节点运行写入独立的追加式留存（`data/claim-pipeline/node_runs.sqlite3`）；通过 r2-v4 契约与
证据定位检查的 N5 Claim 由 `pipeline.py` 写入生产 `claims`/`evidences`（`extractor='n5'`），
随后由 `verify.py` 核验，未通过的不写入。七夹具与 50 篇真实 RSS 运行已完成（Batch 12）；
Batch 13 完成 N2 经济相关性、N3 期间关联与 N5 语义去重（14 篇回归）；Batch 14 修复 N3
rate/change、period_change、3.8% 遗漏与输出预算；Batch 15 修复 N2 的 GDP subject、贸易 predicate
与 `$0.1bn` economic relevance；Batch 16 只改 N5，把变化关系的终点 level 折回 change（10 篇参考集），
N5 Claim 仍非已核实事实。
契约见 `docs/CLAIM_PIPELINE.md`。

核验把每条主张与它引用的证据对照：数值是否在引文里、单位是否同族、期间是否与证据记录一致、
百分比与百分点是否混用、比较口径是否与措辞矛盾。结果写入 `claim_verifications`（追加式），
并更新主张状态。`verified` 的含义是"主张与其证据一致"，不是"该事实为真"；散文骨架主张一律
`unverifiable`；有数值但无单位的主张也按 `unverifiable` 处理。主张契约 `r2-v4` 支持
`advance_estimate` 等修订状态与年度区间（`1997-2024`），并把模型的原始表达保留在
`unit_raw` / `period_raw` / `revision_raw` 里。**核验已接入每日管线**；HOLD 仍由覆盖率与
管线阻断决定，核验结果本身不改写发布门禁。

- 七张核心表：`events`、`event_articles`、`evidences`、`claims`、`claim_evidence`、`event_corrections`、
  `claim_corrections`；实体层：`entities`、`entity_aliases`、`entity_mentions`、`entity_relations`、`event_links`。
- 机会层（schema v9；生产已有 `signal_detected` 行）：`opportunities`、`opportunity_links`、`opportunity_hypotheses`、
  `opportunity_revisions`。最小数据访问在 `opportunity.py`，append-only revision；每日管线从
  evidence-backed B 种子创建 `signal_detected`，不自动声称 problem/buyer/payment 已验证。
  `b-candidates` 只读生成 B 种子映射：证据型种子、仅信号种子、映射不足、疑似重复簇和人工复核状态；
  不创建 Opportunity，不自动合并，输出到 `reports/opportunity-candidates.{json,md}`。
  `b-review validate|preview|apply` 读取独立 review manifest；apply 必须显式 `--apply`，只允许
  `data/archive/p0-batch12-validation/opportunity_radar.sqlite3` 这个隔离 v9 库，单条机会的事务内创建
  links 与首条 revision，初始状态固定 `signal_detected`；AI 辅助清单不能自动产生 accepted/创建批准。
- 标识符是内容哈希，重复运行不产生第二条记录。
- 事件合并只有两条规则：规范化 URL 相同，或规范化标题相同且在 72 小时窗口内。其余是不同事件；
  共享关键词不合并。
- 候选关联（`event_links.status='candidate'`）从不自动合并；接受或拒绝写追加式 `event_corrections`。
- 事件候选（`relation='event_candidate'`）比较标题规范化相似度、共享实体、共享证据句子、事件类型
  与时间窗口。强候选必须有标题之外的信号（共享实体/证据/事件类型）；只有标题相似最多是弱候选；
  低于阈值不关联。候选记录保留双方 event_id、article_id、标题、共享词、共享实体、引用证据 ID、
  时间差和转载判断状态，但不改变事件归属。
- 来源独立性分开报告：文章数、来源 ID 数、来源族数、独立来源单元数、已记录联合发布组、未知来源族。
  未知来源族不计入独立来源；同一来源族的多篇不增加独立单元；已记录 `syndication_group` 的多来源
  折叠为一个单元。不同来源族但只有相似标题/引用时，只输出转载候选，不认定为已确认转载。
- RSS 主张 `extractor='skeleton'`：v5 提示词只产出散文事实，数值字段为空，`verification_state`
  一律 `unverified`。文章发布日期只作为 `articles.published` / evidence `observed_at`，不会写入
  Claim 的 `period`；没有明确事实期间时 `period` 为空。SEC/EIA 主张 `extractor='structured'`，
  带数值、单位、期间与申报关系。
- Claim/Evidence 写入要求：evidence 有非空 `source_id`、可定位的 `locator_json`，并能回到文章
  或申报/序列记录；Claim 至少关联一条这样的 evidence。不满足的 Claim 不写入，`bulk_add` 在
  `evidences_rejected` / `claims_rejected` / `links_rejected` / `rejected` 中列出原因，不静默丢弃。
- 旧版 v5 skeleton Claim 曾把发布日期写进 `period`；`periods --apply` 只修正“period 恰好等于
  文章发布日期且 `period_raw` 为空”的记录，并写入追加式 `claim_corrections`；其他记录保持原值并
  报告为待处置。

- 实体抽取（`unified_main extract`）：只读已有标题、Evidence 引文和 Claim 文本，不抓取正文。
  类别为 ORGANIZATION / GOVERNMENT / PRODUCT / TECHNOLOGY / LOCATION / PERSON；当前确定性规则只自动
  抽取组织、政府和地点，产品/技术/人物仅在已有受控别名出现时匹配，不凭模型或字符串相似度生成。
  每条 mention 保留原始文本、类别（经 entities）、article/evidence/claim 键、原文定位、方法和置信度；
  同一实体在同一来源的多次出现合并为一行并记录 `occurrence_count`。`source_name` 是 FreshRSS/feed
  标签，不是发布机构；它不生成 `PUBLISHED_BY`，也不作为正文 mention。`The company`、`A.I. company`
  等泛化词被过滤。
- 实体关系（`entity_relations`）：`MENTIONED_IN` 由 mention 表表达；`INGESTED_FROM` 由
  `articles.source_id` / `source_name` 表达；`SOURCE_FAMILY` 由 `evidences.source_family` 表达；
  `SYNDICATED_FROM` 只由已记录的 `syndication_group` 表达。`PUBLISHED_BY` 只在来源登记提供明确
  发布者身份时生成；当前数据没有该字段，因此为 0。`APPLICANT` / `PETITIONER` / `REGULATED_BY` 只在
  明确句子线索下生成，全部 `unverified`。`AFFECTED_BY` 和 `RELATED_TO` 不自动生成；提及不等于受影响
  或业务关系。`event_candidates` 的共享实体只使用 mention；实体提及也不增加来源独立性。

## 统一生产管线（R1–R6）

每日 `cli` 在分析完成后自动执行 [pipeline.py](opportunity_radar/pipeline.py)：
R1 回填、N0–N5 数值主张（默认每轮 8 篇）、实体/谱系、事件候选、`verify` 核验、
Opportunity 发现（只创建 `signal_detected`）、经济数据同步与派生、质量快照。
每一步写入 `stats.pipeline`，阻断性失败使本次运行 HOLD。`OR_PIPELINE_ENABLED=0`
只用于隔离测试。

```
python -m opportunity_radar.cli --dry-run              # 真实取数 + 模型 + 全管线，不发邮件
python -m opportunity_radar.cli --period weekly       # 从事件/证据/主张重建周报
python -m opportunity_radar.cli --period monthly      # 月报
python -m opportunity_radar.cli --period auto         # 每日运行 + 到期周报/月报
python -m opportunity_radar.unified_main economic     # BLS/EIA -> 经济库 + MoM/YoY
python -m opportunity_radar.unified_main opportunities# evidence-backed B 种子 -> signal_detected
python -m opportunity_radar.unified_main quality      # R6 指标 + 30 天回测快照
python -m opportunity_radar.unified_main backtest     # 30 天运行/覆盖率/投递回测
python -m opportunity_radar.unified_main benchmark    # 冻结的 N1 基准摘要
```

R3 编辑优先级在评分结果中输出 `signal_score` / `evidence_score` /
`editorial_priority`（P0–P3/REJECT）；日报按优先级排序事件代表卡片，来源配额仍只影响
`distribution`，不改写 `status`。

R5 经济库位于 `data/economic/economic.sqlite3`：`datasets` / `observations` /
`observation_versions` / `derived_metrics` / `economic_runs`。修订追加版本，不覆盖历史；
派生指标同时保存公式与输入。R6 指标写入 `data/quality/quality.sqlite3` 和
`reports/quality/latest.{json,md}`；没有真实基准的指标标 `NOT_MEASURED`。

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
- 外部数据源：启动器先运行 `run-sources.ps1`（SEC、EIA、Federal Register、BLS，各自独立库）；
  状态写入 `reports/sources/latest.json`，失败或未配置会出现在日报附录，GDELT 记为 `frozen`。
  这些源的数据不进入 RSS 业务表、提示词或日报正文。
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
| `README.md` | 产品入口：是什么、怎么装、怎么跑、数据怎么流 |
| `docs/PRD.md` | 产品定义：用户、通道、功能需求、数据模型、质量框架 |
| `docs/PROJECT_STATUS.md` | 当前事实：已交付、数据库现状、验收矩阵、缺口 |
| `docs/ARCHITECTURE.md` | 模块职责、数据流、统一生产管线与 R3–R6 |
| `docs/OPERATIONS.md` | 日常运行、排障、任务计划、数据库迁移 |
| `docs/EVIDENCE_AND_LANES.md` | 证据等级与通道评分规则 |
| `docs/CLAIM_PIPELINE.md` | 主张提取流水线：N0–N5 的契约、失败语义、限制 |
| `docs/SOURCE_POLICY.md` | 来源准入与治理字段 |
| `docs/SECURITY_PRIVACY_SOURCE_COMPLIANCE.md` | 安全、隐私与来源合规边界 |
| `docs/E2E_VERIFICATION.md` | 端到端验证方法与边界 |
| `docs/archive/` | 历史与已取代文档（冻结，不再修改） |

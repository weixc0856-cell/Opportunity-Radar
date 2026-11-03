# 项目状态（2026-11-03）

当前分支 `main`；Batch 16 已合并（`d48d872`），第七至十六批均已进入 `main`。
测试：本地 **973 项通过**（含 Source Pilot 测试）；本次未复核干净检出。

## 当前阶段冻结（2026-11-02）

N0–N5 影子 Claim 生成路线已完成阶段性验收并冻结，基线为 Batch 16（合并提交 `d48d872`）。

- 冻结范围：N0 正文规范化、N1 数字候选、N2 语义识别、N3 关系识别、N4 数值标准化、N5 Claim 组装。
- 当前结果仍是**影子 Claim，不是已核实事实**；不写生产 claims/analyses。
- 不启用 v7、不申请 G6；不修改评分、日报、邮件与 R0 发布门禁；SEC/EIA 独立通道保持不变。
- 已知限制见 `docs/OPEN_ISSUES.md` ISSUE-004；它们不阻碍当前路线冻结，不启动 Batch 17。

## 已交付

| 阶段 | 内容 | 状态 |
|---|---|---|
| S0 | 来源覆盖审计；SEC EDGAR 与 EIA 定为限定范围的接入候选 | 已冻结（P0） |
| G-D2 第一阶段 | SEC/EIA 独立摄取通道：获取、规范化、存储、质量验证 | 已验收（10/10），代码与测试已提交 |
| R0 | 运行可靠性与发布门禁：重试、熔断、覆盖率分级、HOLD 隔离 | 已实施、已真实验证并冻结 |
| 调度器修复 | 电源状态不再终止任务；启动器记录运行 ID、阶段与退出码 | 已上线 |
| R1 Batch 1 | Event / Evidence / Claim 统一模型 + RSS/SEC/EIA 回填 | 已实现并**已部署到两库** |
| R1 Batch 2 | 实体、提及、候选关联（claim↔event、event↔event） | 已实现并**已部署到生产库** |
| R1 Batch 3 | 来源谱系（15 源 → 12 族）与独立佐证画像 | 已实现并**已部署到生产库** |
| R1 Batch 4 | 日报按事件展示：同事件合并卡片、来源族与佐证状态、主张与证据定位、候选关联状态 | 已实现 |
| R2（规则） | 结构化主张契约 r2-v4（含数量级模型）、核验规则 r2-v2、冲突检测、v7 影子提示词 | 已实现并离线验证；**v7 切换判定：NOT READY**（百分比变化类数字召回 68%，见 R2_BATCH6 §6） |
| R2 Batch 7 | N0 文章标准化 + N1 数字候选发现（首版） | 已被 Batch 8 的契约取代，保留为历史记录 |
| R2 Batch 8 | N0/N1 契约对齐：完整正文、原子/复合表达分层、节点留存、识别器实测 | 已实现并在 567 篇真实语料上验证（人工基准 19/19，数字覆盖 9905/9905）；N2–N5 未开始 |
| R2 Batch 9 | N2 数字候选语义 + N3 数字关系（本地 Qwen3-30B-A3B） | 已实现并通过真实模型、程序校验与固定样本；真实语料范围见 R2_BATCH9 验收记录 |
| R2 Batch 10 | N4 数值标准化 + N5 完整性门禁与 r2-v4 影子 Claim 组装 | 已实现；两篇 BEA 真实文章端到端产生 16 条影子 Claim，18/18 候选有处置；N4/N5 partial 表示缺失期间等偏差可见；未写生产库 |
| R2 Batch 11 | 多关系组装核查 + 五夹具 N2/N3 覆盖 + 七夹具 N4/N5 | 七夹具完成：49 个 N1 候选全部有处置，31 个接受候选、36 条影子 Claim，契约 36/36；多关系（$105.6bn）核查正确；N2/N3 批次指标与失败恢复已启用 |
| R2 Batch 12 | 50 篇真实 RSS 影子运行 + 10 篇人工基准 | 50 篇完成 N0–N5：257 候选、51 claim_value、42 条影子 Claim，257/257 有处置，契约 50/50；人工参考 N1 21/21、N2 disposition 21/21、N5 正文召回 17/18；N3 period 0/18、3 组语义重复 Claim |
| R2 Batch 13 | N2 经济相关性、N3 期间关联、N5 语义去重 + N1/N4 期间证据 | 14 篇回归（10 篇受影响 + 4 篇补齐参考集）：N2 claim_value 32→20、non_claim 9→27；pySMESH/GUI/Cyril/NVIDIA/SimScale 不再生成 Claim，Google/Intel 语义修复；N3 period 0→15 条关系，参考集正文 Claim 11/18 关联；N5 22→17 条唯一 Claim、5 条语义重复合并；854 测试通过。参考集 N2/N3 部分语义指标回退，见验收记录 |
| R2 Batch 14 | N3 rate/change、period_change、3.8% 遗漏、输出预算 | 10 篇人工参考集：N3 type 17→20/21、direction 17→20/21、comparison 14→18/21，回到 Batch 12 基线；period 11/18 未回退；3.8% 由模型关系或一次覆盖重试分配；1400/2400 tokens 均完成 BEA Personal Income，200 强制截断标 invalid_output；N5 18 条 Claim、严格精确率 15/18、召回 14/18，仍低于 Batch 12，原因在固定 N2 输入；866 测试通过 |
| R2 Batch 15 | N2 subject/predicate/economic_relevance 定向修复 | 10 篇参考集：N2 disposition 20→21/21、subject 17→20/21、predicate 16→19/21、economic 20→21/21；GDP subject、贸易 `$12.8bn` predicate、`$0.1bn` 经济相关性修复；N5 18 条 Claim，严格精确率 18/18、正文严格召回 17/18（按 relationship_type+comparison 同时匹配为 16/18、16/18）；872 测试通过 |
| R2 Batch 16 | N5 endpoint level 组装规则 | 固定 Batch 15 N0–N4，仅重跑 N5：贸易 `$105.6bn` 的终点 level 折回 change，Claim 18→17；严格精确率 18/18→17/17（100%），正文严格召回 17/18；relationship_type+comparison 精确率 16/18→16/17；重复/误合并/漏合并 1/0/0；875 测试通过 |
| N0–N5 影子 Claim 路线 | N0–N5 离线影子生成、候选完整处置、r2-v4 影子 Claim | **阶段验收完成并冻结**；基线 Batch 16；影子 Claim 未接入生产 |
| P0 Batch 1 | 文章来源身份：`articles.source_id`、迁移、`unified_main sources` 回填 | 已实现；生产副本初始绑定 132/138；Batch 5 用显式 feed alias 补绑余下 6 条，验证副本 138/138；生产库未改 |
| P0 Batch 2 | Claim/Evidence 语义正确性：skeleton `period` 不再使用发布日期；写入时强制来源、定位与证据关联；历史 `period` 修正 | 已实现；生产副本 220/220 条 skeleton Claim 的 `period` 已置空，220 条修正记录；0 条待处置；生产库未改 |
| P0 Batch 3 | 事件候选与来源独立性：`event_candidate` 强/弱候选、来源族/独立来源单元/转载候选计算 | 已实现；真实数据 117 事件、6,786 对比较，1 个弱候选、0 强候选、0 已确认转载；无多文章事件，真实聚合能力标记 PARTIAL；生产库未改 |
| P0 Batch 4 | 实体识别与关系：确定性 mention、类别、定位、受控规范化、`entity_relations` | 已实现；Batch 5 修正 source_name 不是 publisher，`PUBLISHED_BY` 不再生成；APPLICANT/PETITIONER/REGULATED_BY 真实数据 0 条，合成测试覆盖；生产库未改 |
| P0 Batch 5 | 数据链路闭环与一致性：来源语义、只读端到端审计、10 条完整链路样本 | 已实现；验证副本 138/138 source_id、52 mention/60 次、24 实体、0 `PUBLISHED_BY`；审计 PARTIAL（15 条 lineage 仅 declared、47 个事件无证据、21 篇未分析文章）；生产库未改 |
| P0 Batch 6 | 迁移安全与事件证据表达：显式 `db-migrate`、审计样本分层、`EVIDENCE_BACKED`/`NO_EVIDENCE`/`INSUFFICIENT_EVIDENCE` | 已实现；普通 CLI 不再隐式迁移；显式迁移在副本完成 v5→v8；审计 10 条完整链路 + 各类缺失样本；47 个无 Evidence 事件在日报中显示“无证据”；生产库未改 |
| P0 Batch 7 | 下游输出证据边界：文本/HTML/邮件/JSON 一致表达 Event/Claim/Source 状态；Opportunity 缺失记录 | 已实现；验证副本 70 EVIDENCE_BACKED / 47 NO_EVIDENCE；220 条 Claim 全为 skeleton/unverified；无独立 Opportunity 实体；文本、HTML、邮件共用状态行，JSON 保留原始状态；生产库未改 |
| P0 Batch 8 | 输出安全降级与 Text/HTML 一致性：`event_context` 状态、HTML 渲染 v5 facts/inferences | 已实现；事件上下文区分 AVAILABLE/NOT_FOUND/UNAVAILABLE/READ_FAILED/SCHEMA_UNSUPPORTED；文章证据等级不升级为事件状态；HTML 补齐 v5 内容；审计 117 篇有 Event / 21 篇无 Event；生产库未改 |

## 数据库现状

| 库 | 表 | `user_version` | 内容 |
|---|---|---|---|
| `data/opportunity_radar.sqlite3`（生产） | 24 | 5 | articles 138 / analyses 117 / runs 16 / deliveries 29；events 117 / evidences 220 / claims 220 / entities 10 / event_links 3（全部 candidate）；尚无 `source_id` 列，未迁移；220 条 skeleton Claim 的 `period` 仍为旧值 |
| P0 Batch 1+2 部署验证副本（生产库拷贝） | 25 | 7 | `data/archive/p0-batch2-postdeploy-validation-2026-11-03/opportunity_radar.sqlite3`；132/138 篇文章绑定 `source_id`；220/220 条 skeleton Claim 的 `period` 已置空；`claim_corrections` 220 条；验证状态仍全部为 `unverified`；SHA-256 `cbeecbdb…f482` |
| P0 Batch 3 验证副本（Batch 1+2 副本 + candidates） | 25 | 7 | `data/archive/p0-batch3-validation-2026-11-03/opportunity_radar.sqlite3`；117 events / 117 articles；`event_candidate` 1 条（weak、same_source_family）；`reprint_candidate` 0；`source_family_count` 11；独立佐证事件 0；未知独立性事件 42；SHA-256 `c10aaa86…d7a3` |
| P0 Batch 5 验证副本（Batch 1–4 修正后） | 26 | 8 | `data/archive/p0-batch5-validation-2026-11-03/opportunity_radar.sqlite3`；138/138 articles 绑定 `source_id`；24 entities（company 10 / organization 3 / government 3 / location 8）；mentions 52 行 / 60 次；有定位 52/52；有 Evidence 30；`entity_relations` 0（`PUBLISHED_BY` 不生成）；`event_candidate` 1 条；SHA-256 `5bbf3781…3d10` |
| P0 Batch 6 迁移验证副本（生产 v5 显式迁移） | 26 | 8 | `data/archive/p0-batch6-migration-validation-2026-11-03/opportunity_radar.sqlite3`；138/138 source_id；220/220 skeleton period 修正；24 entities；mentions 52/60，有定位 52/52；`entity_relations` 0；event_candidate 1；审计 PARTIAL（70 EVIDENCE_BACKED / 47 NO_EVIDENCE；15 declared；21 未分析文章）；SHA-256 `ca370add…5a6f` |
| `data/ingest/opportunity_radar_ingest.sqlite3` | 18 | 3 | sec_facts 2,719 / eia_observations 34 / evidences 2,753 / claims 2,753 |

生产最近一次运行 run 16（2026-11-03 08:30 本地）为 `analysis_failed` / `HOLD`，覆盖率 0.0，失败原因 `circuit_open` 10、`timeout` 3，未发送邮件；这是本批次之前的调度运行故障；P0 Batch 1/Batch 2/Batch 3/Batch 4/Batch 5 均未修改生产库。

证据按来源族：ycombinator-hn 109、openai 24、simscale 17、nyt 17、paraview 15、bbc 14、bea 8、
nvidia 7、precice 5、ons 3、federal-reserve 1。按独立性：unknown 170、independent_secondary 31、
independent_primary 19。

备份：`data/archive/r1-backfill-2026-11-01/`、`r1-batch2-deploy-2026-11-01/`、`r1-batch3-deploy-2026-11-01/`；P0 Batch 2 生产快照 `data/archive/p0-batch2-preflight-2026-11-03/`。

## 当前能力

- **日报**：每日 08:00 计划任务；发布门禁（PASS / PASS_WITH_LIMITATIONS / HOLD）；事件级展示
  （每事件一张卡片，含事实主张、证据 ID 与定位、来源画像、候选关联状态）；报告与归档含运行 ID、
  覆盖率、失败原因。
- **结构化通道**：SEC 10 家公司 XBRL 事实、EIA 单一序列；独立库、独立进程、9 类失败分类。
- **统一模型**：事件、证据、主张、实体、候选关联、来源谱系；文章可直接绑定 `source_id`；Claim/Evidence 写入要求可追溯来源、可定位记录和至少一条证据关联，不满足的 Claim 不写入并在报告中列出；skeleton Claim 的 `period` 为空，发布日期只作为文章/观察时间；生产库尚未执行迁移/回填。
- **事件候选与来源独立性**：`unified_main candidates` 生成强/弱事件候选，保留双方 event/article、标题、共享词、实体、证据 ID、时间差和转载判断；不自动合并。`event_profile` 分开输出文章数、来源 ID 数、来源族数、独立来源单元、联合发布组、未知来源族；未知来源族不计入独立佐证。
- **实体识别与关系**：`unified_main extract` 从已存标题、Evidence 引文和 Claim 文本抽取确定性 mention；保留原始文本、类别、article/evidence/claim 键、定位、方法和置信度。`source_name` 是 feed/`INGESTED_FROM` 标签，不是发布机构；当前不生成 `PUBLISHED_BY`。`APPLICANT`/`PETITIONER`/`REGULATED_BY` 只在明确句子线索下生成且全部 `unverified`；`AFFECTED_BY`/`RELATED_TO` 不自动生成。
- **一致性审计**：`unified_main audit --db <库>` 只读检查 source、evidence、claim、event、entity、relation；输出完整链路和各类缺失样本（最多每类若干条），计数与样本分开；不迁移 schema，不修改数据库。
- **迁移安全**：普通业务 CLI 使用 `migrate=False`；旧 schema 直接报错并提示 `unified_main db-migrate`。`db-migrate` 默认只预览，`--apply --backup <文件>` 才迁移；`audit`、`report`、`--render-only` 保持只读。
- **事件证据状态**：`event_profile` 区分 `EVIDENCE_BACKED` / `NO_EVIDENCE` / `INSUFFICIENT_EVIDENCE`；无 Evidence 的事件保留在日报中并显示“证据状态：无证据”，不作为已核实事实或商业机会事实依据。
- **输出证据边界**：文本、HTML 和邮件共用 `event_summary_lines`；`NO_EVIDENCE` 显示“仅线索，不作为已核实事实”，`EVIDENCE_BACKED` 也注明“不等于主张已核验”。归档 JSON 保留原始 `event.evidence_status` 和 Claim `verification_state`。当前没有独立 Opportunity 表；B 通道是文章级候选。
- **Event 上下文降级**：`cli.attach_event_context` 为每个 item 记录 `AVAILABLE` / `NOT_FOUND` / `UNAVAILABLE` / `READ_FAILED` / `SCHEMA_UNSUPPORTED`。上下文缺失时保留文章证据等级，并在文本/HTML 明确写“不是事件级核验结论”；不把缺失映射成 `NO_EVIDENCE` 或 `EVIDENCE_BACKED`。归档 JSON 保存 `event_context`。
- **Text/HTML 一致性**：HTML 与文本都渲染 v5 facts、inferences、gaps、actions；事件证据状态行共用 `event_summary_lines`。HTML 只是排版和密度不同，不再静默丢失事实或推断。
- **主张核验（离线）**：`verify` 模块对主张与证据做确定性对照，产出 verified / rejected /
  unverifiable 与冲突记录，并提供 `--audit`（检查执行情况）与 `--conflicts`（冲突报告）。
  尚未接入生产库、日报或门禁。
- **结构化提示词 v7（影子）**：`prompts/analyst_v7.md` 输出结构化主张，仅由 `tools/shadow_v7.py`
  在副本上运行；生产仍是 v6。主张契约 `r2-v4` 支持 `advance_estimate` 等修订状态、年度区间，
  并把数量级（million/billion）与物理单位分开存储；
  并保留模型的原始表达（`unit_raw` / `period_raw` / `revision_raw`）。
- **主张提取流水线（离线）**：N0 把标题与正文规范化为带段落/句子 ID 与全文偏移的文档；
  N1 输出原子候选（类型、原始表达、数量级/单位/币种分离、全文位置）与复合表达组；
  N2 判定每个候选的经济相关性（economic / non_economic / uncertain）以及主体/指标/主张状态
  （claim_value / context_only / non_claim / ambiguous / unresolved）；N3 判定水平/变化/比较/
  区间等关系，并对每个 claim_value 给出处置，期间可由同句或标题同月确定性补齐；N4 确定性地
  标准化数值/单位/数量级/币种/期间/baseline，并保留期间原文与定位；N5 检查每个 N1 候选的处置，
  按 r2-v4 语义字段合并重复 Claim 后组装影子 Claim，证据回指 N0。节点运行写入独立的追加式留存；
  影子 Claim 不写生产库、不进入日报或核验。见 `docs/CLAIM_PIPELINE.md`。
- **运维**：管理后台（回环地址）、验收脚本、端到端故障注入工具。
- **本地模型**：Qwen3-30B-A3B-Instruct-2507-Q4_K_M，64K 上下文 + q8_0 KV，实测约 10 tok/s。

## 未完成

1. **语料覆盖**：117 篇文章只有 2 篇提到 SEC 覆盖的公司，实体对齐几乎没有可用信号；
   跨来源佐证在真实事件上尚未发生（当前没有多文章事件）。这是来源覆盖问题（S1），不是模型问题。
2. **RSS 主张是骨架**：数值、单位、期间为空；v6 skeleton Claim 的 `period` 不再写发布日期，但也不推断事实期间；R2 升级提示词后才有可核验的数值主张。
3. **转载识别**：`syndication_group` 全为空，需要正文相似度或通讯社标记。
4. **实体消歧**：同名不同公司、母子公司会被当作同一实体；股票代码暂不参与匹配。
5. **谱系未接入评分**：`multi_source_coverage` 证据状态仍按 `source_name` 计数（同一机构多个栏目会算作多个），尚未改为来源族/独立来源单元计数；这会改变评分和证据状态，需单独批准。
6. **R2 待启用**：50 篇真实 RSS 样本已完成 N0–N5；Batch 13 修复 N2 经济相关性、N3 期间关联
   与 N5 语义去重；Batch 14 将 N3 rate/change、period_change 恢复到 Batch 12 基线；Batch 15 修复
   GDP subject、贸易 predicate 与 `$0.1bn` economic relevance；Batch 16 只改 N5，将 `$105.6bn`
   的终点 level 折回 change，Claim 18→17，严格精确率 17/17，正文严格召回 17/18，
   relationship_type+comparison 精确率 16/17。Google/Intel title-only 语义仍不精确，Personal
   Income 的 0.2% DPI 仍缺 N3 关系，GDP 2.2% comparison 仍为 unknown。影子 Claim 尚未接入生产
   Claim 表、`verify.py`、日报或门禁。v7 切换判定仍为 **NOT READY**。N2/N3 语义准确率仅 10 篇
   人工参考，不外推；程序只记录缺失、不补造。
7. **R3–R6 未开始**：编辑优先级、周报月报、经济数据引擎、回测。
8. **生产迁移与历史修正未执行**：P0 Batch 1/5 的 `source_id` 回填与 feed alias、P0 Batch 2 的 `period` 修正、P0 Batch 3 的事件候选写入、P0 Batch 4 的 schema v8 实体列/关系表迁移和 P0 Batch 5 的审计均只在生产副本完成；需批准后先备份再对生产库执行。
9. **事件聚合真实样本不足**：当前 117 个事件对应 117 篇文章，没有多文章事件；Batch 3 只得到 1 个同来源族弱候选，强候选/转载候选/跨来源族独立佐证均为 0。真实聚合能力标记为 PARTIAL，合成测试通过不等于真实数据已验证。
10. **实体层只验证了组织/政府/地点**：Batch 5 验证副本得到 52 条 mention、24 个正文实体；PRODUCT/TECHNOLOGY/PERSON 没有自动抽取；APPLICANT/PETITIONER/REGULATED_BY 真实数据为 0，只有合成测试覆盖。`AFFECTED_BY` 和 `RELATED_TO` 按边界不自动生成。`source_name` 是 feed 标签，未生成 `PUBLISHED_BY`。实体数量增长不等于关系质量已验证。
11. **事件证据覆盖仍不完整**：验证副本 117 个事件中 70 个 `EVIDENCE_BACKED`、47 个 `NO_EVIDENCE`、0 个 `INSUFFICIENT_EVIDENCE`；21 篇文章未分析。无 Evidence 事件保留但不作为已核实事实。来源谱系 15 条全部 `declared`，没有 `verified`；不能声称独立来源已核验。
12. **没有独立 Opportunity 实体**：B 通道“值得验证的商业机会”是按文章分析和评分路由的候选，不存储在独立 Opportunity 表，也不具备事件/Claim 级事实依据结构。当前只能保证它不把无证据事件或未核验 Claim 显示为已核实事实，不能声称已有完整的商业机会事实模型。
13. **Event 上下文状态不持久化**：`AVAILABLE/NOT_FOUND/UNAVAILABLE/READ_FAILED/SCHEMA_UNSUPPORTED` 是运行时 item 状态，不存在数据库表中；审计只能统计 Event 成员关系，无法从数据库重建具体读取失败。Event 上下文读取失败时，输出明确降级，不伪装成无证据。

## 边界

- SEC/EIA 数据不进入 RSS 业务表、不进入 LLM 分析、不进入日报；两库共享模型契约但物理分离。
- 评分权重、证据门槛、发布门禁的语义不因 R1 改动。
- 未确认许可的来源保持禁用；正文抓取（`full_text_fetch`）全部关闭。

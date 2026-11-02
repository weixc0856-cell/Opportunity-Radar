# 项目状态（2026-11-02）

当前分支 `feat/r2-batch14-n3-semantic-regression`（第十四批）；第七至十三批已进入 `main`。
测试：**866 项通过**；干净检出同样通过（27 项因缺少本地样本显式跳过）。

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

## 数据库现状

| 库 | 表 | `user_version` | 内容 |
|---|---|---|---|
| `data/opportunity_radar.sqlite3` | 23 | 3 | articles 126 / analyses 117 / runs 15 / deliveries 29；events 117 / evidences 220 / claims 220 / entities 10 / event_links 3（全部 candidate） |
| `data/ingest/opportunity_radar_ingest.sqlite3` | 18 | 3 | sec_facts 2,719 / eia_observations 34 / evidences 2,753 / claims 2,753 |

证据按来源族：ycombinator-hn 109、openai 24、simscale 17、nyt 17、paraview 15、bbc 14、bea 8、
nvidia 7、precice 5、ons 3、federal-reserve 1。按独立性：unknown 170、independent_secondary 31、
independent_primary 19。

备份：`data/archive/r1-backfill-2026-11-01/`、`r1-batch2-deploy-2026-11-01/`、`r1-batch3-deploy-2026-11-01/`。

## 当前能力

- **日报**：每日 08:00 计划任务；发布门禁（PASS / PASS_WITH_LIMITATIONS / HOLD）；事件级展示
  （每事件一张卡片，含事实主张、证据 ID 与定位、来源画像、候选关联状态）；报告与归档含运行 ID、
  覆盖率、失败原因。
- **结构化通道**：SEC 10 家公司 XBRL 事实、EIA 单一序列；独立库、独立进程、9 类失败分类。
- **统一模型**：事件、证据、主张、实体、候选关联、来源谱系；回填命令幂等。
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
2. **RSS 主张是骨架**：数值、单位、期间为空；R2 升级提示词后才有可核验的数值主张。
3. **转载识别**：`syndication_group` 全为空，需要正文相似度或通讯社标记。
4. **实体消歧**：同名不同公司、母子公司会被当作同一实体；股票代码暂不参与匹配。
5. **谱系未接入评分**：`multi_source_coverage` 证据状态仍按文章计数，尚未改为来源族计数。
6. **R2 待启用**：50 篇真实 RSS 样本已完成 N0–N5；Batch 13 修复 N2 经济相关性、N3 期间关联
   与 N5 语义去重；Batch 14 将 N3 rate/change、period_change 恢复到 Batch 12 基线，并修复 3.8%
   遗漏与 N3 输出预算。N5 仍低于 Batch 12，原因是固定 N2 输入中的 GDP subject、贸易
   `$12.8bn` predicate 与 `$0.1bn` context_only；影子 Claim 尚未接入生产 Claim 表、`verify.py`、
   日报或门禁。v7 切换判定仍为 **NOT READY**。N2/N3 语义准确率仅 10 篇人工参考，不外推；
   程序只记录缺失、不补造。
7. **R3–R6 未开始**：编辑优先级、周报月报、经济数据引擎、回测。

## 边界

- SEC/EIA 数据不进入 RSS 业务表、不进入 LLM 分析、不进入日报；两库共享模型契约但物理分离。
- 评分权重、证据门槛、发布门禁的语义不因 R1 改动。
- 未确认许可的来源保持禁用；正文抓取（`full_text_fetch`）全部关闭。

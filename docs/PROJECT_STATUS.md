# 项目状态（2026-11-01）

当前分支 `feat/evidence-lanes-source-governance`，HEAD 与 `origin` 同步。
测试：**642 项通过**；干净检出同样通过（27 项因缺少本地样本显式跳过）。

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
| R1 Batch 4 | 日报按事件展示：同事件合并卡片、来源族与佐证状态、候选关联标注 | 已实现 |

## 数据库现状

| 库 | 表 | `user_version` | 内容 |
|---|---|---|---|
| `data/opportunity_radar.sqlite3` | 23 | 3 | articles 117 / analyses 108 / runs 14 / deliveries 26；events 108 / evidences 220 / claims 220 / entities 10 / event_links 3（全部 candidate） |
| `data/ingest/opportunity_radar_ingest.sqlite3` | 18 | 3 | sec_facts 2,719 / eia_observations 34 / evidences 2,753 / claims 2,753 |

证据按来源族：ycombinator-hn 109、openai 24、simscale 17、nyt 17、paraview 15、bbc 14、bea 8、
nvidia 7、precice 5、ons 3、federal-reserve 1。按独立性：unknown 170、independent_secondary 31、
independent_primary 19。

备份：`data/archive/r1-backfill-2026-11-01/`、`r1-batch2-deploy-2026-11-01/`、`r1-batch3-deploy-2026-11-01/`。

## 当前能力

- **日报**：每日 08:00 计划任务；发布门禁（PASS / PASS_WITH_LIMITATIONS / HOLD）；事件级展示；
  报告与归档含运行 ID、覆盖率、失败原因。
- **结构化通道**：SEC 10 家公司 XBRL 事实、EIA 单一序列；独立库、独立进程、9 类失败分类。
- **统一模型**：事件、证据、主张、实体、候选关联、来源谱系；回填命令幂等。
- **运维**：管理后台（回环地址）、验收脚本、端到端故障注入工具。

## 未完成

1. **语料覆盖**：117 篇文章只有 2 篇提到 SEC 覆盖的公司，实体对齐几乎没有可用信号；
   跨来源佐证在真实事件上尚未发生（当前没有多文章事件）。这是来源覆盖问题（S1），不是模型问题。
2. **RSS 主张是骨架**：数值、单位、期间为空；R2 升级提示词后才有可核验的数值主张。
3. **转载识别**：`syndication_group` 全为空，需要正文相似度或通讯社标记。
4. **实体消歧**：同名不同公司、母子公司会被当作同一实体；股票代码暂不参与匹配。
5. **谱系未接入评分**：`multi_source_coverage` 证据状态仍按文章计数，尚未改为来源族计数。
6. **R2–R6 未开始**：主张核验、编辑优先级、周报月报、经济数据引擎、回测。

## 边界

- SEC/EIA 数据不进入 RSS 业务表、不进入 LLM 分析、不进入日报；两库共享模型契约但物理分离。
- 评分权重、证据门槛、发布门禁的语义不因 R1 改动。
- 未确认许可的来源保持禁用；正文抓取（`full_text_fetch`）全部关闭。

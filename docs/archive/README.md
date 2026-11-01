# 历史记录（冻结）

本目录保存审计、设计评审、授权、验收与实验记录。它们记录**当时**的证据与结论：

- 不修改其中的数字、结论与日期。后续变化写进 `docs/` 下的现行文档。
- 文中的 `docs/xxx.md` 路径是撰写时的位置，相关文件多数已移入本目录。
- 现行事实见 `docs/PROJECT_STATUS.md`；产品定义见 `docs/PRD.md`；路线见 `docs/IMPLEMENTATION_PLAN.md`。

## 2026-11-01：S0、SEC/EIA 通道、R0、R1

| 主题 | 文件 |
|---|---|
| 来源覆盖审计（S0，P0 冻结） | `S0_SOURCE_COVERAGE_AUDIT.md` |
| SEC/EIA 接入设计（G-D1） | `INTEGRATION_DESIGN_SEC_EIA.md`、`SEC_SAMPLE_MATRIX_2026-11-01.md` |
| 第一阶段实施授权（G-D2） | `IMPLEMENTATION_AUTHORIZATION_2026-11-01.md` |
| 实施前条件证据 | `INDEPENDENT_CHANNEL_AUDIT_2026-11-01.md`、`COST_QUANTIFICATION_2026-11-01.md`、`FAILURE_INJECTION_ACCEPTANCE_2026-11-01.md` |
| 第一阶段实现与验收 | `PHASE1_SEC_COVERAGE_2026-11-01.md`、`PHASE1_EIA_QUALITY_2026-11-01.md`、`PHASE1_ISOLATION_AND_FAULTS_2026-11-01.md`、`PHASE1_SUMMARY_2026-11-01.md`、`PHASE1_CONCURRENT_RUN_2026-11-01.md`、`PHASE1_FINAL_ACCEPTANCE_2026-11-01.md` |
| R0 发布门禁 | `R0_ACCEPTANCE_2026-11-01.md` |
| R1 统一事件模型 | `R1_BATCH1_ACCEPTANCE_2026-11-01.md`、`R1_BATCH2_ACCEPTANCE_2026-11-01.md`、`R1_BATCH3_ACCEPTANCE_2026-11-01.md`、`R1_BATCH4_ACCEPTANCE_2026-11-01.md` |
| R2 主张核验 | `R2_ACCEPTANCE_2026-11-01.md`（含 G6 评审材料）、`R2_BATCH2_ACCEPTANCE_2026-11-01.md`（v7 影子、冲突展示、核验审计）、`R2_BATCH3_ACCEPTANCE_2026-11-01.md`（契约 r2-v2、20 篇影子、数量级缺陷修复）、`R2_BATCH4_ACCEPTANCE_2026-11-01.md`（64K 服务、生成预算、50 篇影子、r2-v2 规则）、`R2_BATCH5_ACCEPTANCE_2026-11-01.md`（64K 长上下文阶梯、数量级模型、切换评估）、`R2_BATCH6_ACCEPTANCE_2026-11-01.md`（缺陷定位、人工基准、**NOT READY** 判定）、`R2_BATCH7_ACCEPTANCE_2026-11-01.md`（N0/N1 确定性流水线头、人工基准 19/19）、`R2_BATCH8_N0_N1_SPEC_2026-11-01.md`（第八批规格）、`R2_BATCH8_ACCEPTANCE_2026-11-01.md`（契约对齐、复合表达、Recognizers-Text 实测）、`R2_BATCH9_N2_N3_SPEC_2026-11-02.md`（第九批规格）、`R2_BATCH9_N2_N3_ACCEPTANCE_2026-11-02.md`（N2/N3 语义与关系、真实模型运行） |
| 来源实测与缺陷修复记录 | `SOURCE_REVIEW.md` |

## 2026-10-20 至 2026-10-26：早期实验

| 分组 | 文件 |
|---|---|
| 开发检查点 | `DEV_CHECKPOINT_2026-10-23.md`、`ACCEPTANCE_2026-10-23.md`、`BUILD_STATUS_2026-10-23.txt` |
| 影子运行与端到端 | `SHADOW_RUN_2026-10-23.md`、`SHADOW_ROUND2_DESIGN.md`、`E2E_ROUND2_RESULTS_2026-10-23.md`、`E2E_SOURCE_QUALITY_2026-10-23.md` |
| 评分与构念实验 | `A_LANE_SCORING_REVIEW_2026-10-23.md`、`CONSTRUCT_REVIEW_2026-10-23.md`、`ACTIONABILITY_EXPERIMENT_DESIGN_2026-10-23.md`、`ACTIONABILITY_EXPERIMENT_RESULTS_2026-10-23.md` |
| 正文抓取审计 | `FULL_TEXT_AUDIT_2026-10-23.md` |
| 来源整合 | `SOURCE_CONSOLIDATION_PLAN.md`、`source-probe-2026-10-23.json` |
| P0 审计 | `P0_AUDIT_2026-10-26.md` |
| 旧版建议 | `API_CONTRACT_RECOMMENDATIONS.md`、`QA_TEST_PLAN.md`、`UI_UX_SPEC.md` |

## 仍然有效的结论

- **actionability 字段作为评分信号为 FAIL**（`ACTIONABILITY_EXPERIMENT_RESULTS_2026-10-23.md`），不再做同类实验。
- **importance 排序提升不等于展示质量提升**（`A_LANE_SCORING_REVIEW_2026-10-23.md`）：配额决定读者看到什么。
- **P0 审计的三个缺陷仍部分存在**（`P0_AUDIT_2026-10-26.md`）：`content_basis` 未读 `retrieval_status`、
  引文最小信息量、deferred 条目无跨期承载。当前状态见 `docs/OPEN_ISSUES.md`。
- **SEC/EIA 第一阶段的隔离与验收结论**（`PHASE1_FINAL_ACCEPTANCE_2026-11-01.md`）：独立库、独立入口、
  故障分类与并发行为已实测；该结论是后续阶段不得越界的依据。

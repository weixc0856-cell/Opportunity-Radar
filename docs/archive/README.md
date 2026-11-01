# 历史文档归档（2026-10-20 至 2026-10-26）

本目录保存**带日期的实验、审计与旧版设计文档**。它们记录了当时的证据与结论，属于冻结材料：

- 不修改其中的数字、结论与日期；后续变化写在当前文档中。
- 当前行为以 `README.md`、`CLAUDE.md`、`docs/PRD.md`、`docs/IMPLEMENTATION_PLAN.md` 与 `docs/` 下的现行文档为准。
- 归档文档内出现的 `docs/xxx.md` 路径是其撰写时的位置；相关文件现在多半已移入本目录。

## 分组

| 分组 | 文件 | 说明 |
|---|---|---|
| 2026-10-23 开发检查点 | `DEV_CHECKPOINT_2026-10-23.md`、`ACCEPTANCE_2026-10-23.md` | 当时的代码与验收记录（371/381 项测试） |
| 影子运行与 E2E | `SHADOW_RUN_2026-10-23.md`、`SHADOW_ROUND2_DESIGN.md`、`E2E_ROUND2_RESULTS_2026-10-23.md`、`E2E_SOURCE_QUALITY_2026-10-23.md` | 来源质量与端到端实验 |
| 评分与构念 | `A_LANE_SCORING_REVIEW_2026-10-23.md`、`CONSTRUCT_REVIEW_2026-10-23.md`、`ACTIONABILITY_EXPERIMENT_DESIGN_2026-10-23.md`、`ACTIONABILITY_EXPERIMENT_RESULTS_2026-10-23.md` | actionability AUC 实验（结论：FAIL） |
| 正文抓取 | `FULL_TEXT_AUDIT_2026-10-23.md` | 正文抓取抽样审计 |
| 来源整合 | `SOURCE_CONSOLIDATION_PLAN.md`、`source-probe-2026-10-23.json` | 旧版信源整合方案与探测数据；S0 审计将重新评估 |
| 2026-10-26 P0 审计 | `P0_AUDIT_2026-10-26.md` | 四个 P0 问题的审计与修复记录 |
| 旧版建议 | `API_CONTRACT_RECOMMENDATIONS.md`、`QA_TEST_PLAN.md`、`UI_UX_SPEC.md` | 2026-10-20 审查建议；多数已实现或已被现行测试与规范取代 |

## 仍然有效的结论

- `ACTIONABILITY_EXPERIMENT_RESULTS_2026-10-23.md`：actionability 字段作为评分信号为 **FAIL**，不要再做同类字段实验。
- `A_LANE_SCORING_REVIEW_2026-10-23.md`：importance AUC 0.782，但 `source_cap` 决定最终展示量。
- `P0_AUDIT_2026-10-26.md`：`content_basis` 未读 `retrieval_status`、引文最小信息量、deferred 条目无跨期承载——均仍待处理。

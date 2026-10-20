# Opportunity Radar：产品与工程审查资料包

本资料包基于当前项目代码与 140 项现有单元测试结果整理。它主要增加审查文档和下一阶段规范，不应被误解为已经实现了所有路线图项目。

## 文档导航
- `PRODUCT_ENGINEERING_REVIEW.md`：执行摘要、架构、技术选型、风险优先级与 4 周路线图
- `PRD_LOCAL_WORKBENCH.md`：产品定位、MVP 范围、页面、交互和验收标准
- `API_CONTRACT_RECOMMENDATIONS.md`：现有 API 目录与建议的统一响应契约
- `QA_TEST_PLAN.md`：单元、API、前端、端到端与故障测试
- `SECURITY_PRIVACY_SOURCE_COMPLIANCE.md`：本地后台、邮件、来源、AI 与公开部署风险
- `UI_UX_SPEC.md`：交互状态、危险操作、无障碍与前端框架策略

## 本次审查边界
- 对用户上传的 ZIP 运行了现有 Python unittest：140 项通过。
- 没有修改现有业务代码。
- 没有验证用户本机 FreshRSS、llama-server、SMTP 或 Windows 任务计划程序。
- 没有逐一在线核验 CSV 中的 RSS URL 和法律条款。

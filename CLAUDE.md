# Opportunity Radar — 工作指导

本文件规定**怎么在这个仓库里工作**：原则、边界、阶段纪律与文档地图。
产品是什么、有哪些功能，见 `docs/PRD.md`；当前做到哪一步，见 `docs/PROJECT_STATUS.md`。

## 项目一句话

本地优先的商业与产业情报系统：真实来源 → 结构化证据 → 可复核的判断。不是 RSS 阅读器，
不是让模型自动写财经文章的工具。

## 工作原则

1. **证据优先**：任何结论都要能回到原始文本与位置。模型输出是待核验的材料，不是事实。
2. **隔离**：SEC/EIA 有独立数据库与入口，不写入 RSS 业务表、不进入 LLM 与日报；两库共享数据契约，
   不共享文件。
3. **可复现**：确定性规则优先；模型、提示词、规则、数据版本随记录保存；同输入同输出。
4. **失败要可见**：运行失败、覆盖率不足、证据缺失都必须在报告与运行记录里出现，不能被渲染成
   "今天没有信号"。
5. **保守合并**：不确定就保持独立。候选关联写 `candidate`，未知来源写 `unknown`。

## 交付纪律

- 阶段完成的定义是：代码 + 测试 + 真实数据验证 + 文档记录。缺一项就说缺哪一项。
- 每个阶段独立提交；不改写已推送的提交；不把未验证的改动混进提交。
- 真实运行需要本机 FreshRSS 与 `llama-server`；没有就明确写"未验证"，不要用 mock 结果代替。
- 生产库迁移必须有可恢复备份；先在副本演练，再对生产执行。
- 本地 LLM 单端口 **8080**，项目实例 **CPU-only**（`-ngl 0`，64K）。`start-model.ps1`
  检测到端口被占用时等待（`MaxWaitSeconds`），不另开端口、不 kill 别人的进程；
  `run-digest.ps1` 只停止本次启动的实例（`reports\llama-server.pid`）。

## 工程约定

- 运行期只用 Python 标准库；新增依赖需要先证明标准库不够用，并记录理由与版本。
- 数据库迁移只允许附加（`CREATE TABLE` / `ADD COLUMN`），用 `PRAGMA user_version` 记录版本；
  只读路径（如 `--render-only`）不触发迁移。
- 文章、证据、纠正记录都是追加式；不覆盖历史，不改写已发生的验收结论。
- 报告先写临时文件并校验，失败时保留上一份有效报告。
- 密钥只从环境变量读取；日志要脱敏。

## 硬性禁止

1. 把模型自评或模型抽取的字段当作独立验证。
2. 把多篇转载当作多来源佐证；把同一机构的多个栏目当作多个来源。
3. 在来源谱系未知时声称"独立佐证"。
4. 把咨询报告预测写成已发生事实；把论文、开源项目与商业部署混为一谈。
5. 未经批准修改评分权重、证据门槛或发布门禁。
6. 让 SEC/EIA 数据进入 RSS 业务表、LLM 分析或日报。
7. 绕过登录、付费墙、robots 或访问限制；接入未核验许可的来源。
8. 在没有基准数据时宣称准确率、覆盖率或"已验证"。

## 当前阶段

R0–R6 已进入同一生产管线。每日 `cli` 在分析后自动执行 R1 回填、N0–N5 数值主张、
实体/谱系、事件候选、`verify` 核验、Opportunity 发现、经济数据同步与 R6 质量快照。
生产库已迁移到 schema v9；历史 skeleton Claim 的 `period` 已修正，`source_id` 已回填。
Opportunity 只创建 `signal_detected`，不自动声称 problem/buyer/payment 已验证。
生产分析器使用 V7（`OR_PROMPT_PATH=prompts/analyst_v7.md`）；V6 保留为回滚版本。
分析后端走 Anthropic Messages 路由（`OR_LLM_API_STYLE=anthropic`，cc switch 本地代理
`http://127.0.0.1:15721/v1`，模型 `claude-sonnet-5`）；本地 Qwen + 8080 保留为回滚后端，
见 `docs/OPERATIONS.md` 的 Analyzer backend。
日报每日 06:00，周报/月报由 `--period auto` 按 7/30 天节奏生成。
日报邮件只发送第一至七节与附录说明；附录 A/B/C 按 `report_hash` 写入 SQLite
`report_sections` 并随归档保存，管理台 `/report` 仍提供完整版。

## 文档地图

| 文档 | 写什么 |
|---|---|
| `README.md` | 产品入口：是什么、怎么装、怎么跑、数据怎么流 |
| `docs/PRD.md` | 产品定义：用户、通道、功能需求、数据模型、质量框架 |
| `docs/REPORT_FORMAT.md` | 报告体例：咨询结构、写作规则、门禁与语言约束 |
| `docs/PROJECT_STATUS.md` | 当前事实：已交付、数据库现状、验收矩阵、缺口 |
| `docs/ARCHITECTURE.md` | 模块职责、数据流、统一生产管线与 R3–R6 |
| `docs/OPERATIONS.md` | 日常运行、排障、任务计划、数据库迁移 |
| `docs/EVIDENCE_AND_LANES.md` | 证据等级与通道评分规则 |
| `docs/CLAIM_PIPELINE.md` | 主张提取流水线：N0–N5 的契约、失败语义、限制 |
| `docs/SOURCE_POLICY.md` | 来源准入与治理字段 |
| `docs/SECURITY_PRIVACY_SOURCE_COMPLIANCE.md` | 安全、隐私与来源合规边界 |
| `docs/E2E_VERIFICATION.md` | 端到端验证方法与边界 |
| `docs/archive/` | 历史与已取代文档（冻结，不再修改） |

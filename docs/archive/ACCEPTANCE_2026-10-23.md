# 验收结果（2026-10-23）

> 口径：只记录**本机实际执行过**的检查。没有执行、或被环境/许可阻断的项，分别记为 `NOT_RUN` / `BLOCKED`，
> 不用推测值填充。`PASS` 只表示该项检查通过，不表示来源准确、许可完整或结论成立。

## 工作项

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 完整单元测试 | **PASS** | 327 tests, 0 failures（`python -m unittest discover -s tests`），Python 3.12.10 |
| 2 | 语法编译 | **PASS** | `compileall` 覆盖 `opportunity_radar`、`tests`、`tools` |
| 3 | 来源登记审计 | **PASS** | 模板 43 行 / 0 启用 / 0 error；本地 43 行 / 14 启用 / 0 error / 0 warning |
| 4 | 数据集登记校验 | **PASS** | 2 行，1 approved，0 error；`--check` 返回 HTTP 200 |
| 5 | 页面监测适配器 | **PASS** | 18 个单元测试；实跑：国家统计局 15 条链接，第二次 `skipped_interval` |
| 6 | 管理端字段与读写 | **PASS** | `SOURCE_FIELDS` 含 `intelligence_lines`；admin 测试通过 |
| 7 | 旧配置兼容 | **PASS** | 无新列的 CSV 可加载，审计给 `missing_intelligence_lines` 警告，不静默归类 |
| 8 | 历史库 render-only 回归 | **PASS** | `--render-only` exit 0；3 条旧记录计为 `(undeclared)`，未猜测主线 |
| 9 | 真实端点探测 | **PASS** | 26 个候选（`docs/source-probe-2026-10-23.json`）；8 可用 / 13 仅入口 / 5 拦截 |
| 10 | FreshRSS 分类迁移 | **PASS** | 23 订阅 / 9 分类 / 3,915 条目；迁移前备份 `db.sqlite.bak-2026-10-23` |
| 11 | 真实采集与完整报告 | **PASS** | 候选配置 `--dry-run`：6 获取 / 6 分析 / 0 失败，报告与归档完整 |
| 12 | 隔离 DB 影子运行 | **PASS** | 基线 6/6（A 通道 0）vs 候选 6/6（A 通道 6），见 `docs/SHADOW_RUN_2026-10-23.md` |
| 13 | 端到端环境检查 | **PASS** | `acceptance`：8 passed, 0 failed, 0 critical（配置/来源/FreshRSS/模型/SQLite/报告/邮件配置/计划任务） |
| 14 | 启用来源 URL 可达性 | **FAIL（4 项，均不阻塞采集）** | 见下 |
| 15 | 条款与复用许可审查 | **BLOCKED** | 未阅读任何来源条款；`approved` 仅为本地私测，许可全部 `unknown` |
| 16 | 中国政策来源接入 | **BLOCKED** | 10 个部委仅 PBOC 有 Feed，且无条款页；gov.cn 政策列表为 JS 渲染 |
| 17 | BLS 接入 | **BLOCKED** | Feed 可用，但 HTML/条款页对非浏览器客户端 403，无法核对许可 |
| 18 | 结构化数据"持续更新"证明 | **NOT_RUN** | 只做了一次端点探测；连续性与修订未观察 |
| 19 | 7 天来源质量指标 | **NOT_RUN** | 未积累；成功率为单次观测 |
| 20 | 通讯社转载识别 | **NOT_RUN** | 按任务要求保留 `multi_source_coverage` 现有谨慎语义，本轮不实现 |
| 21 | CI 重跑 | **NOT_RUN** | 本地测试通过不等于 GitHub Actions 通过；本次未触发流水线 |
| 22 | 真实邮件发送 | **NOT_RUN** | 本轮全部使用 `--dry-run`；邮件路径的最后一次真实验证在来源变更之前 |

## 第 14 项明细

`source_audit --check-urls` 对 14 个启用来源检查 homepage / feed / terms：

| 来源 | 检查项 | 结果 | 说明 |
|---|---|---|---|
| hn-ask | feed | `URLError` | 同一时刻 hn-show 的同一提供方正常；判断为瞬时失败，FreshRSS 刷新正常 |
| hn-show | feed_provider_terms | `URLError` | hnrss.org 瞬时不可达；hn-ask 的同类检查返回 200 |
| openai-community | terms | HTTP 403 | 已知；条款页拒绝非浏览器客户端，未尝试绕过 |
| nyt-home | homepage | HTTP 403 | 已知；官方 RSS 域名正常，采集不使用首页 |

这四项**都没有改变**登记状态：前两项是可达性抖动，后两项是已记录的访问限制。

## 结论边界

- 12 个 `PASS` 覆盖"代码、配置、迁移、探测、采集、报告"六类可独立验证的工作。
- `BLOCKED` 的三项都指向同一件事：**没有条款阅读，就没有真正的许可结论**。把 `permission_status=approved` 读成"已授权"是错误理解。
- `NOT_RUN` 的四项都依赖时间或外部环境：持续更新、长期指标、CI、真实投递。

## 补充：端到端来源质量验证（同日，独立产物）

30 篇对 30 篇的公平对照运行见 `docs/E2E_SOURCE_QUALITY_2026-10-23.md`。
该轮的验收结果：运行可复现 PASS、数据隔离 PASS、报告生成 PASS、指标原始记录 PASS、
证据规则未被绕过 PASS、样本量 PASS；相同时间窗口 **FAIL**（基线含 9 月初条目）；
多日稳定性、人工盲评、连续失败率 **NOT_RUN**；条款许可仍 **BLOCKED**。

> 后续变更（同日）：Census 因 E2E 发现 Feed 无条目级链接已禁用，启用数由 14 变为 13；
> 该检查的执行时间与结果保留为当时记录，未回改。见 `docs/SOURCE_REVIEW.md` §14.2。

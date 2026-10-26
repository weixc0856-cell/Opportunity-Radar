# 端到端验证（E2E）

`tools/e2e_verify.py` 不是配置巡检（那是 `opportunity_radar.acceptance`），而是把真实流程跑两遍：

| 运行 | 输入 | 必须证明 |
|---|---|---|
| happy | FreshRSS → 真实本地模型 → SQLite → 报告 | 至少一条分析成功；报告、归档、哈希与计数一致 |
| fault | 复用 happy 的库 + 一个固定返回非法 `category` 的本地模型 | 退出码非零、状态 `analysis_failed`、逐条失败入库、报告明确说明失败 |

fault 运行复现 `docs/OPEN_ISSUES.md` 的 ISSUE-001（`policy_change` 不在枚举内）。它复用了
happy 的数据库，所以同一轮里既有"已有结果跳过"，又有"分析失败"——这正是过去会把失败写成
"本轮没有新增分析任务"的组合。

## 用法

```powershell
# 两次运行 + 不做基线
.\.venv\Scripts\python.exe tools\e2e_verify.py --limit 3

# 固定基线（数据库、日志、报告、哈希清单）
.\.venv\Scripts\python.exe tools\e2e_verify.py --limit 3 --baseline-dir tests\baselines\2026-10-26

# 只跑正常流程
.\.venv\Scripts\python.exe tools\e2e_verify.py --skip-fault

# 机器可读
.\.venv\Scripts\python.exe tools\e2e_verify.py --json
```

隔离目录默认是 `data/e2e-verify-<时间戳>/`：`happy/` 与 `fault/` 各含独立的 SQLite、日志与
报告树。生产数据库、生产报告目录和邮件都不会被触碰（CLI 以 `--dry-run` 调用）。

## 检查项

- 预检：配置、来源审计、启用来源、FreshRSS Feed 映射、候选池条数、模型 `/health`。
- 运行：`runs` 表的最新一行；`analyses` 成功数；`analysis_failures` 的逐条失败。
- 失败语义（只在出现失败时检查）：
  - 退出码非零，状态属于 `partial_failed` / `analysis_failed` / `failed`；
  - `analyzed=0` 且 `failed>0` 必须是 `analysis_failed`，不能是 `dry_run` / `success`；
  - 失败条数必须与 `analysis_failures` 行数一致；
  - 报告不得包含"本轮没有新增分析任务"，且必须包含失败说明。
- 产物完整性：`latest-digest.txt/html`、归档 manifest/items 存在；`report_hash` 与文件内容一致；
  `article_count` 与 items 数一致；manifest 的 status 计数与 items 重算一致；每条的
  `scoring.status` 与渲染的 `status` 一致。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 全部检查通过 |
| 1 | 验证失败（某项语义或产物不成立） |
| 2 | 预检失败（配置/来源/FreshRSS/模型），不会消耗模型时间 |
| 3 | 基线打包失败 |

## 基线

`--baseline-dir` 会把 happy 运行的 `run.sqlite3`、`run.log`、`stdout.txt`、`stderr.txt` 与
`reports/` 复制过去，再写：

- `verification.json`：两次运行的 run 行、失败行、全部检查结果、`git_commit` / `git_dirty`；
- `MANIFEST.json`：目录内每个文件的字节数与 SHA-256。

数据库、日志和报告含第三方 Feed 摘要，按项目约束不入库（`tests/baselines/.gitignore`）；
版本库只保留 `MANIFEST.json` 与 `verification.json`。因此克隆仓库后无法重新核对被忽略的文件，
清单的作用是证明基线生成时磁盘上存在哪些文件。

## 边界

- 3 条样本只证明链路可用，**不**证明来源质量、许可、模型判断力或多日稳定性；
- 模型是非确定性的：分数和文本每次运行都不同。基线比较的是失败语义与产物完整性，不是逐字回归；
- fault 运行只覆盖"分析阶段失败"这一类；FreshRSS、SMTP、计划任务的故障由
  `opportunity_radar.acceptance` 与自己注入的环境故障覆盖；
- 报告里的 `review_required` 来源仍然需要在真实运行前人工复核，E2E 不改变许可状态。

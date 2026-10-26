# 验证基线

这里保存端到端验证与生产运行的本地证据，不是逐字回归的黄金样本。

## 现有基线

| 目录 | 生成时间 | 内容 |
|---|---|---|
| `2026-10-26/` | 2026-10-26 | happy 3 条 / fault 2 条；`git_dirty=true`（修复已应用、尚未提交） |
| `2026-10-26-production/` | 2026-10-26 14:27 | 生产入口 `run-digest.ps1` 的 run 8：采集 20 / 分析 6 / 1 watch / 5 filtered；3 封邮件；提示词 v6 |

`MANIFEST.json` 记录 `git_commit`、`git_dirty` 与目录内每个文件的 SHA-256；
`verification.json` 记录运行行、检查结果与逐条摘要。两者可以入库（数据库、日志与报告除外）。

`run.sqlite3`、`run.log`、`stdout.txt`、`stderr.txt` 与 `reports/` 由 `.gitignore` 排除：
它们含第三方 Feed 摘要，按项目约束不提交。因此克隆仓库后无法重新核对被忽略文件的哈希；
清单的作用是证明基线生成时磁盘上存在哪些文件。

生产基线 `2026-10-26-production/` 目录：

- `opportunity_radar.sqlite3`：生产库快照（含历史分析与本次 run 8）；
- `logs/`：`opportunity-radar.log`、`scheduler-run.log`、`cli-run.log`、`cli-run.err.log`；
- `reports/`：`latest-digest.html/.txt` 与本次归档的 `.html/.txt/.items.json/.manifest.json`；
- `verification.json`：run 行、投递数量（不记录收件人地址）、逐条分析摘要、提示词版本与 hash；
- `MANIFEST.json`：上述每个文件的 SHA-256。

数据库、日志和报告同样由 `.gitignore` 排除；版本库只保留 `verification.json` 与 `MANIFEST.json`。
生产基线与 `2026-10-26/`（E2E happy/fault 验证基线）分开保存，避免覆盖已审计的证据。

## 重新生成

```powershell
.\.venv\Scripts\python.exe tools\e2e_verify.py --limit 3 --baseline-dir tests\baselines\<YYYY-MM-DD>
```

模型是非确定性的：分数、标题和文本每次运行都不同。比较的是**失败语义与产物完整性**，
不是具体分数。若要让 `git_dirty=false`，先提交代码再跑。

生产基线：用 `deploy\windowsun-digest.ps1` 跑真实入口，然后把生产库、日志与报告复制到
`tests/baselines/<YYYY-MM-DD>-production/`，写 `verification.json` 与 `MANIFEST.json`。
生产运行会按配置发送邮件；不记录收件人地址，只记录投递数量。

## 读取失败记录

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.cli --render-only   # 不涉及失败表
```

```python
from opportunity_radar.store import Store
Store('tests/baselines/2026-10-26/run.sqlite3', read_only=True).analysis_failures()
```

# 验证基线

这里保存 `tools/e2e_verify.py` 生成的本地证据，不是逐字回归的黄金样本。

## 现有基线

| 目录 | 生成时间 | 内容 |
|---|---|---|
| `2026-10-26/` | 2026-10-26 | happy 3 条 / fault 2 条；`git_dirty=true`（修复已应用、尚未提交） |

`MANIFEST.json` 记录 `git_commit`、`git_dirty` 与目录内每个文件的 SHA-256；
`verification.json` 记录两次运行的 `runs` 行、逐条失败、全部检查结果。两者可以入库。

`run.sqlite3`、`run.log`、`stdout.txt`、`stderr.txt` 与 `reports/` 由 `.gitignore` 排除：
它们含第三方 Feed 摘要，按项目约束不提交。因此克隆仓库后无法重新核对被忽略文件的哈希；
清单的作用是证明基线生成时磁盘上存在哪些文件。

## 重新生成

```powershell
.\.venv\Scripts\python.exe tools\e2e_verify.py --limit 3 --baseline-dir tests\baselines\<YYYY-MM-DD>
```

模型是非确定性的：分数、标题和文本每次运行都不同。比较的是**失败语义与产物完整性**，
不是具体分数。若要让 `git_dirty=false`，先提交代码再跑。

## 读取失败记录

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.cli --render-only   # 不涉及失败表
```

```python
from opportunity_radar.store import Store
Store('tests/baselines/2026-10-26/run.sqlite3', read_only=True).analysis_failures()
```

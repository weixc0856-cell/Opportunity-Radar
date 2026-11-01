# Prompt assets

Prompts are versioned assets, not code strings.

| File | Role | Used at runtime |
|---|---|---|
| `analyst.md` | 单次调用文章分析提示词；首行 `VERSION: N`（当前 6） | 由 `LocalAnalyzer` 加载 |
| `shared/output_contract.md` | 所有提示词必须遵守的输出与证据规则 | 自动追加到 `analyst.md` |
| `shared/style_guide_zh.md` | 中文简报的写作规则 | 自动追加到 `analyst.md` |

- 版本号与提示词哈希会随每条分析保存（`meta.prompt_version` / `meta.prompt_hash`），便于回溯与新旧对比。
- 修改提示词的步骤：递增 `VERSION` → 跑全量单元测试 → 用固定样本重跑对比 → 再依赖新输出。
- 当前分析契约是 schema v5（`facts` / `inferences` / `gaps` / `actions`）。R2 的 Claim 字段尚未实现，
  不要在未获批准的阶段提前修改 `analyst.md`；R2 启动时再递增版本并同步更新 shared 规则。
- `opportunity_radar/analyzer.py` 中保留了内置回退提示词；修改 `analyst.md` 时需保持两者字段一致，
  否则缺少文件时会静默使用旧契约。
- 证据抽取、商业评估、审阅、编辑改写等分角色提示词尚未接入单次调用管线，本目录不保留未使用的草稿。

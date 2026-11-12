# Prompt assets

Prompts are versioned assets, not code strings.

| File | Role | Used at runtime |
|---|---|---|
| `analyst_v9.md` | 生产分析提示词：v5 契约 + `claims` + `action_title`/`so_what`/`why_now`/`kill_criteria` | `OR_PROMPT_PATH` 指向它；`LocalAnalyzer` 加载 |
| `analyst_v8.md` | 回滚提示词（v9 之前的生产版本） | 仅当 `OR_PROMPT_PATH=prompts/analyst_v8.md` |
| `analyst_v7.md` / `analyst.md` | 历史回滚版本 | 仅在显式指定时使用 |
| `shared/output_contract.md` | 所有提示词必须遵守的输出与证据规则 | 运行时自动追加 |
| `shared/style_guide_zh.md` | 中文简报的写作规则 | 运行时自动追加 |

- 版本号与提示词哈希随每条分析保存（`meta.prompt_version` / `meta.prompt_hash`），
  并进入 `analysis_input_hash`：换提示词会让旧分析失效，而不是静默复用。
- 修改提示词的步骤：递增 `VERSION` → 跑全量单元测试 → 用固定样本重跑对比 → 再切换
  `OR_PROMPT_PATH`。切换与回滚见 `docs/OPERATIONS.md`。
- 当前生产契约是 schema v5（`facts` / `inferences` / `gaps` / `actions`）+ `claims`；v9 的四个执行层字段为可选，旧记录缺省时由渲染器回退；
  N0–N5 的 Claim 契约是 `r2-v4`（见 `docs/CLAIM_PIPELINE.md`）。
- `opportunity_radar/analyzer.py` 中保留了内置回退提示词；只有在没有任何提示词文件时才使用它，
  修改提示词时需保持字段一致，否则缺少文件会静默使用旧契约。
- 证据抽取、商业评估、审阅、编辑改写等分角色提示词尚未接入单次调用管线，本目录不保留未使用的草稿。

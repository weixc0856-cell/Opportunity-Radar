# Prompt assets

Prompts are versioned assets, not code strings.

- `analyst.md` is the single-call prompt used by `LocalAnalyzer`. Its first line is
  `VERSION: N`; the version is recorded with every stored analysis so results can be
  reproduced and compared after a prompt change.
- `shared/output_contract.md` holds rules that every future prompt must follow.
- `shared/style_guide_zh.md` holds the Chinese editorial rules.

When changing a prompt, bump `VERSION` and re-run the regression set before relying on
the output. Role-specific prompts (evidence extraction, commercial assessment, skeptical
review, editorial rewrite) are documented in the contract but not yet wired into the
single-call pipeline.

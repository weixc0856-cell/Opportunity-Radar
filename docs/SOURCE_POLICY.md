# Source approval policy

All repository sources start disabled, and local FreshRSS feed IDs are blank because they are installation-specific. Before enabling a source, record the official owner, canonical domain, actual feed provider (if different), documented RSS/API method, owner and provider terms, review date, allowed access frequency, allowed storage/analysis/internal summary uses, retention limits and attribution requirements. Use `python -m opportunity_radar.source_audit` to check metadata completeness. Optional URL checks only confirm reachability; they do not confirm authenticity, accuracy or permission.

`robots.txt` is not complete legal authorization. Public visibility does not automatically license bulk collection, storage or redistribution. Do not bypass authentication, paywalls, CAPTCHAs, rate limits or technical access controls. If terms are unclear, keep disabled. Suspend a source if permissions change or access is blocked. Email should contain concise summaries and links, not full article copies.

每个已批准来源必须在 `config/sources.csv` 中配置准确的 `freshrss_feed_id`。程序只处理映射到已批准来源的文章；无法映射的 feed 默认跳过。

## Editorial lanes and content access

A source that may legally be read is not automatically a source that belongs in the daily
briefing. Every registry row now declares an editorial job:

- `editorial_lanes`: which channels (A / B / C) the source may feed. Required before enable.
- `content_access_level`: `full_text`, `excerpt`, `title_only` or `auto`. Only `full_text`
  (a review decision) lets the source's articles reach evidence rank E2; `auto` records the
  program's estimate as a hint for the reviewer.
- `source_cap`: how many items the source may contribute to one issue (0 = uncapped). Exceeding
  it defers the extra items from that issue; it never changes their `status`.
- `source_authority` and `topic_tags`: review notes for humans, not scoring inputs.

Only an explicit `full_text` declaration grants evidence rank E2. `auto` and `excerpt`
are both treated as summaries, however long the text is: an unreviewed feed cannot prove
it sent the whole article, and a 400-character body may be a complete short post or the
first half of a long one. The program's length/truncation heuristic is recorded as
`content_basis_estimate` and shown to reviewers in the report; it never affects scoring.

When reviewing a feed, sample several articles of different lengths and compare the feed
body with the article page. Declare `full_text` only when the feed reliably ships the
whole piece; declare `excerpt` when it only ships teasers, so the source can never be
promoted on a body it does not have.

## Intelligence mainlines

`intelligence_lines` answers a different question from `editorial_lanes`: the lane decides
how an item is judged, the mainline says why the source is monitored at all.

| code | meaning |
|---|---|
| `policy_regulation` | policy, regulation, formal documents |
| `macro_economy` | official statistics, central banks, macro data |
| `corporate_capital` | earnings, investor relations, regulated disclosure |
| `industry_supply_chain` | industry structure, energy, supply chains |
| `international_news` | wires and mainstream media as a discovery layer |
| `technology_research` | research, open source, product releases |
| `market_opportunity` | user pain, procurement, hiring, unmet demand |
| `engineering_specialist` | CAE/CFD and other professional engineering signals |
| `system_maintenance` | tooling updates; never enters the briefing |

Rules:

- A source may declare several lines, separated like `editorial_lanes`
  (`macro_economy,technology_research`). Order is normalised on read.
- **One line is not inferred.** A registry without the column parses as undeclared and
  the audit emits `missing_intelligence_lines` (warning). `tools/migrate_intelligence_lines.py`
  adds the column with explicit per-source values and reports what it could not fill.
- An unknown token is an error (`invalid_intelligence_line`), not silently ignored.
- `system_maintenance` is the only line that may exist without `editorial_lanes`; such a
  row is maintenance information and must stay disabled.
- The mainline is **reporting metadata only**. It does not enter `scoring.py`,
  `evidence.py` or `lanes.py`. The daily report prints a per-line count in the data
  overview; items from undeclared sources are counted as `(undeclared)` rather than
  guessed into a line.

The boundary between source-level and item-level classification: the registry declares
what a source is *for*; the item's lane still comes from its content (`lanes.derive_lane`).
No item is assigned a mainline beyond the one its source declared.

## Full-text fetching

`full_text_fetch` is `none` (default) or `article_page`. It answers a narrow question:
may the pipeline request the linked page to obtain the body? It says nothing about
whether the body is complete, and enabling it does **not** raise the evidence rank.

- Only sources that declare `article_page` are fetched. All other sources keep the feed text.
- The fetcher reads robots.txt first, refuses 401/403/429, refuses cross-host redirects,
  refuses paywall markers and short bodies, and caps a run at 20 pages.
- A fetched body replaces `article.summary` and the original feed text is kept in
  `article.feed_summary`; `content_source` becomes `article_page`.
- `content_access_level=full_text` remains a separate review decision: only that
  declaration lets `content_basis()` return `full_text` and reach E2. Review the fetched
  body first, then change the declaration. See `docs/FULL_TEXT_FETCH.md`.
- An invalid value is an audit error (`invalid_full_text_fetch`); a registry without the
  column defaults to `none`.

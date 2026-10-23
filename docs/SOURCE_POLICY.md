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

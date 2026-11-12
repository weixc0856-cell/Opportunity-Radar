# Architecture

1. FreshRSS manages approved subscriptions.
2. `freshrss_client.py` reads the FreshRSS Fever API; it does not crawl arbitrary sites.
3. `source_policy.py` reads the local source register. Keep FreshRSS subscriptions limited to approved sources.
4. `analyzer.py` sends one article at a time to the local model.
5. `schema.py` validates model output; `classifier.py` derives deterministic commercial signals.
6. `evidence.py` decides how much source text we hold (`content_basis`) and what it can support
   (`evidence_state`); `lanes.py` routes the article to editorial lane A, B or C; `scoring.py`
   computes a deterministic per-lane ranking that is gated by the evidence state.
7. `digest.py` renders two editions from one item set: the emailed brief (sections 1–7 plus an
   appendix note) and the complete report with traceable appendices. `render_html.py` follows the
   same split; `Store.save_report_sections` keeps appendices in SQLite by report hash.
8. `email_sender.py` sends SMTP mail using the brief edition only.
9. SQLite stores analysis and run records.
10. `publication.py` decides PASS / PASS_WITH_LIMITATIONS / HOLD from analysis coverage; HOLD sends nothing.
11. R1: `unified.py` builds events, evidences and claims from what was already stored; `linking.py` adds
    entities, mentions and candidate links; `lineage.py` maps each source to the organisation behind it.
    `articles.source_id` binds each stored article to its approved source; `unified_main sources`
    backfills it from analysis metadata or an unambiguous source-name match, and leaves ambiguous or
    unknown names empty. A v5 fact is prose, so its skeleton claim has an empty `period`: the article
    publication date is stored on the article/evidence and is never treated as the fact's period.
    `unified_main periods` audits old skeleton claims and, only when the period exactly equals the
    article publication date and `period_raw` is empty, clears it in an append-only
    `claim_corrections` log; every other case is reported as pending. Claim/evidence writes require
    a source id, a locator, and at least one valid evidence link; rejected records are counted and
    named in the command report. Business commands open the store with `migrate=False`: a database
    below the code schema raises `SchemaVersionError` and points to `unified_main db-migrate`; only
    that explicit command uses `--apply` (with a required backup) to migrate. `audit`, `report` and
    `--render-only` stay read-only. `unified_main extract` reads stored titles, evidence quotes and claim
    text (never a new full-text fetch) and records deterministic entity mentions with category, raw
    text, article/evidence/claim key, locator, method and confidence. A source name is a
    FreshRSS/feed label (`INGESTED_FROM`), not a publisher; `PUBLISHED_BY` requires an explicit
    publisher identity and is not generated from source_name. Explicit sentence cues may add
    APPLICANT, PETITIONER or REGULATED_BY as unverified relations; AFFECTED_BY and RELATED_TO are
    not inferred. `unified_main audit` is a read-only end-to-end check of source, evidence, claim,
    event, entity and relation consistency.
    `unified_main candidates` compares event pairs using normalised
    titles, shared entities, shared evidence sentences and the time window; a strong candidate needs
    a signal beyond title similarity, title-only matches are at most weak, and no event membership is
    changed. `event_profile` reports articles, source ids, source families and independent source
    units separately; unknown families never count, and a recorded syndication group collapses its
    members into one unit. Event profiles also expose `EVIDENCE_BACKED` / `NO_EVIDENCE` /
    `INSUFFICIENT_EVIDENCE`; an event with no valid evidence remains visible but is not presented as
    a verified fact. Text, HTML and email share `event_summary_lines`; the archived `items.json`
    keeps the raw `event.evidence_status` and `event_context`. When event context is missing,
    `cli.attach_event_context` records `NOT_FOUND`, `UNAVAILABLE`, `READ_FAILED` or
    `SCHEMA_UNSUPPORTED`; the article evidence state is retained but never promoted to an event
    state. HTML and text both render v5 facts, inferences, gaps and actions. The B lane remains an
    article-level candidate; it is not automatically a stored Opportunity. `cli.attach_event_context`
    attaches R1 context to the digest, and the
    digest prints one card per event instead of one per article.
12. SEC/EIA keep their own database and entry points (`ingest/`); they share the R1 table contract but
    never write to the RSS database. `deploy/windows/run-sources.ps1` runs SEC, EIA, Federal Register
    and BLS before the daily CLI, each into its own store; `reports/sources/latest.json` records one
    status per source (`ok` / `not_configured` / `failed`, plus GDELT `frozen` on HTTP 429) and the
    digest prints that status line. Only statuses cross the boundary — never observations, quotes or
    claims from those sources.
13. The claim pipeline (`docs/CLAIM_PIPELINE.md`) has six offline nodes. `article_text.py` (N0)
    normalises the title and body into text with paragraph and sentence IDs, document offsets and
    raw-HTML spans; `numeric_candidates.py` (N1) lists every numeric expression as an atom,
    including word quarters and month-only periods, and records ranges, from/to, direction and
    comparison statements as expression groups. `n2_semantic.py` first asks whether each atom is
    economic (`economic`/`non_economic`/`uncertain`) and then what it describes (subject, measure,
    claim or context); the program downgrades non-economic claim values, expands document-defined
    subject acronyms, rebuilds generic/partial predicates from the subject, and promotes a bounded
    amount only when the same sentence has exactly one economic claim. `n3_relationships.py`
    asks what relation the text states, with program checks for IDs, enums, coverage, evidence
    location and comparison wording; it also receives every document period candidate and can
    deterministically attach a same-sentence period or a title period of the same month/quarter,
    without inventing a year. It labels each candidate in_batch, performs one focused model
    retry for omitted candidates, and applies deterministic rate/change and period-comparison
    corrections only to relationships the model already emitted. `n4_normalization.py` (N4) turns those semantics into
    value/unit/scale/currency/period records, preserving period raw text and locator, without
    re-deciding anything. `n5_assembly.py` (N5) disposes every N1 candidate, merges semantically
    identical r2-v4 claims while preserving all relationship/evidence lineage, folds a level that is
    only the evidence endpoint of a change back into that change, and assembles r2-v4 claims. `pipeline_store.py` keeps the runs in a separate append-only SQLite file, reuses the
    latest usable result for the same input, and records per-batch tokens/timing. The nodes
    themselves do not write the production database; `pipeline.py` promotes accepted N5 claims
    into `claims`/`evidences` after the same r2-v4 contract checks.
14. Schema v9 adds the four Opportunity tables: `opportunities`, `opportunity_links`,
    `opportunity_hypotheses`, `opportunity_revisions`. `opportunity.py` is the minimal data access
    layer: stable canonical IDs, polymorphic link target checks, append-only hypotheses/revisions,
    and revision triggers that reject UPDATE/DELETE. `opportunity_audit.py` checks targets,
    ownership, projection and validation gates. `opportunity_discovery.py` creates
    `signal_detected` rows only, from evidence-backed B seeds; it never infers problem_supported,
    buyer_identified or payment_verified.
15. `opportunity_candidates.py` is the read-only B-seed mapping path used by
    `unified_main b-candidates`. It opens the source database with SQLite `mode=ro`, reads stored
    `analyses.result_json.scoring` and the R1 Event/Evidence/Claim/entity/lineage tables, and writes
    only `reports/opportunity-candidates.json` / `.md`. It classifies candidates as evidence-backed,
    signal-only or insufficient mapping, suggests duplicate clusters without merging, and exposes a
    per-candidate human review status. It never creates Opportunity rows, links, hypotheses or revisions.
16. `opportunity_review.py` is the Batch 12 explicit-creation boundary used by
    `unified_main b-review validate|preview|apply`. It validates a review manifest and its
    source-report hash, checks real Article/Event/Evidence/Claim/Entity references, previews
    canonical-key conflicts, and creates an Opportunity with its seed/context/fact links and first
    Revision in one transaction. Apply requires `--apply`, refuses the production path, refuses a
    schema below v9, and never migrates. Existing canonical keys are idempotent only when the
    payload matches exactly; otherwise they are conflicts, never merged. Batch 13 adds a fail-closed
    apply target allowlist (canonical path plus file identity, rejecting symlinks, hardlinks to
    production, traversal, missing paths and any v9 database outside the allowlist) and requires a
    human review manifest before an AI-assisted manifest can request creation.

The order in step 6 matters. Evidence is established before scoring, so a lane can never
promote an item whose quotes could not be located in the text we actually received. See
`docs/EVIDENCE_AND_LANES.md` for the state table, the lane weights and the promotion gates.

RSS content is untrusted input and may contain prompt injection. The model has no tools and cannot initiate network requests. Secrets are never included in prompts.

17. `pipeline.py` is the single post-analysis production chain used by the daily CLI. After
    `attach_event_context` has filed this run's articles, it runs, in order: R1 backfill
    (`unified_main rss`), the bounded N0–N5 claim pipeline (default 8 new articles per run,
    model calls only when N1 found numeric candidates), entity seeding/extraction, lineage,
    event candidates, verification (`verify.py`), Opportunity discovery, the economic engine
    and a quality snapshot. Every step is recorded in `stats.pipeline`; a blocking failure in
    R1 backfill forces HOLD. The N0–N5 bound, skipped count and per-article status are printed,
    never hidden. `OR_PIPELINE_ENABLED=0` disables the chain for isolated tests.
18. R3 editorial priority lives in `scoring.py`: the public `score` is unchanged, and each item
    also carries `signal_score` (uncapped importance), `evidence_score` (E0/E1/E2 strength) and
    `editorial_priority` P0–P3/REJECT with a deterministic `priority_basis`. The digest orders
    event representatives by priority first, score second; source caps still only defer items.
19. `period_report.py` builds weekly and monthly reports by querying events, evidences, claims,
    opportunities and the economic store for a date window. Claim/evidence windows use the
    article's publication time, not the backfill timestamp. `cli --period weekly|monthly` writes
    one report; `--period auto` (used by the scheduled task) writes weekly every 7 days and
    monthly every 30 days, with catch-up by the last report's mtime.
20. `economic.py` is the R5 store (`data/economic/economic.sqlite3`). It syncs BLS macro series
    from the pilot database and EIA observations from the isolated ingest database, keeps the
    current observation plus every distinct revision in `observation_versions`, and derives MoM
    and YoY with the formula and inputs recorded in `derived_metrics`. It never writes the RSS
    business tables and never turns a series into an article.
21. `quality.py` is the R6 measurement layer. It computes claim locator/verification rates,
    event evidence/claim coverage, independent-source events, run failure rate and gate escapes
    from stored rows, records a 30-day backtest, reads the frozen N1 benchmark, and appends a
    snapshot to `data/quality/quality.sqlite3` plus `reports/quality/latest.{json,md}`. Metrics
    with no real benchmark (event clustering precision/recall) are labelled `NOT_MEASURED`.

22. `display.py` separates discovery from display. It computes a pure `display_tier`
    (L0 verified / L1 located-but-unverified / L2 weak signal / L3 filtered) for claims,
    Opportunities and links, with a machine-readable reason. `cli.build_watchlist` collects
    `signal_detected` Opportunities, articles with N1 candidates but no r2-v4 claim, and
    unconfirmed event-candidate links; both digest editions print them in “待观察信号”.
    This changes no score, no gate and no stored row — a weak signal is kept and shown, not
    promoted.

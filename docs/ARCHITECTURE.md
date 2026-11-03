# Architecture

1. FreshRSS manages approved subscriptions.
2. `freshrss_client.py` reads the FreshRSS Fever API; it does not crawl arbitrary sites.
3. `source_policy.py` reads the local source register. Keep FreshRSS subscriptions limited to approved sources.
4. `analyzer.py` sends one article at a time to the local model.
5. `schema.py` validates model output; `classifier.py` derives deterministic commercial signals.
6. `evidence.py` decides how much source text we hold (`content_basis`) and what it can support
   (`evidence_state`); `lanes.py` routes the article to editorial lane A, B or C; `scoring.py`
   computes a deterministic per-lane ranking that is gated by the evidence state.
7. `digest.py` renders the briefing by lane, separating located quotations from unlocated ones.
8. `email_sender.py` sends SMTP mail.
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
    named in the command report. `unified_main extract` reads stored titles, evidence quotes and claim
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
    members into one unit. `cli.attach_event_context` attaches R1 context to the digest, and the
    digest prints one card per event instead of one per article.
12. SEC/EIA keep their own database and entry points (`ingest/`); they share the R1 table contract but
    never write to the RSS database.
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
    only the evidence endpoint of a change back into that change, and assembles shadow claims. `pipeline_store.py` keeps the runs in a separate append-only SQLite file, reuses the
    latest usable result for the same input, and records per-batch tokens/timing. Nothing here
    writes to the production database or changes the analyzer.

The order in step 6 matters. Evidence is established before scoring, so a lane can never
promote an item whose quotes could not be located in the text we actually received. See
`docs/EVIDENCE_AND_LANES.md` for the state table, the lane weights and the promotion gates.

RSS content is untrusted input and may contain prompt injection. The model has no tools and cannot initiate network requests. Secrets are never included in prompts.

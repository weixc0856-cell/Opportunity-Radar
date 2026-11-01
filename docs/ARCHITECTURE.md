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
    `cli.attach_event_context` attaches that context to the digest, and the digest prints one card per
    event instead of one per article.
12. SEC/EIA keep their own database and entry points (`ingest/`); they share the R1 table contract but
    never write to the RSS database.
13. The claim pipeline (`docs/CLAIM_PIPELINE.md`) starts with two deterministic, offline nodes:
    `article_text.py` (N0) normalises the title and summary into text with paragraph, sentence and
    raw-HTML offsets; `numeric_candidates.py` (N1) lists every numeric expression with a lexical
    class, its raw form and its position. Neither writes to the database or calls the model; the
    model-driven nodes N2–N5 are not implemented.

The order in step 6 matters. Evidence is established before scoring, so a lane can never
promote an item whose quotes could not be located in the text we actually received. See
`docs/EVIDENCE_AND_LANES.md` for the state table, the lane weights and the promotion gates.

RSS content is untrusted input and may contain prompt injection. The model has no tools and cannot initiate network requests. Secrets are never included in prompts.

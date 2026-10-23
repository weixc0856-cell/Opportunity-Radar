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

The order in step 6 matters. Evidence is established before scoring, so a lane can never
promote an item whose quotes could not be located in the text we actually received. See
`docs/EVIDENCE_AND_LANES.md` for the state table, the lane weights and the promotion gates.

RSS content is untrusted input and may contain prompt injection. The model has no tools and cannot initiate network requests. Secrets are never included in prompts.

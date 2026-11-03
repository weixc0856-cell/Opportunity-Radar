# Source Pilot Status

Last updated: 2026-11-02
Baseline: `main@1c45b9b`; N0–N5 frozen at Batch 16.

This file records only the isolated source-pilot state. It does not change the production
status in `PROJECT_STATUS.md`.

---

## GDELT

| Dimension | Status | Evidence |
|---|---|---|
| Code and offline tests | **PASS** | `opportunity_radar/pilot/gdelt.py`; 16 pilot tests at GDELT stage, 36 total after BLS additions; fixture parsing, canonicalization, dedupe, matching, isolation, empty-response failure |
| Live acquisition | **LIVE_BLOCKED / NOT_VERIFIED** | Last request 2026-11-02T09:26:44Z; HTTP 200 `{}` and repeated HTTP 429; no valid articles returned |
| Real-data parsing | **NOT_VERIFIED** | No live article list; fixture only |
| RSS-external incremental value | **NOT_EVALUATED** | No live candidates |
| Production isolation | **PASS** | Production SHA256 unchanged: `234a0e50310fb0d49429e4311ba282e236eb234dc808d97f24f580962472d8f3` |
| Completion | **NOT COMPLETE** | Do not mark completed or permanently unavailable |

History:

- run 1: HTTP 200, body `{}`, recorded as success/0 before the empty-payload rule; retained as a historical artifact and not live acceptance evidence.
- run 2: HTTP 429, `rate_limit`, recorded as failed.
- Controlled one-request mode added; 429 stops immediately without retry.
- 5-minute and 10-minute cooldown probes both returned 429.
- No GDELT request has been made since the last probe at 2026-11-02T09:26:44Z.

Recovery condition:

- After the network environment permits it, **one human-authorized controlled retest**:
  ```powershell
  .\.venv\Scripts\python.exe -m opportunity_radar.pilot gdelt `
    --live --controlled --query-text "artificial intelligence" `
    --max-records 10 --timespan 7d
  ```
- One query, one HTTP request, no retry on 429. If 429 persists, mark `LIVE_BLOCKED`; do not probe continuously, use a proxy, or switch to Bulk Export without approval.

---

## Federal Register

| Dimension | Status | Evidence |
|---|---|---|
| Code and offline tests | **PASS** | `opportunity_radar/pilot/federal_register.py`; 26 pilot tests at FR stage, 36 total after BLS additions; type mapping, content hash, versions, pagination, zero-result handling, FDA watch config, isolation |
| Live acquisition | **PASS (limited window)** | 9 watch rows / 8 agencies configured; original 8 watches 8/8 HTTP 200; FDA-only 1 request HTTP 200; `since=2026-10-26` |
| Real-data parsing | **PASS (limited sample)** | 17 documents total; initial 8 + FDA 9; types NOTICE 8, PRORULE 4, RULE 5; 0 invalid |
| Version handling | **PASS (offline) / unchanged live** | Offline content-change test; live re-runs recorded 8 unchanged and 0 new versions for the original watches; FDA 9 initial versions |
| Zero-result handling | **PASS** | HTTP 200 `{"count":0}` treated as valid empty, not schema failure |
| Production isolation | **PASS** | Same production SHA256; pilot DB `user_version=2`; no production tables written |
| Commercial-value validation | **NOT_EVALUATED** | No business-value claim made from 17 documents |
| Stage status | **FROZEN** | FDA coverage confirmed; no further Federal Register changes without new authorization |

History:

- run 3 (before zero-result fix): HTTP 200 with `{"count":0}` was treated as schema failure for 4 zero-result watches; retained as history.
- run 4/5 (after fix): original 8/8 watch queries HTTP 200; 8 documents unchanged; 0 errors; 8 versions.
- run 6 (FDA-only): 1 request HTTP 200; 9 documents inserted; 0 errors; 9 initial versions.
- Zero-result payloads now become valid empty results; missing `results` with `count>0` remains a schema failure.

Known limitations:

- Watchlist covers 8 approved agencies with 9 watch rows because Commerce has two watches.
- Live documents were returned for Commerce, Energy, FCC, EPA and FDA; Treasury, USTR and FTC returned valid zero results in the 7-day window.
- Live validation used `max_pages=1`; multi-page live pagination was not exercised, but an offline two-page test covers it.
- Only a 7-day window (`2026-10-26` onward) was tested.
- Zero-result watches (`commerce-ai`, `treasury-tariff`, `ustr-trade`, `ftc-ai`) are valid empty results, not failures.
- FDA watch uses the term `medical device`; `artificial intelligence` returned zero in the same window.
- No automatic event/evidence/claim links; no scoring/digest integration.
- The API is a prototype, not the official legal edition; legal text must be checked against govinfo.
- No subscriber display or redistribution in the pilot.

---

## BLS

| Dimension | Status | Evidence |
|---|---|---|
| Official series basis | **PASS** | 9 IDs verified via BLS Data Viewer/API v1: CES0000000001, LNS14000000, CES0500000003, CUSR0000SA0, CUUR0000SA0, JTS000000000000000JOL, JTS000000000000000HIL, JTS000000000000000QUL, PRS85006092 |
| Code and offline tests | **PASS** | `opportunity_radar/pilot/bls.py`; 36 total pilot tests; 10 BLS tests |
| Live acquisition | **PASS (limited)** | BLS API v1, no key; this pilot requested 2017–2026 (10-year window); limited 2-series run 8 (1 request, 234 observations); full 9-series run 9 (1 request, 971 observations); repeat runs 10/11 (971 unchanged each) |
| Real-data parsing | **PASS (limited)** | 971 observations; monthly 933, quarterly 38; 3 missing-value observations preserved; 0 invalid periods |
| Version handling | **PASS (offline) / unchanged live** | Offline revision test; live repeats recorded 971 unchanged; no real revision observed between runs 9 and 11 |
| Production isolation | **PASS** | Same production SHA256; pilot DB `user_version=4`; no production tables written |
| Commercial-value validation | **NOT_EVALUATED** | 971 observations prove pipeline correctness only |
| Stage status | **FROZEN / PASS_LIMITED** | Stop here; do not start other sources |

History:

- run 7 (before schema v4): `UNIQUE(series_id, period_raw)` collapsed the same month across years; 234 rows were recorded as 24 inserted + 210 updated. This was a schema defect, not a valid collection.
- v4 rebuild: macro tables recreated with `UNIQUE(series_id, year, period_raw)`; run 7 macro data removed; run 7 record retained as historical.
- run 8 (limited): 2 series, 234 inserted, 0 errors; requested 2017–2026.
- run 9 (full): 9 series, 971 observations (737 inserted + 234 unchanged), 0 errors, 971 versions; requested 2017–2026.
- run 10 (repeat): 971 unchanged, 0 errors, version count unchanged at 971; requested 2017–2026.
- run 11 (repeat after CES unit correction): 971 unchanged, 0 errors, version count unchanged at 971; requested 2017–2026.

Known limitations:

- BLS API v1 allows at most 10 years of data per request. This pilot's collection window is **2017–2026** (a 10-year request window); the API is not limited to 2017–2026.
- BLS API v1 also has no key, 25 queries/day, and 25 series/request.
- No BLS API key; no v2 catalog/20-year range.
- `preliminary` / `latest` recorded only when BLS provided the fields/footnotes; older observations may have `NULL` rather than 0.
- 3 `missing_value` observations preserve `value_raw` and do not invent a value.
- No real revision occurred between run 9 and run 11; revision handling is covered by an offline test.
- No release-calendar integration; no event/evidence/claim links; no scoring/digest.
- No subscriber display or redistribution.
- Commercial intelligence value is not validated.

---

## Value review

| Item | Status |
|---|---|
| Report | `docs/SOURCE_PILOT_VALUE_REVIEW.md` |
| Review status | **COMPLETE** |
| Source Pilot stage | **FROZEN / CLOSED** (final review 2026-11-02) |
| Federal Register value | **MEDIUM** (3 HIGH are abstract/metadata information potential only; not verified commercial value) |
| BLS value | **MEDIUM** (macro-background layer; descriptive changes are not business opportunities) |
| FR/RSS same-event | **0/17** confirmed; 3 RELATED; 14 UNMATCHED in current RSS; external coverage UNKNOWN |
| FR/RSS timing | No SAME_EVENT, so **FR earlier than RSS is not proven**; 1 RELATED case (2026-21884) is not counted |
| FR impact objects | Industry/category explicit **14/17**; document-level named companies **3/17** (2026-21818, 2026-22302, 2026-22337); NOT_EVALUATED **3/17** (FDA PRA) |
| Entity roles | 7 companies + 1 association; **0 explicitly direct-regulated**; 2 companies explicit applicant/petitioner; 4 inferred potentially affected; 2 formal role UNKNOWN. The 4 inferred cases must not be merged with the 2 explicit roles. |
| FR evidence depth | Full text **5/17**; abstract/metadata **12/17** |
| Cross-source links | 0 confirmed; no forced FR/BLS/RSS association |
| H1 / H2 | **COMPLETE** |
| H3–H7 | **NOT_STARTED** |
| Next stage | Source Pilot frozen; no further FR audits or source expansion; next phase must be separately defined |
| New sources | **None** |

---

## Boundary

- Pilot data lives in `data/pilot/source_pilot.sqlite3` and `reports/pilot/`.
- Production RSS, SEC/EIA, R0/R1, N0–N5, scoring, digest and gate behavior are unchanged.
- GDELT remains discovery-only; Federal Register remains policy-document-only; BLS remains macro-observation-only.
- No Pilot data is promoted into production claims/analyses/events/evidences.

"""Independent ingestion channel for SEC EDGAR and EIA.

Authorised by G-D2 (docs/IMPLEMENTATION_AUTHORIZATION_2026-11-01.md).
Scope: data acquisition, normalisation, storage, quality validation only.

Hard isolation rules (do not relax without a new authorization):
- Own SQLite file; never the production database.
- Own entry points; never imported by cli.main().
- Never write articles / analyses / analysis_history / analysis_sections / runs.
- Never feed the existing LLM analysis, scoring, evidence gates or digest.
"""
VERSION = '1.0'

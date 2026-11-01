"""Source rights policy for the ingest channel.

Design doc v0.8 §7: SEC's own records are reusable; company filings carry third-party
material that is not automatically cleared. EIA official data is public domain with
attribution. Anything not assessed is `unknown` and blocks use — silence is not permission.

This is a policy check, not an HTTP failure: a rights refusal is raised before any request or
write, and is never produced by disguising a network error.
"""
from __future__ import annotations
from .http import IngestError, RIGHTS

APPROVED = 'approved'
UNKNOWN = 'unknown'
BLOCKED = 'blocked'

POLICY = {
    'sec-edgar': {
        'status': APPROVED,
        'official_data': True,
        'third_party_content': False,
        'attribution': 'SEC EDGAR',
        'basis': 'design doc §7: SEC-authored content reusable; company filings stored as-is',
    },
    'eia': {
        'status': APPROVED,
        'official_data': True,
        'third_party_content': False,
        'attribution': 'U.S. Energy Information Administration',
        'basis': 'design doc §7: EIA official data is public domain with attribution',
    },
}


def assert_source_allowed(source_id):
    entry = POLICY.get(source_id)
    if entry is None:
        raise IngestError(RIGHTS, f'source {source_id!r} has no rights assessment; refusing to run')
    if entry['status'] != APPROVED:
        raise IngestError(RIGHTS, f'source {source_id!r} is {entry["status"]}; refusing to run')
    return entry


def assert_content_usable(source_id, third_party=False):
    """Third-party material inside a filing is not cleared for redistribution by default."""
    entry = assert_source_allowed(source_id)
    if third_party and not entry.get('third_party_cleared', False):
        raise IngestError(RIGHTS,
                          f'{source_id}: third-party content is not marked as cleared; '
                          'store metadata only, do not redistribute')
    return entry

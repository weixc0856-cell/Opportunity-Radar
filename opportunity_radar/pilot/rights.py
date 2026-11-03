"""Pilot source rights gate.

The pilot registry carries the review decision. Anything missing, disabled or not
explicitly allowed is refused before a request is made or a record is written.
"""
from __future__ import annotations

from .config import PilotConfigError, pilot_source

BODY_STORAGE = {
    # GDELT returns discovery metadata only. Its upstream article bodies are not covered
    # by GDELT's own licence, so the pilot never stores them.
    'gdelt': False,
}

DISPLAY_ALLOWED = {
    # Pilot decision: none of the three sources is displayed to subscribers during the
    # four-week observation window, even where the source licence would permit it later.
    'gdelt': False,
}


class PilotRightsError(PermissionError):
    pass


def assert_source_allowed(source_id):
    try:
        source = pilot_source(source_id)
    except PilotConfigError as exc:
        raise PilotRightsError(str(exc)) from exc
    if not source.enabled:
        raise PilotRightsError(f'pilot source is disabled: {source_id}')
    if source.commercial_use not in {'ALLOWED', 'CONDITIONAL'}:
        raise PilotRightsError(
            f'pilot source {source_id} has commercial_use={source.commercial_use}'
        )
    if source.subscriber_display not in {'ALLOWED', 'CONDITIONAL', 'PROHIBITED'}:
        raise PilotRightsError(
            f'pilot source {source_id} has invalid subscriber_display'
        )
    return source


def assert_body_storage_allowed(source_id, body_kind='article_body'):
    assert_source_allowed(source_id)
    if body_kind == 'article_body' and not BODY_STORAGE.get(source_id, False):
        raise PilotRightsError(
            f'{source_id}: storing upstream article bodies is not allowed in the pilot'
        )
    return True


def assert_subscriber_display_allowed(source_id):
    assert_source_allowed(source_id)
    if not DISPLAY_ALLOWED.get(source_id, False):
        raise PilotRightsError(
            f'{source_id}: subscriber display is disabled during the pilot'
        )
    return True

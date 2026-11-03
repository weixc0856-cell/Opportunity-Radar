"""Configuration for the isolated source pilot.

The pilot has its own registry, database, snapshot directory and report directory.
It never inherits the RSS, SEC/EIA or claim-pipeline settings.
"""
from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from opportunity_radar.ingest.config import assert_isolated_db


class PilotConfigError(ValueError):
    pass


def _env(name, default=''):
    return os.getenv(name, default).strip()


def _path(value):
    return str(Path(value).expanduser())


@dataclass(frozen=True)
class PilotSettings:
    db_path: str
    report_dir: str
    snapshot_dir: str
    production_db: str
    user_agent: str
    gdelt_base_url: str
    timeout: int
    gdelt_min_interval: float
    max_records: int
    fr_base_url: str = 'https://www.federalregister.gov/api/v1'
    fr_min_interval: float = 1.0
    bls_base_url: str = 'https://api.bls.gov/publicAPI/v1'
    bls_min_interval: float = 1.0

    @classmethod
    def from_env(cls):
        try:
            timeout = max(1, int(_env('OR_PILOT_TIMEOUT_SECONDS', '30')))
            interval = max(0.0, float(_env('OR_PILOT_GDELT_MIN_INTERVAL', '5')))
            max_records = max(1, min(250, int(_env('OR_PILOT_GDELT_MAX_RECORDS', '250'))))
            fr_interval = max(0.0, float(_env('OR_PILOT_FR_MIN_INTERVAL', '1')))
            bls_interval = max(0.0, float(_env('OR_PILOT_BLS_MIN_INTERVAL', '1')))
        except ValueError as exc:
            raise PilotConfigError(f'invalid numeric setting: {exc}') from exc
        db_path = _path(_env('OR_PILOT_DB_PATH', 'data/pilot/source_pilot.sqlite3'))
        snapshot_dir = _path(_env('OR_PILOT_SNAPSHOT_DIR', str(Path(db_path).parent / 'snapshots')))
        return cls(
            db_path=db_path,
            report_dir=_path(_env('OR_PILOT_REPORT_DIR', 'reports/pilot')),
            snapshot_dir=snapshot_dir,
            production_db=_path(_env('OR_PILOT_PRODUCTION_DB', 'data/opportunity_radar.sqlite3')),
            user_agent=_env('OR_PILOT_USER_AGENT', 'OpportunityRadar-Pilot/0.1 (local research)'),
            gdelt_base_url=_env('OR_PILOT_GDELT_BASE_URL',
                                'https://api.gdeltproject.org/api/v2/doc/doc').rstrip('/'),
            timeout=timeout,
            gdelt_min_interval=interval,
            max_records=max_records,
            fr_base_url=_env('OR_PILOT_FR_BASE_URL',
                             'https://www.federalregister.gov/api/v1').rstrip('/'),
            fr_min_interval=fr_interval,
            bls_base_url=_env('OR_PILOT_BLS_BASE_URL',
                              'https://api.bls.gov/publicAPI/v1').rstrip('/'),
            bls_min_interval=bls_interval,
        )

    def validate(self):
        if not self.gdelt_base_url.startswith('https://'):
            raise PilotConfigError('GDELT base URL must be https')
        if not self.fr_base_url.startswith('https://'):
            raise PilotConfigError('Federal Register base URL must be https')
        if not self.bls_base_url.startswith('https://'):
            raise PilotConfigError('BLS base URL must be https')
        if self.timeout < 1:
            raise PilotConfigError('timeout must be positive')
        if self.fr_min_interval < 0:
            raise PilotConfigError('Federal Register interval must not be negative')
        if self.bls_min_interval < 0:
            raise PilotConfigError('BLS interval must not be negative')
        if self.max_records < 1 or self.max_records > 250:
            raise PilotConfigError('max_records must be between 1 and 250')
        # The same isolation rule the ingest channel uses. The production DB can never
        # become the pilot store by accident.
        assert_isolated_db(self.db_path, production={Path(self.production_db)})
        if Path(self.db_path).resolve() == Path(self.production_db).resolve():
            raise PilotConfigError('pilot DB must not be the production DB')
        return self


@dataclass(frozen=True)
class PilotSource:
    source_id: str
    name: str
    source_type: str
    access_method: str
    base_url: str
    terms_url: str
    license_url: str
    commercial_use: str
    local_cache: str
    long_term_storage: str
    analysis_use: str
    subscriber_display: str
    redistribution: str
    attribution_required: str
    retention_limit: str
    enabled: bool
    cadence: str
    notes: str


SOURCE_FIELDS = [
    'source_id', 'name', 'source_type', 'access_method', 'base_url', 'terms_url',
    'license_url', 'commercial_use', 'local_cache', 'long_term_storage',
    'analysis_use', 'subscriber_display', 'redistribution', 'attribution_required',
    'retention_limit', 'enabled', 'cadence', 'notes',
]


def load_pilot_sources(path=None):
    source_path = Path(path or _env('OR_PILOT_SOURCES_PATH', 'config/pilot_sources.csv'))
    if not source_path.exists():
        return []
    out = []
    with source_path.open(encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            values = {key: str(row.get(key) or '').strip() for key in SOURCE_FIELDS}
            values['enabled'] = values['enabled'].lower() in {'true', '1', 'yes'}
            out.append(PilotSource(**values))
    return out


def pilot_source(source_id, path=None):
    for source in load_pilot_sources(path):
        if source.source_id == source_id:
            return source
    raise PilotConfigError(f'pilot source not registered: {source_id}')


@dataclass(frozen=True)
class GdeltQuery:
    query_id: str
    query: str
    timespan: str
    max_records: int
    language: str
    country: str
    enabled: bool
    notes: str


GDELT_QUERY_FIELDS = [
    'query_id', 'query', 'timespan', 'max_records', 'language', 'country',
    'enabled', 'notes',
]


def load_gdelt_queries(path=None):
    query_path = Path(path or _env('OR_PILOT_GDELT_QUERIES_PATH',
                                   'config/pilot_gdelt_queries.csv'))
    if not query_path.exists():
        raise PilotConfigError(f'GDELT query file not found: {query_path}')
    out = []
    seen = set()
    with query_path.open(encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            values = {key: str(row.get(key) or '').strip() for key in GDELT_QUERY_FIELDS}
            if not values['query_id'] or not values['query']:
                raise PilotConfigError('GDELT query rows require query_id and query')
            if values['query_id'] in seen:
                raise PilotConfigError(f'duplicate GDELT query_id: {values["query_id"]}')
            seen.add(values['query_id'])
            try:
                max_records = int(values['max_records'] or '250')
            except ValueError as exc:
                raise PilotConfigError(f'invalid max_records for {values["query_id"]}') from exc
            if max_records < 1 or max_records > 250:
                raise PilotConfigError(f'max_records out of range for {values["query_id"]}')
            values['max_records'] = max_records
            values['enabled'] = values['enabled'].lower() in {'true', '1', 'yes'}
            if not values['timespan']:
                values['timespan'] = '1d'
            out.append(GdeltQuery(**values))
    if not out:
        raise PilotConfigError(f'no GDELT queries found in {query_path}')
    return out


@dataclass(frozen=True)
class FederalRegisterWatch:
    watch_id: str
    agency_slug: str
    term: str
    document_types: str
    enabled: bool
    max_documents: int
    notes: str

    @property
    def types(self):
        return [value.strip().upper() for value in self.document_types.split(',')
                if value.strip()]


FEDERAL_REGISTER_WATCH_FIELDS = [
    'watch_id', 'agency_slug', 'term', 'document_types', 'enabled',
    'max_documents', 'notes',
]
FEDERAL_REGISTER_TYPES = {'RULE', 'PRORULE', 'NOTICE', 'PRESDOC'}


def load_federal_register_watchlist(path=None):
    watch_path = Path(path or _env('OR_PILOT_FR_WATCHLIST_PATH',
                                   'config/pilot_federal_register_watchlist.csv'))
    if not watch_path.exists():
        raise PilotConfigError(f'Federal Register watchlist not found: {watch_path}')
    out = []
    seen = set()
    with watch_path.open(encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            values = {key: str(row.get(key) or '').strip()
                      for key in FEDERAL_REGISTER_WATCH_FIELDS}
            if not values['watch_id'] or not values['agency_slug'] or not values['term']:
                raise PilotConfigError('Federal Register rows require watch_id, agency_slug and term')
            if values['watch_id'] in seen:
                raise PilotConfigError(f'duplicate Federal Register watch_id: {values["watch_id"]}')
            seen.add(values['watch_id'])
            try:
                max_documents = int(values['max_documents'] or '50')
            except ValueError as exc:
                raise PilotConfigError(
                    f'invalid max_documents for {values["watch_id"]}'
                ) from exc
            if max_documents < 1 or max_documents > 200:
                raise PilotConfigError(
                    f'max_documents out of range for {values["watch_id"]}'
                )
            values['max_documents'] = max_documents
            values['enabled'] = values['enabled'].lower() in {'true', '1', 'yes'}
            types = [value.strip().upper() for value in values['document_types'].split(',')
                     if value.strip()]
            if not types or any(value not in FEDERAL_REGISTER_TYPES for value in types):
                raise PilotConfigError(
                    f'invalid document_types for {values["watch_id"]}: {values["document_types"]}'
                )
            values['document_types'] = ','.join(types)
            out.append(FederalRegisterWatch(**values))
    if not out:
        raise PilotConfigError(f'no Federal Register watch rows found in {watch_path}')
    return out


@dataclass(frozen=True)
class BlsSeries:
    series_id: str
    label: str
    topic: str
    unit: str
    frequency: str
    seasonal_adjustment: str
    enabled: bool
    notes: str


BLS_SERIES_FIELDS = [
    'series_id', 'label', 'topic', 'unit', 'frequency', 'seasonal_adjustment',
    'enabled', 'notes',
]
BLS_FREQUENCIES = {'monthly', 'quarterly', 'annual', 'weekly', 'daily'}
BLS_SEASONAL = {'seasonally adjusted', 'not seasonally adjusted', 'unknown'}


def load_bls_series(path=None):
    series_path = Path(path or _env('OR_PILOT_BLS_SERIES_PATH',
                                   'config/pilot_bls_series.csv'))
    if not series_path.exists():
        raise PilotConfigError(f'BLS series file not found: {series_path}')
    out = []
    seen = set()
    with series_path.open(encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            values = {key: str(row.get(key) or '').strip() for key in BLS_SERIES_FIELDS}
            if not values['series_id'] or not values['label'] or not values['unit']:
                raise PilotConfigError('BLS rows require series_id, label and unit')
            if values['series_id'] in seen:
                raise PilotConfigError(f'duplicate BLS series_id: {values["series_id"]}')
            seen.add(values['series_id'])
            values['enabled'] = values['enabled'].lower() in {'true', '1', 'yes'}
            values['frequency'] = values['frequency'].lower() or 'unknown'
            if values['frequency'] not in BLS_FREQUENCIES:
                raise PilotConfigError(
                    f'invalid frequency for {values["series_id"]}: {values["frequency"]}'
                )
            values['seasonal_adjustment'] = values['seasonal_adjustment'].lower() or 'unknown'
            if values['seasonal_adjustment'] not in BLS_SEASONAL:
                raise PilotConfigError(
                    f'invalid seasonal_adjustment for {values["series_id"]}'
                )
            out.append(BlsSeries(**values))
    if not out:
        raise PilotConfigError(f'no BLS rows found in {series_path}')
    return out


def config_hash(*paths):
    digest = hashlib.sha256()
    for path in paths:
        digest.update(Path(path).read_bytes() if Path(path).exists() else b'')
    return digest.hexdigest()

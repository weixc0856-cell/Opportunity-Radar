"""Configuration for the independent ingestion channel.

Deliberately separate from opportunity_radar.config.Settings: the ingest channel must not
inherit the RSS/LLM/SMTP settings, and the RSS pipeline must not inherit these.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = 'data/ingest/opportunity_radar_ingest.sqlite3'
DEFAULT_REPORT_DIR = 'reports/ingest'
PRODUCTION_DB_PATH = 'data/opportunity_radar.sqlite3'


class IngestConfigError(ValueError):
    pass


def _env(k, default=''):
    return os.getenv(k, default).strip()


@dataclass(frozen=True)
class IngestSettings:
    db_path: str
    report_dir: str
    sec_user_agent: str
    eia_api_key: str
    timeout: int
    sec_max_rps: float
    eia_base_url: str
    sec_base_url: str

    @classmethod
    def from_env(cls):
        try:
            timeout = max(1, int(_env('OR_INGEST_TIMEOUT_SECONDS', '30')))
            rps = float(_env('OR_INGEST_SEC_MAX_RPS', '5'))
        except ValueError as exc:
            raise IngestConfigError(f'invalid numeric setting: {exc}') from exc
        return cls(
            db_path=_env('OR_INGEST_DB_PATH', DEFAULT_DB_PATH),
            report_dir=_env('OR_INGEST_REPORT_DIR', DEFAULT_REPORT_DIR),
            sec_user_agent=_env('OR_INGEST_SEC_USER_AGENT'),
            eia_api_key=_env('OR_INGEST_EIA_API_KEY') or _env('EIA_API_KEY'),
            timeout=timeout,
            sec_max_rps=min(5.0, max(0.1, rps)),
            eia_base_url=_env('OR_INGEST_EIA_BASE_URL', 'https://api.eia.gov/v2').rstrip('/'),
            sec_base_url=_env('OR_INGEST_SEC_BASE_URL', 'https://data.sec.gov').rstrip('/'),
        )

    def validate_sec(self):
        if not self.sec_user_agent:
            return ['OR_INGEST_SEC_USER_AGENT is required (SEC requires a declared contact)']
        if '@' not in self.sec_user_agent:
            return ['OR_INGEST_SEC_USER_AGENT should include a contact address']
        return []

    def validate_eia(self):
        if not self.eia_api_key:
            return ['OR_INGEST_EIA_API_KEY (or EIA_API_KEY) is required']
        return []


def production_db_candidates():
    """Paths that must never be used as the ingest database."""
    out = {Path(PRODUCTION_DB_PATH).resolve()}
    env = _env('OR_DB_PATH')
    if env:
        out.add(Path(env).resolve())
    return out


def assert_isolated_db(db_path, production=None):
    """Refuse to run when the ingest DB resolves to the production RSS database."""
    target = Path(db_path).resolve()
    for p in (production or production_db_candidates()):
        if target == Path(p).resolve():
            raise IngestConfigError(
                f'refusing to use the production database as the ingest store: {target}')
    return target

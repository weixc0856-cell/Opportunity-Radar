"""Unified Event / Evidence / Claim model (R1, batch 1).

Three entities, one contract, two stores. The RSS pipeline keeps its records in the
production database; SEC and EIA keep the identical tables in their own database, because
G-D2 still forbids their data from entering the RSS business tables. Sharing the contract
rather than the file keeps the isolation that was already accepted.

Everything here is deterministic: identifiers are content hashes, so re-running a backfill
adds nothing and the same article always resolves to the same evidence and the same claim.
Nothing in this module scores, ranks or publishes; it only records what the text says and
where it says it.

What this batch deliberately does not do:
  * no model calls and no LLM extraction - a claim built from a v5 fact is a skeleton;
  * no automatic merge of merely similar events - an event is only shared when the URL or
    the normalised title matches inside a time window;
  * no verification - every claim is `unverified` until R2 judges it.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import claim_contract

RULES_VERSION = 'r1-v1'
SCHEMA_VERSION = 9
TITLE_WINDOW_HOURS = 72


EVENT_CONTEXT_AVAILABLE = 'AVAILABLE'
EVENT_CONTEXT_NOT_FOUND = 'NOT_FOUND'
EVENT_CONTEXT_UNAVAILABLE = 'UNAVAILABLE'
EVENT_CONTEXT_READ_FAILED = 'READ_FAILED'
EVENT_CONTEXT_SCHEMA_UNSUPPORTED = 'SCHEMA_UNSUPPORTED'
EVENT_CONTEXT_LABEL = {
    EVENT_CONTEXT_AVAILABLE: '事件上下文已加载',
    EVENT_CONTEXT_NOT_FOUND: '未找到关联事件',
    EVENT_CONTEXT_UNAVAILABLE: '事件上下文不可用',
    EVENT_CONTEXT_READ_FAILED: '事件上下文读取失败',
    EVENT_CONTEXT_SCHEMA_UNSUPPORTED: '事件上下文不可用（schema 不支持）',
}


class SchemaVersionError(RuntimeError):
    """The database is older than the code and must be migrated explicitly."""


def require_schema(conn, path=''):
    """Refuse a writable business operation on an unmigrated database."""
    current = conn.execute('PRAGMA user_version').fetchone()[0]
    if current < SCHEMA_VERSION:
        raise SchemaVersionError(
            f'database schema is {current}, code requires {SCHEMA_VERSION}; '
            f'run `python -m opportunity_radar.unified_main db-migrate --db {path}` '
            f'to preview and `--apply --backup <backup>` to migrate')

# Relations an article can have to the event it was filed under.
SAME_STORY = 'same_story'
FOLLOW_UP = 'follow_up'
RELATED_NOT_SAME = 'related_not_same'
UNKNOWN = 'unknown'
RELATIONS = (SAME_STORY, FOLLOW_UP, RELATED_NOT_SAME, UNKNOWN)

# Who decided the assignment. Batch 1 only uses rules; the column exists so a later batch
# can record model or human decisions without changing the table.
ASSIGN_RULE = 'rule'

CLAIM_KINDS = ('fact', 'source_interpretation', 'system_inference', 'hypothesis', 'forecast', 'opinion')
VERIFICATION_STATES = ('unverified', 'verified', 'rejected', 'unverifiable')

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  event_id TEXT PRIMARY KEY,
  event_key TEXT UNIQUE,
  event_type TEXT NOT NULL DEFAULT '',
  title_norm TEXT NOT NULL DEFAULT '',
  first_seen_at TEXT,
  last_seen_at TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  merged_into TEXT,
  rules_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_articles(
  event_id TEXT NOT NULL,
  article_key TEXT NOT NULL,
  relation TEXT NOT NULL,
  assignment TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  PRIMARY KEY(event_id, article_key)
);
CREATE TABLE IF NOT EXISTS evidences(
  evidence_id TEXT PRIMARY KEY,
  article_key TEXT NOT NULL DEFAULT '',
  source_id TEXT NOT NULL DEFAULT '',
  evidence_kind TEXT NOT NULL,
  quote TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}',
  source_family TEXT NOT NULL DEFAULT '',
  independence TEXT NOT NULL DEFAULT 'unknown',
  lineage_basis TEXT NOT NULL DEFAULT '',
  syndication_group TEXT NOT NULL DEFAULT '',
  observed_at TEXT,
  rules_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims(
  claim_id TEXT PRIMARY KEY,
  article_key TEXT NOT NULL DEFAULT '',
  event_id TEXT,
  fact_ordinal INTEGER,
  subject TEXT NOT NULL DEFAULT '',
  predicate TEXT NOT NULL DEFAULT '',
  value_num REAL,
  value_text TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  unit_raw TEXT NOT NULL DEFAULT '',
  scale TEXT NOT NULL DEFAULT '',
  currency TEXT NOT NULL DEFAULT '',
  region TEXT NOT NULL DEFAULT '',
  period TEXT NOT NULL DEFAULT '',
  period_raw TEXT NOT NULL DEFAULT '',
  comparison TEXT NOT NULL DEFAULT '',
  denominator TEXT NOT NULL DEFAULT '',
  seasonality TEXT NOT NULL DEFAULT '',
  revision TEXT NOT NULL DEFAULT '',
  revision_raw TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'fact',
  quote TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}',
  verification_state TEXT NOT NULL DEFAULT 'unverified',
  verified_at TEXT,
  verification_basis TEXT NOT NULL DEFAULT '',
  extractor TEXT NOT NULL DEFAULT 'skeleton',
  rules_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_evidence(
  claim_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  support TEXT NOT NULL DEFAULT 'direct',
  independence TEXT NOT NULL DEFAULT 'unknown',
  locator_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  PRIMARY KEY(claim_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS claim_corrections(
  correction_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT NOT NULL DEFAULT '',
  new_value TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim_verifications(
  verification_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  contract_version TEXT NOT NULL DEFAULT '',
  input_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  support TEXT NOT NULL DEFAULT 'unsupported',
  basis TEXT NOT NULL DEFAULT '',
  checks_json TEXT NOT NULL DEFAULT '[]',
  deviations_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  UNIQUE(claim_id, rules_version, input_hash)
);
CREATE TABLE IF NOT EXISTS claim_conflicts(
  conflict_id TEXT PRIMARY KEY,
  claim_a TEXT NOT NULL,
  claim_b TEXT NOT NULL,
  reason TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(claim_a, claim_b, reason)
);
CREATE TABLE IF NOT EXISTS event_corrections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  action TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  actor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunities(
  opportunity_id TEXT PRIMARY KEY,
  canonical_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  problem_statement TEXT NOT NULL DEFAULT '',
  buyer_scope TEXT NOT NULL DEFAULT '',
  opportunity_kind TEXT NOT NULL DEFAULT '',
  stage TEXT NOT NULL DEFAULT 'active' CHECK(stage IN ('active','monitoring','closed')),
  validation_state TEXT NOT NULL DEFAULT 'signal_detected'
    CHECK(validation_state IN ('signal_detected','insufficient_evidence','problem_supported',
                               'buyer_identified','payment_verified','opportunity_candidate',
                               'contradicted')),
  confidence REAL NOT NULL DEFAULT 0 CHECK(confidence>=0 AND confidence<=1),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  current_revision_id TEXT NOT NULL DEFAULT '',
  rules_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunity_links(
  link_id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL,
  target_kind TEXT NOT NULL CHECK(target_kind IN ('article','event','evidence','claim','entity')),
  target_key TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('seed_signal','fact_basis','unverified_claim','inference',
                                    'counter_evidence','payment_evidence','buyer','subject',
                                    'competitor','affected','context')),
  support TEXT NOT NULL DEFAULT 'context' CHECK(support IN ('direct','indirect','contradicts','context')),
  locator_json TEXT NOT NULL DEFAULT '{}',
  method TEXT NOT NULL DEFAULT 'manual',
  confidence REAL NOT NULL DEFAULT 0 CHECK(confidence>=0 AND confidence<=1),
  observed_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(opportunity_id,target_kind,target_key,role)
);
CREATE TABLE IF NOT EXISTS opportunity_hypotheses(
  hypothesis_id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL,
  hypothesis_kind TEXT NOT NULL,
  statement TEXT NOT NULL,
  basis_hash TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0 CHECK(confidence>=0 AND confidence<=1),
  status TEXT NOT NULL DEFAULT 'proposed'
    CHECK(status IN ('proposed','supported','contradicted','retired')),
  supersedes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(opportunity_id,hypothesis_kind,statement,basis_hash,supersedes)
);
CREATE TABLE IF NOT EXISTS opportunity_revisions(
  revision_id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL,
  stage TEXT NOT NULL CHECK(stage IN ('active','monitoring','closed')),
  validation_state TEXT NOT NULL CHECK(validation_state IN ('signal_detected','insufficient_evidence',
    'problem_supported','buyer_identified','payment_verified','opportunity_candidate','contradicted')),
  hypothesis_id TEXT NOT NULL DEFAULT '',
  basis_hash TEXT NOT NULL,
  link_ids_json TEXT NOT NULL DEFAULT '[]',
  rules_version TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(opportunity_id,stage,validation_state,hypothesis_id,basis_hash,rules_version)
);
CREATE INDEX IF NOT EXISTS idx_opportunity_links_opportunity ON opportunity_links(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_links_target ON opportunity_links(target_kind,target_key);
CREATE INDEX IF NOT EXISTS idx_opportunity_hypotheses_opportunity ON opportunity_hypotheses(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_revisions_opportunity ON opportunity_revisions(opportunity_id,created_at);
CREATE TRIGGER IF NOT EXISTS opportunity_links_no_update
BEFORE UPDATE ON opportunity_links
BEGIN SELECT RAISE(ABORT, 'opportunity_links are append-only'); END;
CREATE TRIGGER IF NOT EXISTS opportunity_links_no_delete
BEFORE DELETE ON opportunity_links
BEGIN SELECT RAISE(ABORT, 'opportunity_links are append-only'); END;
CREATE TRIGGER IF NOT EXISTS opportunity_hypotheses_no_update
BEFORE UPDATE ON opportunity_hypotheses
BEGIN SELECT RAISE(ABORT, 'opportunity_hypotheses are append-only'); END;
CREATE TRIGGER IF NOT EXISTS opportunity_hypotheses_no_delete
BEFORE DELETE ON opportunity_hypotheses
BEGIN SELECT RAISE(ABORT, 'opportunity_hypotheses are append-only'); END;
CREATE TRIGGER IF NOT EXISTS opportunity_revisions_no_update
BEFORE UPDATE ON opportunity_revisions
BEGIN SELECT RAISE(ABORT, 'opportunity_revisions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS opportunity_revisions_no_delete
BEFORE DELETE ON opportunity_revisions
BEGIN SELECT RAISE(ABORT, 'opportunity_revisions are append-only'); END;
CREATE INDEX IF NOT EXISTS idx_claims_article ON claims(article_key);
CREATE INDEX IF NOT EXISTS idx_claim_corrections_claim ON claim_corrections(claim_id);
CREATE INDEX IF NOT EXISTS idx_claims_event ON claims(event_id);
CREATE INDEX IF NOT EXISTS idx_evidences_article ON evidences(article_key);
CREATE INDEX IF NOT EXISTS idx_event_articles_article ON event_articles(article_key);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix, *parts):
    raw = '\x1f'.join('' if p is None else str(p) for p in parts)
    return prefix + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def _plain(value):
    text = unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))
    return re.sub(r'\s+', ' ', text).strip()


def stable_id(prefix, *parts):
    """Public alias: other modules build ids the same way so they cannot drift."""
    return _stable_id(prefix, *parts)


def canonical_url(url):
    """Scheme/host case, `www.`, tracking parameters, fragment and trailing slash are noise.

    Two records of the same page differ in these details far more often than in their path,
    so comparing the canonical form is what makes "same story" a rule and not a guess.
    """
    raw = str(url or '').strip()
    if not raw:
        return ''
    parts = urlsplit(raw)
    host = (parts.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    path = re.sub(r'/+$', '', parts.path or '')
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith(('utm_', 'ref', 'fbclid', 'gclid'))]
    return urlunsplit(('https' if parts.scheme in ('http', 'https') else parts.scheme,
                       host, path, urlencode(query), ''))


# Suffixes a publisher appends to the same underlying release. Only an exact trailing match is
# stripped, so a title that merely mentions "time series" keeps its meaning.
TITLE_SUFFIXES = ('time series', 'release', 'press release', 'statistical bulletin',
                  'data', 'statistics', 'news release', 'bulletin')


def canonical_title(title):
    """Punctuation- and case-insensitive title with publisher suffixes removed."""
    text = _plain(title).lower()
    text = re.sub(r'\s+[|\-–—]\s+.*$', '', text) if '|' in text else text
    text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
    text = re.sub(r'\s+', ' ', text).strip()
    changed = True
    while changed:
        changed = False
        for suffix in TITLE_SUFFIXES:
            if text.endswith(' ' + suffix):
                text = text[:-(len(suffix) + 1)].strip()
                changed = True
    return text


def _parse_time(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def hours_apart(left, right):
    a, b = _parse_time(left), _parse_time(right)
    if a is None or b is None:
        return None
    return abs((a - b).total_seconds()) / 3600.0


# --------------------------------------------------------------------------- identifiers
def event_id_for(event_key):
    return _stable_id('evt-', canonical_url(event_key) or event_key)


def evidence_id_for(article_key, quote, locator):
    loc = locator or {}
    return _stable_id('ev-', article_key, re.sub(r'\s+', ' ', str(quote or '').strip()),
                      loc.get('field', ''), loc.get('start', ''), loc.get('accn', ''),
                      loc.get('period', ''))


def claim_id_for(article_key, ordinal=None, key_parts=None):
    if key_parts is not None:
        return _stable_id('cl-', *key_parts)
    return _stable_id('cl-', article_key, ordinal)


def _locator_dict(raw):
    """(locator, error). A locator is the evidence's pointer back to its source text."""
    if isinstance(raw, dict):
        return raw, ''
    try:
        value = json.loads(raw or '{}')
    except (TypeError, ValueError):
        return {}, 'locator_invalid_json'
    if not isinstance(value, dict):
        return {}, 'locator_invalid_json'
    return value, ''


def evidence_integrity_problems(evidence):
    """What makes an evidence row unable to support a claim.

    Source identity and a locator are mandatory. An article key is enough for RSS;
    a filing/series reference is enough for the isolated SEC/EIA stores.
    """
    problems = []
    if not str(evidence.get('evidence_id') or '').strip():
        problems.append('evidence_id_missing')
    if not str(evidence.get('source_id') or '').strip():
        problems.append('source_id_missing')
    if not str(evidence.get('evidence_kind') or '').strip():
        problems.append('evidence_kind_missing')
    if not str(evidence.get('quote') or '').strip():
        problems.append('quote_missing')
    locator, locator_error = _locator_dict(evidence.get('locator_json'))
    if locator_error:
        problems.append(locator_error)
    elif not locator:
        problems.append('locator_missing')
    elif not (str(evidence.get('article_key') or '').strip()
              or locator.get('accn') or locator.get('series_id')):
        problems.append('article_or_source_record_missing')
    return problems


def claim_integrity_problems(claim):
    """A newly produced claim must start unverified and carry an id."""
    problems = []
    if not str(claim.get('claim_id') or '').strip():
        problems.append('claim_id_missing')
    state = str(claim.get('verification_state') or 'unverified').strip()
    if state not in ('', 'unverified'):
        problems.append('claim_not_unverified')
    return problems


def repair_skeleton_periods(store, apply=False, actor='p0-batch2'):
    """Remove a publication date that an older v5 skeleton claim wrote into `period`.

    Only a skeleton claim whose non-empty period exactly equals its article's publication
    date, and whose `period_raw` is empty, is safe to correct. Everything else is reported
    as pending and left untouched. The claim id and verification_state are never changed.
    """
    if not getattr(store, 'has_articles', False):
        return {'applied': False, 'error': 'articles table absent', 'skeleton_claims': 0,
                'already_empty': 0, 'eligible': 0, 'corrected': 0, 'pending': 0,
                'pending_reasons': {}, 'pending_examples': []}
    result = {'applied': bool(apply), 'skeleton_claims': 0, 'already_empty': 0,
              'eligible': 0, 'corrected': 0, 'pending': 0,
              'pending_reasons': {}, 'pending_examples': []}
    pending = []

    def add_pending(claim_id, reason, period, published):
        result['pending'] += 1
        result['pending_reasons'][reason] = result['pending_reasons'].get(reason, 0) + 1
        if len(pending) < 20:
            pending.append({'claim_id': claim_id, 'reason': reason, 'period': period,
                            'published': published})

    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            '''SELECT c.claim_id, c.period, c.period_raw, c.verification_state, a.published
               FROM claims c LEFT JOIN articles a USING(article_key)
               WHERE c.extractor='skeleton' ORDER BY c.claim_id''')]
        result['skeleton_claims'] = len(rows)
        eligible = []
        for row in rows:
            period = str(row.get('period') or '')
            published = str(row.get('published') or '')[:10]
            if not period:
                result['already_empty'] += 1
                continue
            if str(row.get('verification_state') or '') != 'unverified':
                add_pending(row['claim_id'], 'claim_not_unverified', period, published)
                continue
            if not published:
                add_pending(row['claim_id'], 'article_publication_missing', period, published)
                continue
            if period != published:
                add_pending(row['claim_id'], 'period_not_publication_date', period, published)
                continue
            if str(row.get('period_raw') or '').strip():
                add_pending(row['claim_id'], 'period_raw_present', period, published)
                continue
            eligible.append(row)
        result['eligible'] = len(eligible)
        if apply:
            for row in eligible:
                cur = conn.execute(
                    "UPDATE claims SET period='' WHERE claim_id=? AND period=? AND extractor='skeleton' "
                    "AND verification_state='unverified'", (row['claim_id'], row['period']))
                if not cur.rowcount:
                    add_pending(row['claim_id'], 'concurrent_change', row['period'],
                                str(row.get('published') or '')[:10])
                    continue
                correction_id = _stable_id('cc-', row['claim_id'], 'period', row['period'], '',
                                           'publication_date_not_fact_period')
                conn.execute(
                    'INSERT OR IGNORE INTO claim_corrections(correction_id,claim_id,field,old_value,'
                    'new_value,reason,actor,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (correction_id, row['claim_id'], 'period', row['period'], '',
                     'publication_date_not_fact_period', actor, now()))
                result['corrected'] += 1
    result['pending_examples'] = pending
    return result


# --------------------------------------------------------------------------- records
@dataclass(frozen=True)
class ArticleRef:
    article_key: str
    url: str = ''
    title: str = ''
    published: str = ''
    source_id: str = ''
    summary_hash: str = ''


def evidence_from_fact(article_key, section, source_id='', observed_at='', source_family=''):
    """One located v5 fact becomes one evidence row: quote, locator, source, time."""
    meta = section.get('meta') or section
    quote = str(meta.get('quote') or '')
    locator = meta.get('locator') or {}
    if not quote or not locator:
        raise ValueError('evidence requires a quote and a locator')
    return {
        'evidence_id': evidence_id_for(article_key, quote, locator),
        'article_key': article_key,
        'source_id': source_id or '',
        'evidence_kind': 'quote',
        'quote': quote,
        'locator_json': json.dumps(locator, ensure_ascii=False, sort_keys=True),
        'source_family': source_family or source_id or '',
        'independence': 'unknown',
        'observed_at': observed_at or str(meta.get('published') or '') or None,
        'rules_version': RULES_VERSION,
        'created_at': now(),
    }


def claim_from_fact(article_key, section, event_id=None):
    """A v5 fact is prose plus an actor. The claim records exactly that, and no more.

    `extractor='skeleton'` says the numeric fields are empty because the model was never
    asked for them; R2 upgrades the prompt and fills them. Calling this a verified claim
    would be the fabrication the project forbids.

    The article publication date is not a fact period. A v5 fact has no period field, so
    `period` stays empty unless a caller supplies an explicit, contract-valid period.
    """
    meta = section.get('meta') or section
    ordinal = section.get('ordinal')
    explicit_period = str(section.get('period') or meta.get('period') or '').strip()
    period = explicit_period if claim_contract.valid_period(explicit_period) else ''
    return {
        'claim_id': claim_id_for(article_key, ordinal),
        'article_key': article_key,
        'event_id': event_id,
        'fact_ordinal': ordinal,
        'subject': str(meta.get('actor') or ''),
        'predicate': 'assertion',
        'value_num': None,
        'value_text': str(section.get('text') or '')[:500],
        'unit': '',
        'currency': '',
        'region': '',
        'period': period,
        'period_raw': explicit_period,
        'comparison': '',
        'denominator': '',
        'seasonality': '',
        'revision': '',
        'kind': 'fact',
        'quote': str(meta.get('quote') or ''),
        'locator_json': json.dumps(meta.get('locator') or {}, ensure_ascii=False, sort_keys=True),
        'verification_state': 'unverified',
        'extractor': 'skeleton',
        'rules_version': RULES_VERSION,
        'created_at': now(),
    }


def sec_evidence(fact):
    locator = {'accn': fact.get('accn', ''), 'cik': fact.get('cik', ''),
               'taxonomy': fact.get('taxonomy', ''), 'tag': fact.get('tag', ''),
               'form': fact.get('form', ''), 'filed': fact.get('filed', ''),
               'period_start': fact.get('period_start'), 'period_end': fact.get('period_end')}
    quote = (f"{fact.get('entity_name') or fact.get('cik')} {fact.get('tag')} "
             f"{fact.get('value_raw')} {fact.get('unit')} for {fact.get('period_end')}")
    return {
        'evidence_id': evidence_id_for('', quote, locator),
        'article_key': '',
        'source_id': 'sec-edgar',
        'evidence_kind': 'sec_fact',
        'quote': quote,
        'locator_json': json.dumps(locator, ensure_ascii=False, sort_keys=True),
        'source_family': 'sec-edgar',
        'independence': 'independent_primary',
        'observed_at': fact.get('filed') or fact.get('last_seen_at'),
        'rules_version': RULES_VERSION,
        'created_at': now(),
    }


def sec_claim(fact):
    period = fact.get('period_end') or ''
    if fact.get('period_start'):
        period = f"{fact.get('period_start')}/{fact.get('period_end')}"
    return {
        'claim_id': claim_id_for('', key_parts=('sec', fact.get('cik'), fact.get('tag'),
                                               fact.get('unit'), fact.get('period_start'),
                                               fact.get('period_end'), fact.get('accn'))),
        'article_key': '',
        'event_id': None,
        'fact_ordinal': None,
        'subject': fact.get('entity_name') or fact.get('cik') or '',
        'predicate': fact.get('metric_id') or fact.get('tag') or '',
        'value_num': fact.get('value_num'),
        'value_text': fact.get('value_raw') or '',
        'unit': fact.get('unit') or '',
        'currency': 'USD' if (fact.get('unit') or '') == 'USD' else '',
        'region': 'US',
        'period': period,
        'comparison': '',
        'denominator': '',
        'seasonality': '',
        'revision': fact.get('filing_relation') or '',
        'kind': 'fact',
        'quote': '',
        'locator_json': sec_evidence(fact)['locator_json'],
        'verification_state': 'unverified',
        'extractor': 'structured',
        'rules_version': RULES_VERSION,
        'created_at': now(),
    }


def eia_evidence(observation, series=None):
    locator = {'series_id': observation.get('series_id', ''), 'period': observation.get('period', ''),
               'period_kind': observation.get('period_kind', ''),
               'snapshot_hash': observation.get('snapshot_hash', '')}
    if series:
        locator.update({'dataset': series.get('dataset', ''), 'route': series.get('route', ''),
                        'metric': series.get('metric', '')})
    quote = (f"{observation.get('series_id')} {observation.get('period')} "
             f"{observation.get('value_raw')} {observation.get('unit')}")
    return {
        'evidence_id': evidence_id_for('', quote, locator),
        'article_key': '',
        'source_id': 'eia',
        'evidence_kind': 'eia_observation',
        'quote': quote,
        'locator_json': json.dumps(locator, ensure_ascii=False, sort_keys=True),
        'source_family': 'eia',
        'independence': 'independent_primary',
        'observed_at': observation.get('last_seen_at'),
        'rules_version': RULES_VERSION,
        'created_at': now(),
    }


def eia_claim(observation, series=None):
    return {
        'claim_id': claim_id_for('', key_parts=('eia', observation.get('series_id'),
                                               observation.get('period'))),
        'article_key': '',
        'event_id': None,
        'fact_ordinal': None,
        'subject': (series or {}).get('route', '') or observation.get('series_id', ''),
        'predicate': (series or {}).get('metric', '') or 'observation',
        'value_num': observation.get('value_num'),
        'value_text': observation.get('value_raw') or '',
        'unit': observation.get('unit') or '',
        'currency': '',
        'region': 'US',
        'period': observation.get('period', ''),
        'comparison': '',
        'denominator': '',
        'seasonality': 'not_seasonally_adjusted',
        'revision': 'observed_change' if 'observed_change' in (observation.get('quality_flags') or '') else '',
        'kind': 'fact',
        'quote': '',
        'locator_json': eia_evidence(observation, series)['locator_json'],
        'verification_state': 'unverified',
        'extractor': 'structured',
        'rules_version': RULES_VERSION,
        'created_at': now(),
    }


# --------------------------------------------------------------------------- events
def match_relation(article, event, member_urls, member_titles, first_seen, last_seen):
    """(relation, confidence, reason) for filing `article` under `event`, or (None, 0, why).

    Two rules only. Anything else is a different event; a shared keyword is not evidence
    that two articles describe the same thing.
    """
    url = canonical_url(article.url)
    if url and url in member_urls:
        return SAME_STORY, 1.0, 'canonical_url'
    title = canonical_title(article.title)
    if not title or title not in member_titles:
        return None, 0.0, 'no_rule_matched'
    gaps = [g for g in (hours_apart(article.published, first_seen),
                        hours_apart(article.published, last_seen)) if g is not None]
    if not gaps:
        return None, 0.0, 'published_unknown'
    if min(gaps) <= TITLE_WINDOW_HOURS:
        return SAME_STORY, 0.9, 'title_within_window'
    return None, 0.0, 'title_outside_window'


class UnifiedStore:
    """The unified tables, in whichever database they belong to."""

    def __init__(self, path, read_only=False, migrate=True):
        self.path = Path(path)
        self.read_only = read_only
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if migrate:
                self.init()
            else:
                if not self.path.exists():
                    raise SchemaVersionError(
                        f'database does not exist: {self.path}; run a digest or explicit migration')
                with self.connect() as conn:
                    require_schema(conn, str(self.path))
        self.has_articles = self._articles_present()

    def _articles_present(self):
        with self.connect() as conn:
            return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='articles'").fetchone() is not None

    @contextmanager
    def connect(self):
        """sqlite3's own context manager commits but never closes; Windows keeps the file
        locked until the handle is gone. Close it here, as Store.connect does."""
        if self.read_only:
            conn = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self):
        with self.connect() as conn:
            from .linking import ENTITY_SCHEMA   # local import: linking imports this module
            conn.executescript(SCHEMA)
            conn.executescript(ENTITY_SCHEMA)
            mention_columns = {row[1] for row in conn.execute('PRAGMA table_info(entity_mentions)')}
            for name, ddl in (('article_key', "TEXT NOT NULL DEFAULT ''"),
                              ('evidence_id', "TEXT NOT NULL DEFAULT ''"),
                              ('claim_id', "TEXT NOT NULL DEFAULT ''"),
                              ('locator_json', "TEXT NOT NULL DEFAULT '{}'"),
                              ('occurrence_count', 'INTEGER NOT NULL DEFAULT 1')):
                if name not in mention_columns:
                    conn.execute(f'ALTER TABLE entity_mentions ADD COLUMN {name} {ddl}')
            conn.execute("UPDATE entity_mentions SET article_key=target_key "
                         "WHERE article_key='' AND target_kind='article'")
            conn.execute('CREATE INDEX IF NOT EXISTS idx_mentions_article ON entity_mentions(article_key)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_mentions_evidence ON entity_mentions(evidence_id)')
            # Tables created before batch 3 exist already, so the new evidence columns are
            # added in place rather than by recreating anything.
            have = {row[1] for row in conn.execute('PRAGMA table_info(evidences)')}
            for name in ('lineage_basis', 'syndication_group'):
                if name not in have:
                    conn.execute(f"ALTER TABLE evidences ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            claim_columns = {row[1] for row in conn.execute('PRAGMA table_info(claims)')}
            for name, ddl in (('verified_at', 'TEXT'), ('verification_basis', "TEXT NOT NULL DEFAULT ''"),
                              ('unit_raw', "TEXT NOT NULL DEFAULT ''"),
                              ('scale', "TEXT NOT NULL DEFAULT ''"),
                              ('period_raw', "TEXT NOT NULL DEFAULT ''"),
                              ('revision_raw', "TEXT NOT NULL DEFAULT ''")):
                if name not in claim_columns:
                    conn.execute(f'ALTER TABLE claims ADD COLUMN {name} {ddl}')
            verification_columns = {row[1] for row in conn.execute('PRAGMA table_info(claim_verifications)')}
            if 'contract_version' not in verification_columns:
                conn.execute("ALTER TABLE claim_verifications ADD COLUMN contract_version TEXT NOT NULL DEFAULT ''")
            current = conn.execute('PRAGMA user_version').fetchone()[0]
            if current < SCHEMA_VERSION:
                conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')

    # ------------------------------------------------------------------ events
    def assign_article(self, article):
        """File one article under an event. Idempotent: an existing assignment is left alone."""
        with self.connect() as conn:
            existing = conn.execute('SELECT event_id, relation FROM event_articles WHERE article_key=?',
                                    (article.article_key,)).fetchone()
            if existing:
                return {'event_id': existing['event_id'], 'relation': existing['relation'],
                        'assignment': ASSIGN_RULE, 'created': False}

            best = None
            event_rows = conn.execute("SELECT * FROM events WHERE status='open'") if self.has_articles else []
            for row in event_rows:
                members = [dict(m) for m in conn.execute(
                    'SELECT a.url, a.title FROM event_articles e JOIN articles a USING(article_key) WHERE e.event_id=?',
                    (row['event_id'],))]
                urls = {canonical_url(m['url']) for m in members}
                titles = {canonical_title(m['title']) for m in members}
                relation, confidence, reason = match_relation(
                    article, row, urls, titles, row['first_seen_at'], row['last_seen_at'])
                if relation and (best is None or confidence > best[1]):
                    best = (row['event_id'], confidence, relation, reason)
            if best:
                event_id, confidence, relation, reason = best
                conn.execute('INSERT OR IGNORE INTO event_articles(event_id,article_key,relation,assignment,confidence,reason,created_at) '
                             'VALUES(?,?,?,?,?,?,?)',
                             (event_id, article.article_key, relation, ASSIGN_RULE, confidence, reason, now()))
                conn.execute('UPDATE events SET last_seen_at=?, first_seen_at=COALESCE(first_seen_at,?) WHERE event_id=?',
                             (article.published or None, article.published or None, event_id))
                return {'event_id': event_id, 'relation': relation, 'assignment': ASSIGN_RULE,
                        'confidence': confidence, 'reason': reason, 'created': False}

            key = canonical_url(article.url) or ('title:' + canonical_title(article.title))
            event_id = event_id_for(key)
            conn.execute('INSERT OR IGNORE INTO events(event_id,event_key,event_type,title_norm,first_seen_at,last_seen_at,'
                         'status,rules_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                         (event_id, key, '', canonical_title(article.title), article.published or None,
                          article.published or None, 'open', RULES_VERSION, now()))
            conn.execute('INSERT OR IGNORE INTO event_articles(event_id,article_key,relation,assignment,confidence,reason,created_at) '
                         'VALUES(?,?,?,?,?,?,?)',
                         (event_id, article.article_key, SAME_STORY, ASSIGN_RULE, 1.0, 'new_event', now()))
            return {'event_id': event_id, 'relation': SAME_STORY, 'assignment': ASSIGN_RULE,
                    'confidence': 1.0, 'reason': 'new_event', 'created': True}

    # ------------------------------------------------------------------ records
    def add_evidence(self, evidence):
        problems = evidence_integrity_problems(evidence)
        if problems:
            raise ValueError('invalid evidence: ' + ', '.join(problems))
        with self.connect() as conn:
            cur = conn.execute('INSERT OR IGNORE INTO evidences(evidence_id,article_key,source_id,evidence_kind,quote,'
                               'locator_json,source_family,independence,observed_at,rules_version,created_at) '
                               'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                               tuple(evidence[k] for k in ('evidence_id', 'article_key', 'source_id',
                                                           'evidence_kind', 'quote', 'locator_json',
                                                           'source_family', 'independence', 'observed_at',
                                                           'rules_version', 'created_at')))
            return cur.rowcount > 0

    def add_claim(self, claim):
        """Insert one claim. The *_raw columns keep the model's own wording beside the
        normalised value, so a deviation can be traced back to what it actually said."""
        problems = claim_integrity_problems(claim)
        if problems:
            raise ValueError('invalid claim: ' + ', '.join(problems))
        columns = ('claim_id', 'article_key', 'event_id', 'fact_ordinal', 'subject', 'predicate',
                   'value_num', 'value_text', 'unit', 'unit_raw', 'scale', 'currency', 'region', 'period',
                   'period_raw', 'comparison', 'denominator', 'seasonality', 'revision', 'revision_raw',
                   'kind', 'quote', 'locator_json', 'verification_state', 'extractor', 'rules_version',
                   'created_at')
        values = tuple(claim.get(name, '') for name in columns)
        with self.connect() as conn:
            cur = conn.execute(
                'INSERT OR IGNORE INTO claims(%s) VALUES(%s)'
                % (','.join(columns), ','.join('?' * len(columns))), values)
            return cur.rowcount > 0

    def link(self, claim_id, evidence_id, support='direct', independence='unknown', locator_json='{}'):
        with self.connect() as conn:
            if not conn.execute('SELECT 1 FROM claims WHERE claim_id=?', (claim_id,)).fetchone():
                raise ValueError('claim not found: ' + str(claim_id))
            evidence = conn.execute('SELECT * FROM evidences WHERE evidence_id=?',
                                    (evidence_id,)).fetchone()
            if not evidence:
                raise ValueError('evidence not found: ' + str(evidence_id))
            problems = evidence_integrity_problems(dict(evidence))
            if problems:
                raise ValueError('invalid evidence: ' + ', '.join(problems))
            cur = conn.execute('INSERT OR IGNORE INTO claim_evidence(claim_id,evidence_id,support,independence,locator_json,created_at) '
                               'VALUES(?,?,?,?,?,?)',
                               (claim_id, evidence_id, support, independence, locator_json, now()))
            return cur.rowcount > 0

    def bulk_add(self, evidences=(), claims=(), links=()):
        """Write many records in one transaction. A backfill of 2,700 facts must not open
        8,000 connections."""
        evidences, claims, links = list(evidences), list(claims), list(links)
        inserted = {'evidences': 0, 'claims': 0, 'links': 0,
                    'evidences_rejected': 0, 'claims_rejected': 0, 'links_rejected': 0,
                    'rejected_count': 0, 'rejected': []}
        rejected = []

        def reject(kind, key, reasons, article_key=''):
            inserted['rejected_count'] += 1
            if len(rejected) < 20:
                rejected.append({'kind': kind, 'id': str(key or ''),
                                 'article_key': str(article_key or ''),
                                 'reasons': list(reasons)})

        valid_evidence = {}
        for ev in evidences:
            problems = evidence_integrity_problems(ev)
            if problems:
                inserted['evidences_rejected'] += 1
                reject('evidence', ev.get('evidence_id'), problems, ev.get('article_key'))
            else:
                valid_evidence[ev['evidence_id']] = ev

        # An RSS evidence must point at a stored article. SEC/EIA evidence points at its
        # filing/series locator instead, and those stores have no articles table.
        if self.has_articles:
            keys = sorted({str(ev.get('article_key') or '') for ev in valid_evidence.values()
                           if str(ev.get('article_key') or '').strip()})
            found = set()
            if keys:
                with self.connect() as conn:
                    for index in range(0, len(keys), 400):
                        chunk = keys[index:index + 400]
                        found.update(row[0] for row in conn.execute(
                            'SELECT article_key FROM articles WHERE article_key IN (%s)'
                            % ','.join('?' * len(chunk)), chunk))
            for evidence_id, ev in list(valid_evidence.items()):
                key = str(ev.get('article_key') or '').strip()
                if key and key not in found:
                    inserted['evidences_rejected'] += 1
                    reject('evidence', evidence_id, ['article_not_found'], key)
                    del valid_evidence[evidence_id]

        with self.connect() as conn:
            for ev in valid_evidence.values():
                cur = conn.execute('INSERT OR IGNORE INTO evidences(evidence_id,article_key,source_id,evidence_kind,quote,'
                                   'locator_json,source_family,independence,observed_at,rules_version,created_at) '
                                   'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                   tuple(ev[k] for k in ('evidence_id', 'article_key', 'source_id', 'evidence_kind',
                                                         'quote', 'locator_json', 'source_family', 'independence',
                                                         'observed_at', 'rules_version', 'created_at')))
                inserted['evidences'] += cur.rowcount
            claim_map = {str(c.get('claim_id') or ''): c for c in claims}
            links_by_claim = {}
            for link in links:
                claim_id, evidence_id = str(link[0]), str(link[1])
                ev = valid_evidence.get(evidence_id)
                if ev is None:
                    row = conn.execute('SELECT * FROM evidences WHERE evidence_id=?',
                                       (evidence_id,)).fetchone()
                    if row:
                        ev = dict(row)
                if ev is None:
                    inserted['links_rejected'] += 1
                    reject('link', f'{claim_id}->{evidence_id}', ['evidence_not_found'])
                    continue
                problems = evidence_integrity_problems(ev)
                if problems:
                    inserted['links_rejected'] += 1
                    reject('link', f'{claim_id}->{evidence_id}', problems, ev.get('article_key'))
                    continue
                claim = claim_map.get(claim_id)
                if claim is None and not conn.execute(
                        'SELECT 1 FROM claims WHERE claim_id=?', (claim_id,)).fetchone():
                    inserted['links_rejected'] += 1
                    reject('link', f'{claim_id}->{evidence_id}', ['claim_not_found'])
                    continue
                if claim is not None:
                    claim_article = str(claim.get('article_key') or '').strip()
                    evidence_article = str(ev.get('article_key') or '').strip()
                    if claim_article and evidence_article and claim_article != evidence_article:
                        inserted['links_rejected'] += 1
                        reject('link', f'{claim_id}->{evidence_id}',
                               ['claim_evidence_article_mismatch'], evidence_article)
                        continue
                links_by_claim.setdefault(claim_id, []).append(link)

            for cl in claims:
                claim_id = str(cl.get('claim_id') or '')
                problems = claim_integrity_problems(cl)
                if not links_by_claim.get(claim_id):
                    problems.append('claim_evidence_missing')
                if problems:
                    inserted['claims_rejected'] += 1
                    reject('claim', claim_id, problems, cl.get('article_key'))
                    continue
                cur = conn.execute('INSERT OR IGNORE INTO claims(claim_id,article_key,event_id,fact_ordinal,subject,predicate,'
                                   'value_num,value_text,unit,currency,region,period,comparison,denominator,seasonality,'
                                   'revision,kind,quote,locator_json,verification_state,extractor,rules_version,created_at) '
                                   'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                   tuple(cl[k] for k in ('claim_id', 'article_key', 'event_id', 'fact_ordinal',
                                                         'subject', 'predicate', 'value_num', 'value_text', 'unit',
                                                         'currency', 'region', 'period', 'comparison', 'denominator',
                                                         'seasonality', 'revision', 'kind', 'quote', 'locator_json',
                                                         'verification_state', 'extractor', 'rules_version',
                                                         'created_at')))
                inserted['claims'] += cur.rowcount
                for link in links_by_claim[claim_id]:
                    cur = conn.execute('INSERT OR IGNORE INTO claim_evidence(claim_id,evidence_id,support,independence,locator_json,created_at) '
                                       'VALUES(?,?,?,?,?,?)', tuple(link))
                    inserted['links'] += cur.rowcount
        inserted['rejected'] = rejected
        return inserted

    def record_correction(self, event_id, action, payload=None, actor=''):
        with self.connect() as conn:
            conn.execute('INSERT INTO event_corrections(event_id,action,payload_json,actor,created_at) VALUES(?,?,?,?,?)',
                         (event_id, action, json.dumps(payload or {}, ensure_ascii=False), actor, now()))

    # ------------------------------------------------------------------ queries
    def counts(self):
        with self.connect() as conn:
            return {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                    for t in ('events', 'event_articles', 'evidences', 'claims', 'claim_evidence')}

    def event_members(self, event_id):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                'SELECT e.article_key, e.relation, e.assignment, e.confidence, e.reason '
                'FROM event_articles e WHERE e.event_id=? ORDER BY e.created_at, e.article_key', (event_id,))]

    def unlinked_claims(self, limit=20):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                'SELECT c.claim_id, c.article_key, c.predicate FROM claims c '
                'LEFT JOIN claim_evidence ce USING(claim_id) WHERE ce.claim_id IS NULL LIMIT ?', (limit,))]

    def claims_without_locator(self, limit=20):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                'SELECT claim_id, article_key FROM claims WHERE locator_json IN (\'{}\', \'\') LIMIT ?', (limit,))]

    def events_with_multiple_sources(self):
        """How much corroboration actually exists, counted by source rather than by article."""
        with self.connect() as conn:
            rows = conn.execute('''SELECT e.event_id, COUNT(DISTINCT v.source_id) sources, COUNT(DISTINCT e.article_key) articles
                                   FROM event_articles e
                                   JOIN evidences v USING(article_key)
                                   GROUP BY e.event_id HAVING sources > 1 ORDER BY sources DESC, articles DESC''').fetchall()
            return [dict(r) for r in rows]

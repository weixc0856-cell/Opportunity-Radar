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
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

RULES_VERSION = 'r1-v1'
SCHEMA_VERSION = 1
TITLE_WINDOW_HOURS = 72

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
  currency TEXT NOT NULL DEFAULT '',
  region TEXT NOT NULL DEFAULT '',
  period TEXT NOT NULL DEFAULT '',
  comparison TEXT NOT NULL DEFAULT '',
  denominator TEXT NOT NULL DEFAULT '',
  seasonality TEXT NOT NULL DEFAULT '',
  revision TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'fact',
  quote TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}',
  verification_state TEXT NOT NULL DEFAULT 'unverified',
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
CREATE TABLE IF NOT EXISTS event_corrections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL,
  action TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  actor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_article ON claims(article_key);
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
    """
    meta = section.get('meta') or section
    ordinal = section.get('ordinal')
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
        'period': str(meta.get('published') or '')[:10],
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

    def __init__(self, path, read_only=False):
        self.path = Path(path)
        self.read_only = read_only
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.init()
        self.has_articles = self._articles_present()

    def _articles_present(self):
        conn = self.connect()
        try:
            row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='articles'").fetchone()
            return row is not None
        finally:
            conn.close()

    def connect(self):
        if self.read_only:
            conn = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
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
        with self.connect() as conn:
            cur = conn.execute('INSERT OR IGNORE INTO claims(claim_id,article_key,event_id,fact_ordinal,subject,predicate,'
                               'value_num,value_text,unit,currency,region,period,comparison,denominator,seasonality,'
                               'revision,kind,quote,locator_json,verification_state,extractor,rules_version,created_at) '
                               'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               tuple(claim[k] for k in ('claim_id', 'article_key', 'event_id', 'fact_ordinal',
                                                        'subject', 'predicate', 'value_num', 'value_text', 'unit',
                                                        'currency', 'region', 'period', 'comparison', 'denominator',
                                                        'seasonality', 'revision', 'kind', 'quote', 'locator_json',
                                                        'verification_state', 'extractor', 'rules_version',
                                                        'created_at')))
            return cur.rowcount > 0

    def link(self, claim_id, evidence_id, support='direct', independence='unknown', locator_json='{}'):
        with self.connect() as conn:
            cur = conn.execute('INSERT OR IGNORE INTO claim_evidence(claim_id,evidence_id,support,independence,locator_json,created_at) '
                               'VALUES(?,?,?,?,?,?)',
                               (claim_id, evidence_id, support, independence, locator_json, now()))
            return cur.rowcount > 0

    def bulk_add(self, evidences=(), claims=(), links=()):
        """Write many records in one transaction. A backfill of 2,700 facts must not open
        8,000 connections."""
        inserted = {'evidences': 0, 'claims': 0, 'links': 0}
        with self.connect() as conn:
            for ev in evidences:
                cur = conn.execute('INSERT OR IGNORE INTO evidences(evidence_id,article_key,source_id,evidence_kind,quote,'
                                   'locator_json,source_family,independence,observed_at,rules_version,created_at) '
                                   'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                   tuple(ev[k] for k in ('evidence_id', 'article_key', 'source_id', 'evidence_kind',
                                                         'quote', 'locator_json', 'source_family', 'independence',
                                                         'observed_at', 'rules_version', 'created_at')))
                inserted['evidences'] += cur.rowcount
            for cl in claims:
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
            for link in links:
                cur = conn.execute('INSERT OR IGNORE INTO claim_evidence(claim_id,evidence_id,support,independence,locator_json,created_at) '
                                   'VALUES(?,?,?,?,?,?)', tuple(link))
                inserted['links'] += cur.rowcount
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

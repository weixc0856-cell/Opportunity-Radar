"""Entity alignment and candidate links between the RSS, SEC and EIA records (R1 batch 2).

The gap this closes: an SEC revenue fact and a news article about the same company are two
records that know nothing about each other. Naming the company once, in one place, is what
makes a cross-source relation expressible at all.

Three rules shape every function here:

1. Nothing is merged. A relation starts as `candidate`; only a recorded correction can
   accept or reject it, and the two records stay separate rows in separate tables.
2. Nothing is guessed. A mention needs the registered name or an alias derived from it to
   appear as a whole word. Tickers are stored but not matched: three-letter symbols collide
   with ordinary words (CAT, KO, ARM), and a wrong mention is worse than a missing one.
3. Evidence count, source independence and evidence quality are reported separately. When
   the source families are unknown, the profile says so instead of implying corroboration.
"""
from __future__ import annotations

import json
import re
import sqlite3
from html import unescape

from .unified import hours_apart, now, stable_id
from .lineage import CORROBORATING

ENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities(
  entity_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL DEFAULT 'company',
  canonical_name TEXT NOT NULL,
  canonical_key TEXT NOT NULL UNIQUE,
  cik TEXT NOT NULL DEFAULT '',
  ticker TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_aliases(
  entity_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  alias_key TEXT NOT NULL,
  method TEXT NOT NULL DEFAULT 'derived',
  created_at TEXT NOT NULL,
  PRIMARY KEY(entity_id, alias_key)
);
CREATE TABLE IF NOT EXISTS entity_mentions(
  mention_id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  target_kind TEXT NOT NULL,
  target_key TEXT NOT NULL,
  method TEXT NOT NULL,
  matched_text TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(entity_id, target_kind, target_key, method)
);
CREATE TABLE IF NOT EXISTS event_links(
  link_id TEXT PRIMARY KEY,
  left_kind TEXT NOT NULL,
  left_key TEXT NOT NULL,
  right_kind TEXT NOT NULL,
  right_key TEXT NOT NULL,
  relation TEXT NOT NULL,
  basis TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(left_kind, left_key, right_kind, right_key, relation, basis)
);
CREATE INDEX IF NOT EXISTS idx_mentions_target ON entity_mentions(target_kind, target_key);
CREATE INDEX IF NOT EXISTS idx_links_left ON event_links(left_kind, left_key);
CREATE INDEX IF NOT EXISTS idx_links_right ON event_links(right_kind, right_key);
"""

LINK_STATUSES = ('candidate', 'accepted', 'rejected')
REL_SAME_SUBJECT = 'same_subject'
REL_SHARED_ENTITY = 'shared_entity'
DEFAULT_LINK_WINDOW_DAYS = 120
EVENT_EVENT_WINDOW_DAYS = 7
MIN_ALIAS_CHARS = 4


def _plain(value):
    text = unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))
    return re.sub(r'\s+', ' ', text).strip()


def entity_id_for(key):
    return stable_id('ent-', str(key).strip().lower())


def alias_key(value):
    text = _plain(value).lower().replace('&', ' and ')
    return re.sub(r'[^\w\s]', ' ', text).strip()


def derive_aliases(name):
    """Aliases a headline could plausibly use, derived only from the registered name."""
    raw = _plain(name)
    out = {raw}
    stripped = re.sub(r'[,\s]+(inc|incorporated|corp|corporation|company|co|ltd|limited|plc)\b\.?$',
                      '', raw, flags=re.I).strip().rstrip(',')
    if stripped:
        out.add(stripped)
    without_the = re.sub(r'^the\s+', '', stripped or raw, flags=re.I)
    if without_the:
        out.add(without_the)
    return sorted({a for a in out if len(alias_key(a)) >= MIN_ALIAS_CHARS}, key=len)


def seed_entities(store, companies):
    """companies: iterable of {cik, name, ticker}. Idempotent; returns entities created."""
    created = 0
    with store.connect() as conn:
        for company in companies:
            name = _plain(company.get('name') or '')
            if not name:
                continue
            cik = str(company.get('cik') or '').zfill(10) if company.get('cik') else ''
            key = cik or alias_key(name)
            entity_id = entity_id_for(key)
            created += conn.execute(
                'INSERT OR IGNORE INTO entities(entity_id,entity_type,canonical_name,canonical_key,cik,ticker,created_at) '
                'VALUES(?,?,?,?,?,?,?)',
                (entity_id, 'company', name, key, cik, str(company.get('ticker') or ''), now())).rowcount
            for alias in derive_aliases(name):
                conn.execute('INSERT OR IGNORE INTO entity_aliases(entity_id,alias,alias_key,method,created_at) '
                             'VALUES(?,?,?,?,?)',
                             (entity_id, alias, alias_key(alias), 'derived', now()))
    return created


def find_mentions(text, aliases):
    """[(entity_id, alias, matched_text, confidence)] for whole-word, case-insensitive hits.

    The canonical name is trusted more than a derived alias ("Apple Inc." vs "Apple"), so
    the two carry different confidence instead of being reported as the same evidence.
    """
    blob = _plain(text)
    if not blob:
        return []
    hits, seen = [], set()
    for entity_id, alias, is_canonical in aliases:
        if alias_key(alias) in seen or len(alias_key(alias)) < MIN_ALIAS_CHARS:
            continue
        match = re.search(r'(?<![\w])' + re.escape(alias) + r'(?![\w])', blob, re.I)
        if match:
            seen.add(alias_key(alias))
            hits.append((entity_id, alias, match.group(0), 0.9 if is_canonical else 0.75))
    return hits


def index_mentions(store, article_texts, target_kind='article'):
    """article_texts: iterable of (article_key, text). The text searched is whatever the
    caller can prove it holds - never a guess about what the article probably said."""
    with store.connect() as conn:
        rows = conn.execute('SELECT entity_id, alias, canonical_name FROM entity_aliases '
                            'JOIN entities USING(entity_id)').fetchall()
        aliases = [(r['entity_id'], r['alias'], alias_key(r['alias']) == alias_key(r['canonical_name'])) for r in rows]
        if not aliases:
            return {'mentions': 0, 'articles': 0}
        found = touched = 0
        for article_key, text in article_texts:
            hits = find_mentions(text, aliases)
            if not hits:
                continue
            touched += 1
            for entity_id, alias, matched, confidence in hits:
                mention_id = stable_id('men-', entity_id, target_kind, article_key, 'name')
                found += conn.execute(
                    'INSERT OR IGNORE INTO entity_mentions(mention_id,entity_id,target_kind,target_key,method,'
                    'matched_text,confidence,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (mention_id, entity_id, target_kind, article_key, 'name', matched, confidence, now())).rowcount
        return {'mentions': found, 'articles': touched}


def _link(store, left_kind, left_key, right_kind, right_key, relation, basis, confidence, evidence=None):
    link_id = stable_id('lnk-', left_kind, left_key, right_kind, right_key, relation, basis)
    with store.connect() as conn:
        return conn.execute(
            'INSERT OR IGNORE INTO event_links(link_id,left_kind,left_key,right_kind,right_key,relation,basis,'
            'confidence,status,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (link_id, left_kind, left_key, right_kind, right_key, relation, basis, confidence, 'candidate',
             json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True), now())).rowcount > 0


def _period_end(period):
    text = str(period or '')
    if '/' in text:
        text = text.split('/')[-1]
    return text[:10]


def link_claims_to_events(store, claims, window_days=DEFAULT_LINK_WINDOW_DAYS):
    """A structured claim and an event naming the same company near the same time.

    `claims`: iterable of {claim_id, entity_id, period}. A filing and an article about one
    company are not the same event; the link records the relation, it does not create one.
    """
    created = 0
    with store.connect() as conn:
        events_by_entity = {}
        for row in conn.execute('''SELECT DISTINCT m.entity_id, e.event_id, e.first_seen_at
                                   FROM entity_mentions m
                                   JOIN event_articles ea ON ea.article_key = m.target_key
                                   JOIN events e USING(event_id)
                                   WHERE m.target_kind='article' '''):
            events_by_entity.setdefault(row['entity_id'], []).append((row['event_id'], row['first_seen_at']))
    for claim in claims:
        entity_id = claim.get('entity_id')
        if not entity_id:
            continue
        period_end = _period_end(claim.get('period'))
        for event_id, seen in events_by_entity.get(entity_id, []):
            gap_days = None
            if period_end and seen:
                stamp = period_end if len(period_end) > 10 else period_end + 'T00:00:00+00:00'
                hours = hours_apart(stamp, seen)
                gap_days = None if hours is None else hours / 24.0
            if gap_days is not None and gap_days > window_days:
                continue
            created += _link(store, 'claim', claim['claim_id'], 'event', event_id, REL_SAME_SUBJECT,
                             'entity_period_window', 0.6,
                             {'entity_id': entity_id, 'period': claim.get('period'),
                              'event_seen': seen, 'gap_days': gap_days})
    return created


def link_events_by_entity(store, window_days=EVENT_EVENT_WINDOW_DAYS):
    """Two events naming the same company within a few days: a candidate, never a merge."""
    created = 0
    with store.connect() as conn:
        rows = list(conn.execute('''SELECT DISTINCT m.entity_id, e.event_id, e.first_seen_at
                                    FROM entity_mentions m
                                    JOIN event_articles ea ON ea.article_key = m.target_key
                                    JOIN events e USING(event_id)
                                    WHERE m.target_kind='article' '''))
    by_entity = {}
    for row in rows:
        by_entity.setdefault(row['entity_id'], []).append((row['event_id'], row['first_seen_at']))
    for entity_id, events in by_entity.items():
        unique = sorted({e for e, _ in events})
        for i, left in enumerate(unique):
            for right in unique[i + 1:]:
                stamps = sorted(s for e, s in events if e in (left, right) and s)
                gap = hours_apart(stamps[0], stamps[-1]) if len(stamps) >= 2 else None
                if gap is not None and gap > window_days * 24:
                    continue
                created += _link(store, 'event', left, 'event', right, REL_SHARED_ENTITY,
                                 'shared_entity', 0.5, {'entity_id': entity_id, 'gap_hours': gap})
    return created


def event_profile(store, event_id):
    """What stands behind one event, counted four ways and never conflated.

    Articles, sources, source families and corroborating units are different numbers. A
    family counts as a corroborating unit only when its evidence carries a recorded
    independence; evidences that merely share a wire copy collapse into one unit.
    """
    with store.connect() as conn:
        articles = conn.execute('SELECT COUNT(*) FROM event_articles WHERE event_id=?', (event_id,)).fetchone()[0]
        has_lineage = True
        try:
            conn.execute('SELECT syndication_group FROM evidences LIMIT 1')
        except sqlite3.OperationalError:
            has_lineage = False
        group_expr = "COALESCE(v.syndication_group,'')" if has_lineage else "''"
        rows = [dict(r) for r in conn.execute(
            f'''SELECT v.evidence_id, v.source_id, v.source_family, v.independence, v.evidence_kind,
                      {group_expr} AS syndication_group
               FROM event_articles ea JOIN evidences v USING(article_key) WHERE ea.event_id=?''', (event_id,))]
        claims = conn.execute('''SELECT COUNT(*) FROM claims c JOIN event_articles ea ON ea.article_key = c.article_key
                                 WHERE ea.event_id=?''', (event_id,)).fetchone()[0]
        member_sources = sorted({r[0] for r in conn.execute(
            'SELECT a.source_name FROM event_articles e JOIN articles a USING(article_key) '
            'WHERE e.event_id=? AND a.source_name IS NOT NULL AND length(a.source_name)>0', (event_id,))})
        links = conn.execute('''SELECT COUNT(*) FROM event_links
                                WHERE (left_kind='event' AND left_key=?) OR (right_kind='event' AND right_key=?)''',
                             (event_id, event_id)).fetchone()[0]
    sources = sorted({r['source_id'] for r in rows if r['source_id']})
    families = sorted({r['source_family'] for r in rows if r['source_family']})
    independence, kinds, groups = {}, {}, set()
    units = set()
    for row in rows:
        status = row['independence'] or 'unknown'
        independence[status] = independence.get(status, 0) + 1
        kinds[row['evidence_kind']] = kinds.get(row['evidence_kind'], 0) + 1
        group = (row.get('syndication_group') or '').strip()
        if group:
            groups.add(group)
        if status in CORROBORATING and row['source_family']:
            units.add(group or row['source_family'])
    independent = len(units) >= 2
    if independent:
        note = f'至少两个独立单元覆盖（{len(units)} 个），可视为多来源佐证'
    elif not families:
        note = '本条事件没有可追溯的来源族'
    else:
        note = '来源独立性未知或不足：证据数量不等于独立佐证，也不等于证据质量'
    return {
        'event_id': event_id,
        'articles': articles,
        'sources': sources,
        'member_sources': member_sources,
        'evidences': len(rows),
        'claims': claims,
        'source_families': families,
        'independence': independence,
        'evidence_kinds': kinds,
        'syndication_groups': sorted(groups),
        'corroborating_units': len(units),
        'candidate_links': links,
        'independent_corroboration': independent,
        'quality_note': note,
    }


def record_decision(store, link_id, status, actor='', note=''):
    """Accept or reject a candidate. Appends a correction; the link row keeps its status."""
    if status not in LINK_STATUSES:
        raise ValueError(f'unknown link status: {status!r}')
    with store.connect() as conn:
        link = conn.execute('SELECT * FROM event_links WHERE link_id=?', (link_id,)).fetchone()
        if link is None:
            raise ValueError(f'no such link: {link_id}')
        conn.execute('UPDATE event_links SET status=? WHERE link_id=?', (status, link_id))
        conn.execute('INSERT INTO event_corrections(event_id,action,payload_json,actor,created_at) VALUES(?,?,?,?,?)',
                     (link['left_key'], 'link_' + status,
                      json.dumps({'link_id': link_id, 'note': note}, ensure_ascii=False), actor, now()))
    return status

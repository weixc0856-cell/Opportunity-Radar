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

from .unified import canonical_title, hours_apart, now, stable_id
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
  article_key TEXT NOT NULL DEFAULT '',
  evidence_id TEXT NOT NULL DEFAULT '',
  claim_id TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}',
  occurrence_count INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE(entity_id, target_kind, target_key, method)
);
CREATE TABLE IF NOT EXISTS entity_relations(
  relation_id TEXT PRIMARY KEY,
  subject_entity_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  object_kind TEXT NOT NULL,
  object_key TEXT NOT NULL,
  article_key TEXT NOT NULL DEFAULT '',
  evidence_id TEXT NOT NULL DEFAULT '',
  claim_id TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}',
  method TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  verification_state TEXT NOT NULL DEFAULT 'unverified',
  created_at TEXT NOT NULL,
  UNIQUE(subject_entity_id, relation_type, object_kind, object_key, evidence_id)
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
CREATE INDEX IF NOT EXISTS idx_relations_subject ON entity_relations(subject_entity_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_object ON entity_relations(object_kind, object_key);
CREATE INDEX IF NOT EXISTS idx_links_left ON event_links(left_kind, left_key);
CREATE INDEX IF NOT EXISTS idx_links_right ON event_links(right_kind, right_key);
"""

LINK_STATUSES = ('candidate', 'accepted', 'rejected')
REL_SAME_SUBJECT = 'same_subject'
REL_SHARED_ENTITY = 'shared_entity'
REL_EVENT_CANDIDATE = 'event_candidate'
EVENT_CANDIDATE_BASIS = 'event_candidate_v1'
DEFAULT_LINK_WINDOW_DAYS = 120
EVENT_EVENT_WINDOW_DAYS = 7
EVENT_CANDIDATE_WINDOW_DAYS = 7
EVENT_CANDIDATE_STRONG_HOURS = 72
MIN_ALIAS_CHARS = 4

# Words that appear in headlines without distinguishing one event from another.
TITLE_STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'been', 'being', 'by', 'for', 'from',
    'has', 'have', 'how', 'in', 'into', 'is', 'it', 'its', 'new', 'not', 'of', 'on',
    'or', 'over', 'says', 'said', 'than', 'that', 'the', 'their', 'this', 'to', 'up',
    'was', 'were', 'what', 'when', 'where', 'who', 'why', 'will', 'with', 'would',
    'after', 'before', 'about', 'could', 'should', 'may', 'might', 'can', 'more',
    'less', 'first', 'last', 'year', 'years', 'month', 'months', 'day', 'days',
    'today', 'yesterday', 'report', 'reports', 'news', 'update', 'updates',
    'show', 'ask', 'hn',
}

ENTITY_CATEGORIES = ('ORGANIZATION', 'GOVERNMENT', 'PRODUCT', 'TECHNOLOGY', 'LOCATION', 'PERSON')
ENTITY_TYPE_BY_CATEGORY = {
    'ORGANIZATION': 'organization', 'GOVERNMENT': 'government', 'PRODUCT': 'product',
    'TECHNOLOGY': 'technology', 'LOCATION': 'location', 'PERSON': 'person',
}
CATEGORY_BY_ENTITY_TYPE = {value: key for key, value in ENTITY_TYPE_BY_CATEGORY.items()}
CATEGORY_BY_ENTITY_TYPE['company'] = 'ORGANIZATION'
CATEGORY_BY_ENTITY_TYPE['org'] = 'ORGANIZATION'
CATEGORY_BY_ENTITY_TYPE['government_agency'] = 'GOVERNMENT'

ORG_SUFFIXES = ('inc', 'corp', 'corporation', 'company', 'co', 'ltd', 'limited', 'group',
                'holdings', 'bank', 'board', 'department', 'commission', 'ministry',
                'authority', 'agency', 'bureau', 'administration', 'council', 'committee',
                'court', 'university', 'association', 'foundation', 'institute',
                'laboratories', 'labs')
GOV_SUFFIXES = {'department', 'commission', 'ministry', 'authority', 'agency', 'bureau',
                'administration', 'board', 'council', 'committee', 'court'}
ORG_SUFFIX_RE = '(?i:(?:' + '|'.join(re.escape(item) for item in ORG_SUFFIXES) + '))'
ORG_RE = re.compile(
    r"\b((?:[A-Z][\w&.\'-]*)(?:\s+(?:[A-Z][\w&.\'-]*|of|and|for|the)){0,6}(?:\s*,\s*|\s+)"
    r"(?:" + ORG_SUFFIX_RE + r"))(?!\s+of\b)\b\.?")

# Explicit controlled names are preferred over a suffix guess. Each is a reviewed mapping,
# not a model guess: the aliases are the forms the title/evidence may actually use.
KNOWN_GOVERNMENT = {
    'Federal Reserve Board': ('Federal Reserve Board', ['Federal Reserve']),
    'U.S. Bureau of Economic Analysis': ('U.S. Bureau of Economic Analysis',
                                         ['Bureau of Economic Analysis', 'BEA']),
    'Bureau of Economic Analysis': ('U.S. Bureau of Economic Analysis',
                                     ['Bureau of Economic Analysis', 'BEA']),
    'Office for National Statistics': ('Office for National Statistics', ['ONS']),
    'Ofcom': ('Ofcom', []),
    'Securities and Exchange Commission': ('Securities and Exchange Commission', ['SEC']),
    'Food and Drug Administration': ('Food and Drug Administration', ['FDA']),
    'Federal Trade Commission': ('Federal Trade Commission', ['FTC']),
    'Department of Justice': ('Department of Justice', ['DOJ']),
    'Environmental Protection Agency': ('Environmental Protection Agency', ['EPA']),
    'European Commission': ('European Commission', []),
    'Bank of England': ('Bank of England', []),
    'European Central Bank': ('European Central Bank', ['ECB']),
}
GOV_ACRONYMS = {
    'SEC': 'Securities and Exchange Commission',
    'EIA': 'Energy Information Administration',
    'FDA': 'Food and Drug Administration',
    'FTC': 'Federal Trade Commission',
    'DOJ': 'Department of Justice',
    'EPA': 'Environmental Protection Agency',
    'FCA': 'Financial Conduct Authority',
    'BEA': 'U.S. Bureau of Economic Analysis',
    'ONS': 'Office for National Statistics',
    'ECB': 'European Central Bank',
}
LOCATION_ALIASES = {
    'United States': ['United States', 'US', 'U.S.', 'USA', 'U.S.A.'],
    'United Kingdom': ['United Kingdom', 'UK', 'U.K.', 'Britain', 'Great Britain'],
    'European Union': ['European Union', 'EU'],
    'China': ['China'], 'Germany': ['Germany'], 'France': ['France'],
    'India': ['India'], 'Japan': ['Japan'], 'Kazakhstan': ['Kazakhstan'],
    'Russia': ['Russia'], 'Ukraine': ['Ukraine'], 'Canada': ['Canada'],
    'Australia': ['Australia'], 'Brazil': ['Brazil'], 'Mexico': ['Mexico'],
    'Delft': ['Delft'], 'Frankfurt': ['Frankfurt'], 'London': ['London'],
    'New York': ['New York'], 'California': ['California'], 'Texas': ['Texas'],
}
GENERIC_ORGANIZATION_KEYS = {'company', 'the company', 'your company', 'a company',
                              'a i company', 'ai company', 'gen z group', 'the group',
                              'group', 'the bank', 'the board', 'board'}
CASE_SENSITIVE_ALIASES = {'US', 'U.S.', 'USA', 'U.S.A.', 'UK', 'U.K.', 'EU',
                          'SEC', 'EIA', 'FDA', 'FTC', 'DOJ', 'EPA', 'FCA', 'BEA', 'ONS', 'ECB'}

REL_MENTIONED_IN = 'MENTIONED_IN'
REL_PUBLISHED_BY = 'PUBLISHED_BY'
REL_APPLICANT = 'APPLICANT'
REL_PETITIONER = 'PETITIONER'
REL_REGULATED_BY = 'REGULATED_BY'
REL_AFFECTED_BY = 'AFFECTED_BY'
REL_RELATED_TO = 'RELATED_TO'
RELATION_TYPES = (REL_MENTIONED_IN, REL_PUBLISHED_BY, REL_APPLICANT, REL_PETITIONER,
                  REL_REGULATED_BY, REL_AFFECTED_BY, REL_RELATED_TO)


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


def entity_category(entity_type):
    return CATEGORY_BY_ENTITY_TYPE.get(str(entity_type or '').strip().lower(),
                                       str(entity_type or '').strip().upper() or 'ORGANIZATION')


def normalise_entity_name(value):
    text = _plain(value)
    text = re.sub(r'^the\s+', '', text, flags=re.I)
    return text.strip(' ,;:()[]{}')


def entity_key_for(category, name):
    return f'{str(category).strip().lower()}:{alias_key(normalise_entity_name(name))}'


def _alias_entries(conn):
    rows = conn.execute(
        "SELECT e.entity_id, e.entity_type, e.canonical_name, a.alias "
        "FROM entity_aliases a JOIN entities e USING(entity_id) "
        "WHERE a.method<>'publisher'").fetchall()
    by_key = {}
    for row in rows:
        key = alias_key(row['alias'])
        if key:
            by_key.setdefault(key, set()).add(row['entity_id'])
    ambiguous = {key for key, ids in by_key.items() if len(ids) > 1}
    entries = []
    for row in rows:
        key = alias_key(row['alias'])
        if not key or key in ambiguous:
            continue
        entries.append((row['entity_id'], entity_category(row['entity_type']),
                        row['canonical_name'], row['alias'],
                        key == alias_key(row['canonical_name'])))
    return entries, ambiguous


def _word_pattern(value):
    return r'(?<![\w])' + re.escape(value) + r'(?![\w])'


def _candidate(category, canonical_name, matched_text, start, end, method, confidence,
               entity_id='', aliases=()):
    return {'entity_id': entity_id, 'category': category, 'canonical_name': canonical_name,
            'matched_text': matched_text, 'start': start, 'end': end,
            'method': method, 'confidence': confidence, 'aliases': list(aliases)}


def extract_text_candidates(text, alias_entries, excluded_names=None, excluded_spans=None):
    """Deterministic entity candidates from text, with offsets and no inferred identity."""
    text = str(text or '')
    if not text.strip():
        return []
    excluded_names = set(excluded_names or ())
    excluded_spans = list(excluded_spans or ())
    candidates = []
    known_keys = {alias_key(alias) for _entity, _cat, _name, alias, _canon in alias_entries}
    for entity_id, category, canonical, alias, is_canonical in alias_entries:
        flags = 0 if alias in CASE_SENSITIVE_ALIASES else re.I
        for match in re.finditer(_word_pattern(alias), text, flags):
            if alias_key(canonical) in excluded_names:
                continue
            candidates.append(_candidate(category, canonical, match.group(0), match.start(),
                                         match.end(), 'known_alias',
                                         0.9 if is_canonical else 0.75, entity_id))
    for match in ORG_RE.finditer(text):
        matched = match.group(0).strip()
        name = normalise_entity_name(matched)
        key = alias_key(name)
        if not key or key in excluded_names or key in known_keys:
            continue
        if re.sub(r'\s+', ' ', key) in GENERIC_ORGANIZATION_KEYS:
            continue
        suffix = name.rstrip('.').split()[-1].lower()
        category = 'GOVERNMENT' if suffix in GOV_SUFFIXES else 'ORGANIZATION'
        if re.match(r"^(federal|national|u\.s\.|uk|office of)\b", name, re.I):
            category = 'GOVERNMENT'
        aliases = derive_aliases(name) if category == 'ORGANIZATION' else [name]
        candidates.append(_candidate(category, name, matched, match.start(),
                                     match.end(), 'suffix_rule', 0.65, aliases=aliases))
    for phrase, (canonical, aliases) in KNOWN_GOVERNMENT.items():
        if alias_key(canonical) in known_keys:
            continue
        for match in re.finditer(_word_pattern(phrase), text, re.I):
            candidates.append(_candidate('GOVERNMENT', canonical, match.group(0), match.start(),
                                         match.end(), 'government_rule', 0.85,
                                         aliases=[canonical] + list(aliases)))
    for acronym, canonical in GOV_ACRONYMS.items():
        if alias_key(canonical) in known_keys or alias_key(acronym) in known_keys:
            continue
        for match in re.finditer(_word_pattern(acronym), text, 0):
            candidates.append(_candidate('GOVERNMENT', canonical, match.group(0), match.start(),
                                         match.end(), 'government_acronym', 0.8,
                                         aliases=[canonical, acronym]))
    for canonical, aliases in LOCATION_ALIASES.items():
        if alias_key(canonical) in known_keys or any(alias_key(alias) in known_keys for alias in aliases):
            continue
        for alias in aliases:
            flags = 0 if alias in CASE_SENSITIVE_ALIASES else re.I
            for match in re.finditer(_word_pattern(alias), text, flags):
                candidates.append(_candidate('LOCATION', canonical, match.group(0), match.start(),
                                             match.end(), 'location_dictionary', 0.8,
                                             aliases=[canonical] + list(aliases)))
    accepted = []
    for candidate in sorted(candidates, key=lambda c: (c['start'], -(c['end'] - c['start']), -c['confidence'])):
        if any(not (candidate['end'] <= span[0] or candidate['start'] >= span[1])
               for span in excluded_spans):
            continue
        key = candidate['entity_id'] or entity_key_for(candidate['category'], candidate['canonical_name'])
        duplicate = any(
            not (candidate['end'] <= other['start'] or candidate['start'] >= other['end'])
            and (other['entity_id'] or entity_key_for(other['category'], other['canonical_name'])) == key
            for other in accepted)
        if not duplicate:
            accepted.append(candidate)
    return accepted


def _ensure_entity(conn, category, name, aliases=(), alias_method='extracted'):
    name = normalise_entity_name(name)
    key = entity_key_for(category, name)
    row = conn.execute('SELECT entity_id FROM entities WHERE canonical_key=?', (key,)).fetchone()
    created = False
    if row:
        entity_id = row['entity_id']
    else:
        entity_id = entity_id_for(key)
        conn.execute(
            'INSERT OR IGNORE INTO entities(entity_id,entity_type,canonical_name,canonical_key,cik,ticker,created_at) '
            'VALUES(?,?,?,?,?,?,?)',
            (entity_id, ENTITY_TYPE_BY_CATEGORY[category], name, key, '', '', now()))
        row = conn.execute('SELECT entity_id FROM entities WHERE canonical_key=?', (key,)).fetchone()
        entity_id = row['entity_id']
        created = True
    for alias in [name] + list(aliases):
        alias = _plain(alias).strip()
        akey = alias_key(alias)
        if not akey or (len(akey) < MIN_ALIAS_CHARS and category not in ('LOCATION', 'GOVERNMENT')):
            continue
        conn.execute('INSERT OR IGNORE INTO entity_aliases(entity_id,alias,alias_key,method,created_at) '
                     'VALUES(?,?,?,?,?)',
                     (entity_id, alias, akey, alias_method, now()))
    return entity_id, created


def _record_mention(conn, entity_id, target_kind, target_key, method, matched_text, confidence,
                    article_key='', evidence_id='', claim_id='', locator=None,
                    occurrence_count=1):
    mention_id = stable_id('men-', entity_id, target_kind, target_key, method)
    locator_json = json.dumps(locator or {}, ensure_ascii=False, sort_keys=True)
    existing = conn.execute('SELECT mention_id FROM entity_mentions WHERE mention_id=?',
                            (mention_id,)).fetchone()
    if existing:
        conn.execute(
            'UPDATE entity_mentions SET matched_text=?, confidence=?, article_key=?, evidence_id=?, '
            'claim_id=?, locator_json=?, occurrence_count=? WHERE mention_id=?',
            (matched_text, confidence, article_key, evidence_id, claim_id, locator_json,
             occurrence_count, mention_id))
        return 'updated'
    conn.execute(
        'INSERT INTO entity_mentions(mention_id,entity_id,target_kind,target_key,method,matched_text,'
        'confidence,article_key,evidence_id,claim_id,locator_json,occurrence_count,created_at) '
        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (mention_id, entity_id, target_kind, target_key, method, matched_text, confidence,
         article_key, evidence_id, claim_id, locator_json, occurrence_count, now()))
    return 'inserted'


def _record_relation(conn, subject_entity_id, relation_type, object_kind, object_key,
                     article_key='', evidence_id='', claim_id='', locator=None,
                     method='cue', confidence=0.6):
    relation_id = stable_id('rel-', subject_entity_id, relation_type, object_kind,
                            object_key, evidence_id)
    return conn.execute(
        'INSERT OR IGNORE INTO entity_relations(relation_id,subject_entity_id,relation_type,object_kind,'
        'object_key,article_key,evidence_id,claim_id,locator_json,method,confidence,verification_state,created_at) '
        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (relation_id, subject_entity_id, relation_type, object_kind, object_key, article_key,
         evidence_id, claim_id, json.dumps(locator or {}, ensure_ascii=False, sort_keys=True),
         method, confidence, 'unverified', now())).rowcount > 0


_APPLICANT_CUE = re.compile(
    r"\{\{(\d+)\}\}\s+(?:has |have )?(?:applied|filed an application|submitted an application)\b", re.I)
_PETITIONER_CUE = re.compile(
    r"\{\{(\d+)\}\}\s+(?:has |have )?(?:petitioned|filed a petition|submitted a petition)\b", re.I)
_REGULATED_BY_CUE = re.compile(
    r"\{\{(\d+)\}\}\s+(?:is|are)\s+regulated\s+by\s+\{\{(\d+)\}\}", re.I)
_REGULATES_CUE = re.compile(r"\{\{(\d+)\}\}\s+regulates\s+\{\{(\d+)\}\}", re.I)


def extract_text_relations(text, candidates, article_key, evidence_id='', claim_id='',
                           source_locator=None, event_id=''):
    """Only explicit sentence cues create relations. Mention is not a relation.

    AFFECTED_BY and RELATED_TO are deliberately not inferred here: industry similarity is
    not evidence that an entity was affected, and a generic related-to edge would hide the
    missing proof.
    """
    text = str(text or '')
    usable = [candidate for candidate in candidates if candidate.get('entity_id')]
    relations = []
    for sentence_match in re.finditer(r'[^.!?]+[.!?]?', text):
        sentence = sentence_match.group(0)
        offset = sentence_match.start()
        spans = [candidate for candidate in usable
                 if candidate['start'] >= offset and candidate['end'] <= offset + len(sentence)]
        if not spans:
            continue
        masked = sentence
        for index in reversed(range(len(spans))):
            candidate = spans[index]
            local_start = candidate['start'] - offset
            local_end = candidate['end'] - offset
            masked = masked[:local_start] + '{{%d}}' % index + masked[local_end:]
        for pattern, relation_type, method in ((_APPLICANT_CUE, REL_APPLICANT, 'cue:applied'),
                                                (_PETITIONER_CUE, REL_PETITIONER, 'cue:petitioned')):
            for match in pattern.finditer(masked):
                candidate = spans[int(match.group(1))]
                if not article_key:
                    continue
                relations.append({
                    'subject_entity_id': candidate['entity_id'],
                    'relation_type': relation_type,
                    'object_kind': 'event' if event_id else 'article',
                    'object_key': event_id or article_key,
                    'article_key': article_key,
                    'evidence_id': evidence_id,
                    'claim_id': claim_id,
                    'method': method,
                    'confidence': 0.65,
                    'locator': {'field': 'relation_cue', 'start': candidate['start'],
                                'length': candidate['end'] - candidate['start'],
                                'sentence': sentence[:300],
                                **({'source_locator': source_locator} if source_locator else {})},
                })
        for pattern, reverse in ((_REGULATED_BY_CUE, False), (_REGULATES_CUE, True)):
            for match in pattern.finditer(masked):
                pair = (int(match.group(1)), int(match.group(2)))
                subject_index, object_index = pair if reverse else pair
                if reverse:
                    subject_index, object_index = pair[1], pair[0]
                subject, regulator = spans[subject_index], spans[object_index]
                relations.append({
                    'subject_entity_id': subject['entity_id'],
                    'relation_type': REL_REGULATED_BY,
                    'object_kind': 'entity',
                    'object_key': regulator['entity_id'],
                    'article_key': article_key,
                    'evidence_id': evidence_id,
                    'claim_id': claim_id,
                    'method': 'cue:regulated_by',
                    'confidence': 0.7,
                    'locator': {'field': 'relation_cue', 'start': subject['start'],
                                'length': subject['end'] - subject['start'],
                                'sentence': sentence[:300],
                                **({'source_locator': source_locator} if source_locator else {})},
                })
    return relations


def _json_dict(raw):
    try:
        value = json.loads(raw or '{}')
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _source_name_spans(text, source_name):
    if not source_name:
        return []
    return [(match.start(), match.end())
            for match in re.finditer(re.escape(source_name), str(text or ''), re.I)]


def _precreate_candidates(conn, report, alias_entries, ambiguous, text,
                         excluded_names=None, excluded_spans=None):
    """Create pattern entities before mention matching so one run is self-consistent."""
    for candidate in extract_text_candidates(text, alias_entries, excluded_names, excluded_spans):
        if candidate.get('entity_id'):
            continue
        key = alias_key(candidate['canonical_name'])
        if key in ambiguous:
            continue
        aliases = list(candidate.get('aliases') or ())
        if candidate.get('matched_text') and candidate['matched_text'] not in aliases:
            aliases.append(candidate['matched_text'])
        _entity_id, created = _ensure_entity(
            conn, candidate['category'], candidate['canonical_name'], aliases)
        report['entities_created'] += int(created)


def _extract_from_source(conn, report, alias_entries, ambiguous, target_kind, target_key,
                         text, article_key, evidence_id, claim_id, field, source_locator,
                         excluded_names, excluded_spans, event_id=''):
    candidates = extract_text_candidates(text, alias_entries, excluded_names, excluded_spans)
    resolved = []
    for candidate in candidates:
        if not candidate.get('entity_id'):
            key = alias_key(candidate['canonical_name'])
            if key in ambiguous:
                report['ambiguous_mentions'] += 1
                continue
            aliases = list(candidate.get('aliases') or ())
            if candidate.get('matched_text') and candidate['matched_text'] not in aliases:
                aliases.append(candidate['matched_text'])
            entity_id, created = _ensure_entity(
                conn, candidate['category'], candidate['canonical_name'], aliases)
            candidate['entity_id'] = entity_id
            report['entities_created'] += int(created)
        resolved.append(candidate)
    grouped = {}
    for candidate in resolved:
        key = (candidate['entity_id'], candidate['method'])
        if key not in grouped:
            grouped[key] = [candidate, 0]
        grouped[key][1] += 1
    for (entity_id, _method), (candidate, count) in grouped.items():
        locator = {'field': field, 'start': candidate['start'],
                   'length': candidate['end'] - candidate['start']}
        if source_locator:
            locator['source_locator'] = source_locator
        _record_mention(conn, entity_id, target_kind, target_key,
                        f"{field}:{candidate['method']}",
                        candidate['matched_text'], candidate['confidence'],
                        article_key=article_key, evidence_id=evidence_id,
                        claim_id=claim_id, locator=locator, occurrence_count=count)
        report['mention_rows'] += 1
        report['mention_occurrences'] += count
        report['mentions_by_category'][candidate['category']] = report['mentions_by_category'].get(candidate['category'], 0) + count
        if evidence_id:
            report['mentions_with_evidence'] += 1
        report['mentions_with_locator'] += 1
    for relation in extract_text_relations(text, resolved, article_key,
                                            evidence_id=evidence_id, claim_id=claim_id,
                                            source_locator=source_locator, event_id=event_id):
        inserted = _record_relation(
            conn, relation['subject_entity_id'], relation['relation_type'],
            relation['object_kind'], relation['object_key'],
            article_key=relation['article_key'], evidence_id=relation['evidence_id'],
            claim_id=relation['claim_id'], locator=relation['locator'],
            method=relation['method'], confidence=relation['confidence'])
        if inserted:
            report['relations'][relation['relation_type']] += 1
            report['unverified_relations'] += 1


def _backfill_mention_locators(conn):
    """Give old article-level mentions a title locator when the raw text is still there."""
    updated = 0
    rows = [dict(row) for row in conn.execute(
        "SELECT mention_id, article_key, matched_text FROM entity_mentions "
        "WHERE target_kind='article' AND article_key<>'' AND locator_json IN ('{}','')")]
    for row in rows:
        title = conn.execute('SELECT title FROM articles WHERE article_key=?',
                             (row['article_key'],)).fetchone()
        if not title:
            continue
        match = re.search(_word_pattern(row['matched_text']), title[0] or '', re.I)
        if not match:
            continue
        locator = json.dumps({'field': 'title', 'start': match.start(),
                              'length': match.end() - match.start()},
                             ensure_ascii=False, sort_keys=True)
        conn.execute('UPDATE entity_mentions SET locator_json=? WHERE mention_id=?',
                     (locator, row['mention_id']))
        updated += 1
    return updated


def extract_entities(store):
    """Extract mentions and explicit relations from stored titles, evidence and claims.

    Only stored text is read. A mention keeps its raw text, article/evidence/claim key,
    locator and category. A relation is written only when an explicit sentence cue names
    it; a mere mention is never promoted to APPLICANT, REGULATED_BY or AFFECTED_BY.
    """
    report = {'articles_scanned': 0, 'evidences_scanned': 0, 'claims_scanned': 0,
              'mention_rows': 0, 'mention_occurrences': 0, 'entities_created': 0,
              'mentions_with_evidence': 0, 'mentions_with_locator': 0,
              'ambiguous_mentions': 0, 'ambiguous_alias_keys': 0,
              'mentions_by_category': {category: 0 for category in ENTITY_CATEGORIES},
              'relations': {relation_type: 0 for relation_type in RELATION_TYPES},
              'unverified_relations': 0}
    with store.connect() as conn:
        alias_entries, ambiguous = _alias_entries(conn)
        report['ambiguous_alias_keys'] = len(ambiguous)
        articles = [dict(row) for row in conn.execute(
            'SELECT article_key, title, source_name FROM articles ORDER BY article_key')]
        evidences = [dict(row) for row in conn.execute(
            'SELECT evidence_id, article_key, quote, locator_json FROM evidences ORDER BY evidence_id')]
        claims = [dict(row) for row in conn.execute(
            "SELECT c.claim_id, c.article_key, c.value_text, c.quote, c.locator_json, "
            "(SELECT ce.evidence_id FROM claim_evidence ce WHERE ce.claim_id=c.claim_id "
            " ORDER BY ce.evidence_id LIMIT 1) AS evidence_id "
            "FROM claims c ORDER BY c.claim_id")]
        event_by_article = {row['article_key']: row['event_id'] for row in conn.execute(
            'SELECT article_key, event_id FROM event_articles')}
        # First pass: create deterministic pattern entities, then reload aliases and
        # extract mentions. Otherwise aliases created during this run would only match
        # on the next run, making the first result look smaller than the stable result.
        for article in articles:
            excluded = {alias_key(article['source_name'])} if article.get('source_name') else set()
            _precreate_candidates(conn, report, alias_entries, ambiguous,
                                  article['title'] or '', excluded,
                                  _source_name_spans(article['title'], article.get('source_name')))
        for evidence in evidences:
            _precreate_candidates(conn, report, alias_entries, ambiguous, evidence['quote'] or '')
        for claim in claims:
            _precreate_candidates(conn, report, alias_entries, ambiguous,
                                  claim['value_text'] or claim['quote'] or '')
        alias_entries, ambiguous = _alias_entries(conn)
        for article in articles:
            report['articles_scanned'] += 1
            excluded = {alias_key(article['source_name'])} if article.get('source_name') else set()
            _extract_from_source(
                conn, report, alias_entries, ambiguous, 'article', article['article_key'],
                article['title'] or '', article['article_key'], '', '', 'title', None,
                excluded, _source_name_spans(article['title'], article.get('source_name')),
                event_id=event_by_article.get(article['article_key'], ''))
        for evidence in evidences:
            report['evidences_scanned'] += 1
            _extract_from_source(
                conn, report, alias_entries, ambiguous, 'evidence', evidence['evidence_id'],
                evidence['quote'] or '', evidence['article_key'] or '', evidence['evidence_id'],
                '', 'evidence_quote', _json_dict(evidence['locator_json']), set(), [],
                event_id=event_by_article.get(evidence['article_key'] or '', ''))
        for claim in claims:
            report['claims_scanned'] += 1
            _extract_from_source(
                conn, report, alias_entries, ambiguous, 'claim', claim['claim_id'],
                claim['value_text'] or claim['quote'] or '', claim['article_key'] or '',
                claim['evidence_id'] or '', claim['claim_id'], 'claim_text',
                _json_dict(claim['locator_json']), set(), [],
                event_id=event_by_article.get(claim['article_key'] or '', ''))

        report['locators_backfilled'] = _backfill_mention_locators(conn)
        report['mention_rows_written'] = report['mention_rows']
        report['mention_occurrences_written'] = report['mention_occurrences']
        report['mention_rows'] = conn.execute('SELECT COUNT(*) FROM entity_mentions').fetchone()[0]
        report['mention_occurrences'] = conn.execute(
            'SELECT COALESCE(SUM(occurrence_count),0) FROM entity_mentions').fetchone()[0]
        report['mentions_with_evidence'] = conn.execute(
            "SELECT COUNT(*) FROM entity_mentions WHERE evidence_id<>''").fetchone()[0]
        report['mentions_with_locator'] = conn.execute(
            "SELECT COUNT(*) FROM entity_mentions WHERE locator_json NOT IN ('{}','')").fetchone()[0]
        report['mentions_by_category'] = {category: 0 for category in ENTITY_CATEGORIES}
        for row in conn.execute(
                'SELECT e.entity_type, COUNT(*), COALESCE(SUM(m.occurrence_count),0) '
                'FROM entity_mentions m JOIN entities e USING(entity_id) GROUP BY e.entity_type'):
            category = entity_category(row[0])
            report['mentions_by_category'][category] = report['mentions_by_category'].get(category, 0) + row[2]
        report['entity_count'] = conn.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
        report['entity_count_by_category'] = {category: 0 for category in ENTITY_CATEGORIES}
        for row in conn.execute('SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type'):
            category = entity_category(row[0])
            report['entity_count_by_category'][category] = report['entity_count_by_category'].get(category, 0) + row[1]
        report['relations'] = {relation_type: 0 for relation_type in RELATION_TYPES}
        for row in conn.execute('SELECT relation_type, COUNT(*) FROM entity_relations GROUP BY relation_type'):
            report['relations'][row[0]] = row[1]
        report['relations'][REL_MENTIONED_IN] = report['mention_rows']
        report['unverified_relations'] = conn.execute(
            "SELECT COUNT(*) FROM entity_relations WHERE verification_state='unverified'").fetchone()[0]
    return report


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


def title_tokens(title):
    """Distinctive words in a headline, with boilerplate removed."""
    text = canonical_title(title)
    return {token for token in re.findall(r'[0-9a-z一-鿿]+', text)
            if token not in TITLE_STOPWORDS and (len(token) >= 2 or token.isdigit())}


def _set_similarity(left, right):
    """(Jaccard, containment). Containment catches a short headline inside a longer one."""
    if not left or not right:
        return 0.0, 0.0
    shared = left & right
    return len(shared) / len(left | right), len(shared) / min(len(left), len(right))


def source_independence(rows):
    """Count articles, source ids, source families and independent units separately.

    A family is one organisation, not one feed. Unknown independence never contributes.
    Two families in the same recorded syndication group are one unit. This function does
    not decide whether a pair is a reprint; it only uses recorded lineage.
    """
    rows = [dict(row) for row in rows]

    def record_key(row):
        return str(row.get('article_key') or row.get('evidence_id') or '').strip()

    families = sorted({str(row.get('source_family') or '').strip()
                       for row in rows if str(row.get('source_family') or '').strip()})
    source_ids = sorted({str(row.get('source_id') or '').strip()
                         for row in rows if str(row.get('source_id') or '').strip()})
    family_articles = {}
    syndicated_articles = set()
    unknown_family_articles = set()
    unknown_independence_evidence = 0
    for row in rows:
        article = record_key(row)
        family = str(row.get('source_family') or '').strip()
        status = str(row.get('independence') or 'unknown').strip() or 'unknown'
        if family and article:
            family_articles.setdefault(family, set()).add(article)
        if str(row.get('syndication_group') or '').strip() and article:
            syndicated_articles.add(article)
        if not family and article:
            unknown_family_articles.add(article)
        if status not in CORROBORATING:
            unknown_independence_evidence += 1
    family_article_counts = {family: len(articles)
                             for family, articles in sorted(family_articles.items())}
    units = set()
    groups = set()
    for row in rows:
        family = str(row.get('source_family') or '').strip()
        status = str(row.get('independence') or 'unknown').strip() or 'unknown'
        group = str(row.get('syndication_group') or '').strip()
        if group:
            groups.add(group)
        if status in CORROBORATING and family:
            units.add(group or family)
    if not rows:
        status = 'INSUFFICIENT_DATA'
    elif not units:
        status = 'UNKNOWN'
    elif len(units) == 1 and (unknown_family_articles or unknown_independence_evidence):
        status = 'PARTIAL'
    elif len(units) == 1:
        status = 'SINGLE_SOURCE'
    else:
        status = 'MULTI_SOURCE'
    return {
        'records': len(rows),
        'article_or_record_count': len({record_key(row) for row in rows if record_key(row)}),
        'source_count': len(source_ids),
        'source_family_count': len(families),
        'source_families': families,
        'family_article_counts': family_article_counts,
        'same_family_article_count': sum(count for count in family_article_counts.values()
                                         if count > 1),
        'syndicated_evidence_count': sum(1 for row in rows
                                         if str(row.get('syndication_group') or '').strip()),
        'syndicated_article_count': len(syndicated_articles),
        'syndication_groups': sorted(groups),
        'unknown_family_article_count': len(unknown_family_articles),
        'unknown_independence_evidence_count': unknown_independence_evidence,
        'independent_source_units': len(units),
        'independent_corroboration': len(units) >= 2,
        'independence_status': status,
    }


def _event_candidate_records(store):
    """Read the event/article/evidence/entity material needed for candidate comparison."""
    with store.connect() as conn:
        events = {r['event_id']: dict(r) for r in conn.execute(
            "SELECT event_id, event_type, first_seen_at, last_seen_at FROM events")}
        for event in events.values():
            event.update({'articles': [], 'evidence_rows': [], 'entities': set()})
        for row in conn.execute(
                "SELECT ea.event_id, ea.article_key, a.title, a.published, a.source_name "
                "FROM event_articles ea LEFT JOIN articles a USING(article_key)"):
            event = events.get(row['event_id'])
            if event is not None:
                event['articles'].append(dict(row))
        for row in conn.execute(
                "SELECT ea.event_id, v.evidence_id, v.article_key, v.quote, v.source_id, "
                "v.source_family, v.independence, v.syndication_group "
                "FROM event_articles ea JOIN evidences v USING(article_key)"):
            event = events.get(row['event_id'])
            if event is not None:
                event['evidence_rows'].append(dict(row))
        for row in conn.execute(
                "SELECT DISTINCT m.entity_id, COALESCE(e.entity_type,'organization') AS entity_type, "
                "       ea.event_id "
                "FROM entity_mentions m "
                "JOIN event_articles ea ON ea.article_key=m.target_key "
                "LEFT JOIN entities e ON e.entity_id=m.entity_id "
                "WHERE m.target_kind='article'"):
            event = events.get(row['event_id'])
            # A country or city is too broad to distinguish one event from another.
            if event is not None and entity_category(row['entity_type']) != 'LOCATION':
                event['entities'].add(row['entity_id'])
    records = []
    for event in events.values():
        if not event['articles']:
            continue
        titles = [str(a.get('title') or '') for a in event['articles'] if str(a.get('title') or '').strip()]
        times = [event.get('first_seen_at'), event.get('last_seen_at')]
        times += [a.get('published') for a in event['articles'] if a.get('published')]
        times = [str(t) for t in times if t]
        quotes = []
        for row in event['evidence_rows']:
            quote = str(row.get('quote') or '').strip()
            if quote:
                quotes.append({'evidence_id': row.get('evidence_id') or '',
                               'quote': quote, 'tokens': title_tokens(quote)})
        event['titles'] = titles
        event['title_tokens'] = [title_tokens(title) for title in titles]
        event['time'] = min(times) if times else ''
        event['quotes'] = quotes
        event['families'] = sorted({str(r.get('source_family') or '').strip()
                                    for r in event['evidence_rows']
                                    if str(r.get('source_family') or '').strip()})
        event['source_ids'] = sorted({str(r.get('source_id') or '').strip()
                                      for r in event['evidence_rows']
                                      if str(r.get('source_id') or '').strip()})
        event['independence'] = source_independence(event['evidence_rows'])
        records.append(event)
    return records


def _best_title_match(left, right):
    best = {'score': 0.0, 'jaccard': 0.0, 'containment': 0.0, 'shared': []}
    for a in left:
        for b in right:
            jaccard, containment = _set_similarity(a, b)
            score = max(jaccard, containment * 0.9)
            if score > best['score'] or (score == best['score'] and len(a & b) > len(best['shared'])):
                best = {'score': score, 'jaccard': jaccard, 'containment': containment,
                        'shared': sorted(a & b)}
    return best


def _best_quote_match(left, right):
    best_score = 0.0
    best_ids = []
    for a in left:
        for b in right:
            jaccard, containment = _set_similarity(a['tokens'], b['tokens'])
            score = max(jaccard, containment * 0.9)
            if score > best_score:
                best_score = score
                best_ids = sorted({a['evidence_id'], b['evidence_id']})
    return best_score, best_ids


def link_event_candidates(store, window_days=EVENT_CANDIDATE_WINDOW_DAYS):
    """Find strong/weak event pairs and record them as candidates; never merge.

    A strong candidate needs a secondary signal beyond title similarity: a shared
    registered entity, a shared evidence sentence, or the same event type. A title-only
    match is at most weak. Pairs below the weak threshold stay unlinked.
    """
    records = _event_candidate_records(store)
    result = {'events': len(records), 'pairs_compared': 0, 'missing_time': 0,
              'outside_window': 0, 'strong': 0, 'weak': 0, 'unrelated': 0,
              'candidate_count': 0, 'created': 0, 'existing': 0,
              'reprint_candidates': 0, 'same_family_pairs': 0,
              'unknown_reprint_status': 0, 'candidates': []}
    for index, left_record in enumerate(records):
        for right_record in records[index + 1:]:
            left, right = sorted((left_record, right_record), key=lambda item: item['event_id'])
            result['pairs_compared'] += 1
            gap = hours_apart(left.get('time'), right.get('time'))
            if gap is None:
                result['missing_time'] += 1
                continue
            if gap > window_days * 24:
                result['outside_window'] += 1
                continue
            title = _best_title_match(left['title_tokens'], right['title_tokens'])
            quote_score, quote_ids = _best_quote_match(left['quotes'], right['quotes'])
            shared_entities = sorted(left['entities'] & right['entities'])
            type_match = bool(left.get('event_type') and left.get('event_type') == right.get('event_type'))
            secondary = bool(shared_entities or quote_score >= 0.75 or type_match)
            shared_title = title['shared']
            strong = (gap <= EVENT_CANDIDATE_STRONG_HOURS
                      and len(shared_title) >= 2
                      and title['score'] >= 0.55
                      and secondary)
            if (gap <= EVENT_CANDIDATE_STRONG_HOURS and quote_score >= 0.9
                    and (title['score'] >= 0.35 or shared_entities)):
                strong = True
            weak = (not strong and len(shared_title) >= 2
                    and (title['score'] >= 0.5
                         or (len(shared_title) >= 3 and title['score'] >= 0.4)
                         or (shared_entities and title['score'] >= 0.3)
                         or (quote_score >= 0.7 and title['score'] >= 0.3)))
            if not strong and not weak:
                result['unrelated'] += 1
                continue

            left_families = set(left.get('families') or [])
            right_families = set(right.get('families') or [])
            same_family = bool(left_families & right_families)
            known_families = bool(left_families and right_families)
            if same_family:
                reprint_status = 'same_source_family'
                result['same_family_pairs'] += 1
            elif not known_families:
                reprint_status = 'unknown'
                result['unknown_reprint_status'] += 1
            elif (gap <= EVENT_CANDIDATE_STRONG_HOURS
                  and (quote_score >= 0.85 or title['score'] >= 0.95)):
                reprint_status = 'reprint_candidate'
                result['reprint_candidates'] += 1
            else:
                reprint_status = 'not_detected'
            reprint_candidate = reprint_status == 'reprint_candidate'
            grade = 'strong' if strong else 'weak'
            result[grade] += 1
            result['candidate_count'] += 1
            if strong:
                confidence = (0.5 + 0.3 * title['score']
                              + (0.08 if shared_entities else 0.0)
                              + (0.08 if quote_score >= 0.75 else 0.0))
            else:
                confidence = 0.35 + 0.2 * title['score']
            confidence = round(min(0.95, max(0.2, confidence)), 3)
            evidence = {
                'grade': grade,
                'left_event_id': left['event_id'],
                'right_event_id': right['event_id'],
                'left_article_keys': [str(a.get('article_key') or '') for a in left['articles']],
                'right_article_keys': [str(a.get('article_key') or '') for a in right['articles']],
                'left_titles': left['titles'][:3],
                'right_titles': right['titles'][:3],
                'title_similarity': round(title['score'], 4),
                'title_jaccard': round(title['jaccard'], 4),
                'title_containment': round(title['containment'], 4),
                'shared_title_tokens': shared_title[:20],
                'shared_entities': shared_entities[:20],
                'quote_similarity': round(quote_score, 4),
                'shared_quote_evidence_ids': quote_ids[:10],
                'event_types': [left.get('event_type') or '', right.get('event_type') or ''],
                'gap_hours': round(gap, 2),
                'reprint_status': reprint_status,
                'reprint_candidate': reprint_candidate,
                'left_source_families': sorted(left_families),
                'right_source_families': sorted(right_families),
                'left_independence_status': left['independence']['independence_status'],
                'right_independence_status': right['independence']['independence_status'],
                'rules_version': EVENT_CANDIDATE_BASIS,
            }
            created = _link(store, 'event', left['event_id'], 'event', right['event_id'],
                            REL_EVENT_CANDIDATE, EVENT_CANDIDATE_BASIS, confidence, evidence)
            result['created'] += int(created)
            if len(result['candidates']) < 20:
                result['candidates'].append({
                    'left_event_id': left['event_id'], 'right_event_id': right['event_id'],
                    'grade': grade, 'confidence': confidence, 'gap_hours': round(gap, 2),
                    'title_similarity': round(title['score'], 4),
                    'shared_title_tokens': shared_title[:8],
                    'shared_entities': shared_entities[:5],
                    'quote_similarity': round(quote_score, 4),
                    'reprint_status': reprint_status,
                    'created': bool(created),
                })
    result['existing'] = result['candidate_count'] - result['created']
    return result


def event_profile(store, event_id):
    """What stands behind one event, counted four ways and never conflated.

    Articles, sources, source families and corroborating units are different numbers. A
    family counts as a corroborating unit only when its evidence carries a recorded
    independence; evidences that merely share a wire copy collapse into one unit.
    """
    store_has_articles = getattr(store, 'has_articles', False)
    with store.connect() as conn:
        articles = conn.execute('SELECT COUNT(*) FROM event_articles WHERE event_id=?', (event_id,)).fetchone()[0]
        has_lineage = True
        try:
            conn.execute('SELECT syndication_group FROM evidences LIMIT 1')
        except sqlite3.OperationalError:
            has_lineage = False
        group_expr = "COALESCE(v.syndication_group,'')" if has_lineage else "''"
        rows = [dict(r) for r in conn.execute(
            f'''SELECT v.evidence_id, v.article_key, v.source_id, v.source_family, v.independence,
                      v.evidence_kind, {group_expr} AS syndication_group
               FROM event_articles ea JOIN evidences v USING(article_key) WHERE ea.event_id=?''', (event_id,))]
        claims = conn.execute('''SELECT COUNT(*) FROM claims c JOIN event_articles ea ON ea.article_key = c.article_key
                                 WHERE ea.event_id=?''', (event_id,)).fetchone()[0]
        members = [dict(r) for r in conn.execute(
            '''SELECT a.title, a.url, a.source_name FROM event_articles e
               JOIN articles a USING(article_key) WHERE e.event_id=?
               ORDER BY a.published, a.article_key''', (event_id,))] if store_has_articles else []
        member_sources = sorted({r[0] for r in conn.execute(
            'SELECT a.source_name FROM event_articles e JOIN articles a USING(article_key) '
            'WHERE e.event_id=? AND a.source_name IS NOT NULL AND length(a.source_name)>0', (event_id,))})
        links = conn.execute('''SELECT COUNT(*) FROM event_links
                                WHERE (left_kind='event' AND left_key=?) OR (right_kind='event' AND right_key=?)''',
                             (event_id, event_id)).fetchone()[0]
        # What the reader can actually check: each claim with the evidence that backs it,
        # the evidence's place in the source text, and who published it.
        claim_items = [dict(r) for r in conn.execute(
            '''SELECT c.claim_id, c.article_key, c.subject, c.predicate, c.value_text, c.kind,
                      c.verification_state, c.extractor, c.locator_json,
                      (SELECT ce.evidence_id FROM claim_evidence ce WHERE ce.claim_id=c.claim_id LIMIT 1) AS evidence_id,
                      (SELECT v.source_id FROM claim_evidence ce JOIN evidences v USING(evidence_id)
                        WHERE ce.claim_id=c.claim_id LIMIT 1) AS evidence_source_id
               FROM claims c JOIN event_articles ea ON ea.article_key = c.article_key
               WHERE ea.event_id=?
               ORDER BY CASE c.verification_state WHEN 'verified' THEN 0 ELSE 1 END, c.fact_ordinal
               LIMIT 6''', (event_id,))]
        link_items = [dict(r) for r in conn.execute(
            '''SELECT link_id, left_kind, left_key, right_kind, right_key, relation, basis, status,
                      confidence, evidence_json
               FROM event_links
               WHERE (left_kind='event' AND left_key=?) OR (right_kind='event' AND right_key=?)
               ORDER BY CASE status WHEN 'accepted' THEN 0 WHEN 'candidate' THEN 1 ELSE 2 END, confidence DESC
               LIMIT 6''', (event_id, event_id))]
        event_candidate_rows = [dict(r) for r in conn.execute(
            '''SELECT evidence_json FROM event_links
               WHERE relation=? AND ((left_kind='event' AND left_key=?)
                                     OR (right_kind='event' AND right_key=?))''',
            (REL_EVENT_CANDIDATE, event_id, event_id))]
    sources = sorted({r['source_id'] for r in rows if r['source_id']})
    independence_counts, kinds = {}, {}
    for row in rows:
        status = row['independence'] or 'unknown'
        independence_counts[status] = independence_counts.get(status, 0) + 1
        kinds[row['evidence_kind']] = kinds.get(row['evidence_kind'], 0) + 1
    independence = source_independence(rows)
    reprint_candidate_links = 0
    for row in event_candidate_rows:
        try:
            evidence = json.loads(row.get('evidence_json') or '{}')
        except (TypeError, ValueError):
            evidence = {}
        if evidence.get('reprint_candidate'):
            reprint_candidate_links += 1
    if independence['independence_status'] == 'MULTI_SOURCE':
        note = (f"至少两个独立来源单元（{independence['independent_source_units']} 个），"
                f"可视为多来源佐证；文章数量不等于独立来源数量")
    elif independence['independence_status'] == 'SINGLE_SOURCE':
        note = '仅一个已知独立来源单元；文章数量和证据数量都不等于独立来源数量'
    elif independence['independence_status'] == 'PARTIAL':
        note = '只有部分来源有独立性记录；未知来源不计入独立佐证'
    elif independence['independence_status'] == 'UNKNOWN':
        note = '来源独立性未知：未知来源族不能默认视为独立来源'
    else:
        note = '没有足够数据计算来源独立性'
    return {
        'event_id': event_id,
        'articles': articles,
        'members': members,
        'sources': sources,
        'member_sources': member_sources,
        'evidences': len(rows),
        'claims': claims,
        'source_families': independence['source_families'],
        'source_family_count': independence['source_family_count'],
        'source_count': independence['source_count'],
        'family_article_counts': independence['family_article_counts'],
        'same_family_article_count': independence['same_family_article_count'],
        'syndicated_evidence_count': independence['syndicated_evidence_count'],
        'syndicated_article_count': independence['syndicated_article_count'],
        'unknown_family_article_count': independence['unknown_family_article_count'],
        'unknown_independence_evidence_count': independence['unknown_independence_evidence_count'],
        'independent_source_units': independence['independent_source_units'],
        'independence_status': independence['independence_status'],
        'independence': independence_counts,
        'evidence_kinds': kinds,
        'syndication_groups': independence['syndication_groups'],
        'corroborating_units': independence['independent_source_units'],
        'candidate_links': links,
        'event_candidate_links': len(event_candidate_rows),
        'reprint_candidate_links': reprint_candidate_links,
        'claim_items': claim_items,
        'link_items': link_items,
        'links_by_status': {status: sum(1 for item in link_items if item['status'] == status)
                            for status in sorted({item['status'] for item in link_items})},
        'independent_corroboration': independence['independent_corroboration'],
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

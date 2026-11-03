"""Bind stored articles to their registered source_id.

The analysis metadata has carried source_id since v5, but the articles table itself did
not. That left the source relationship dependent on analysis JSON and made pre-analysis
articles unaddressable by source. This module resolves the binding without guessing:

1. an existing non-empty articles.source_id is kept;
2. analysis meta source_id is used only when it names a registered source;
3. an unambiguous normalized source_name match is used as fallback;
4. reviewed feed-label aliases are used only for the explicit observed labels below;
5. ambiguous, missing or unknown names remain empty and are reported.
"""
from __future__ import annotations

import json
import re

from .source_policy import load_sources

# Reviewed feed labels that differ from the registry display name. These are explicit
# aliases, not fuzzy matches: each maps one observed feed label to one source_id.
EXPLICIT_SOURCE_ALIASES = {
    'simscale forum': 'simscale-forum',
    'salome forum': 'salome-forum',
    'uk ons release calendar': 'uk-ons',
}


def normalise_name(value):
    text = re.sub(r'[^0-9a-z一-鿿]+', ' ', str(value or '').lower())
    return re.sub(r'\s+', ' ', text).strip()


def index_sources(sources):
    by_id = {source.source_id: source for source in sources}
    by_name = {}
    ambiguous = set()
    for source in sources:
        key = normalise_name(source.name)
        if not key:
            continue
        prior = by_name.get(key)
        if prior is not None and prior.source_id != source.source_id:
            ambiguous.add(key)
        else:
            by_name[key] = source
    for key in ambiguous:
        by_name.pop(key, None)
    return by_id, by_name, ambiguous


def backfill_article_sources(store, sources=None, dry_run=False):
    """Resolve and optionally persist articles.source_id. Returns an audit summary."""
    sources = list(sources if sources is not None else load_sources())
    by_id, by_name, ambiguous = index_sources(sources)
    with store.connect() as conn:
        rows = [dict(row) for row in conn.execute(
            '''SELECT a.article_key, a.source_name, a.source_id, s.result_json
               FROM articles a LEFT JOIN analyses s USING(article_key)
               ORDER BY a.article_key'''
        )]
        counts = {
            'articles': len(rows), 'already_bound': 0, 'from_meta': 0,
            'from_name': 0, 'from_alias': 0, 'unresolved': 0, 'changed': 0,
        }
        unresolved = []
        updates = []
        for row in rows:
            current = str(row.get('source_id') or '').strip()
            resolved = current if current in by_id else ''
            origin = 'existing' if resolved else ''
            if not resolved and row.get('result_json'):
                try:
                    meta = (json.loads(row['result_json']) or {}).get('meta') or {}
                except (TypeError, ValueError):
                    meta = {}
                candidate = str(meta.get('source_id') or '').strip()
                if candidate in by_id:
                    resolved = candidate
                    origin = 'meta'
            if not resolved:
                key = normalise_name(row.get('source_name'))
                alias_id = EXPLICIT_SOURCE_ALIASES.get(key)
                if alias_id in by_id:
                    resolved = alias_id
                    origin = 'alias'
                else:
                    source = by_name.get(key)
                    if source is not None:
                        resolved = source.source_id
                        origin = 'name'
            if not resolved:
                counts['unresolved'] += 1
                unresolved.append({
                    'article_key': row['article_key'],
                    'source_name': row.get('source_name') or '',
                })
                continue
            if current and current == resolved:
                counts['already_bound'] += 1
                continue
            counts[{'meta': 'from_meta', 'name': 'from_name', 'alias': 'from_alias',
                    'existing': 'already_bound'}[origin]] += 1
            updates.append((resolved, row['article_key']))
        if not dry_run:
            for source_id, article_key in updates:
                conn.execute('UPDATE articles SET source_id=? WHERE article_key=?',
                             (source_id, article_key))
        counts['changed'] = len(updates)
        counts['ambiguous_names'] = sorted(ambiguous)
        counts['unresolved_names'] = sorted({item['source_name'] for item in unresolved
                                             if item['source_name']})
        counts['unresolved_examples'] = unresolved[:20]
        return counts

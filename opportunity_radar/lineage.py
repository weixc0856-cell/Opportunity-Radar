"""Source lineage: which organisation stands behind a source, and what that lets us claim.

A family is an organisation, not a domain and not a feed. The BBC's business and technology
feeds are one family; two different newspapers are two. Counting articles therefore says
nothing about corroboration until every article is traced to a family.

Three rules:

1. Independence is recorded, not inferred. A row must carry the basis it rests on and the
   registry row it came from; nothing is marked independent because its domain differs.
2. Unknown stays unknown. A source with no registry row keeps ``unknown`` and can never
   contribute to independent corroboration.
3. Following the same wire copy is not corroboration. Sources that belong to one
   ``syndication_group`` collapse into a single corroborating family even when their
   ownership differs - but only when that group is actually recorded.

The registry is a reviewed CSV in version control, so a change of judgement is a diff with
an author and a date, not a silent database edit.
"""
from __future__ import annotations

import csv
from pathlib import Path

DEFAULT_REGISTRY = 'config/source_lineage.csv'

FIELDS = ('source_id', 'source_family', 'lineage_kind', 'parent_source', 'syndication_group',
          'ownership_group', 'independence', 'basis', 'basis_source', 'reviewed_at', 'review_status')

LINEAGE_KINDS = ('official_statistics', 'first_party_announcement', 'news_organisation',
                 'community_forum', 'aggregator', 'other')
INDEPENDENCE = ('independent_primary', 'independent_secondary', 'syndicated', 'republished',
                'derived_from_same_source', 'unknown')
REVIEW_STATUS = ('declared', 'verified')
# Statuses that may contribute to corroboration. Everything else is evidence without a
# known provenance, and is never counted as independent.
CORROBORATING = ('independent_primary', 'independent_secondary')


def load(path=DEFAULT_REGISTRY):
    """Read the registry into {source_id: row}. A missing file is an empty registry, not an error."""
    file = Path(path)
    if not file.exists():
        return {}
    with file.open(encoding='utf-8-sig', newline='') as handle:
        return {row['source_id'].strip(): row for row in csv.DictReader(handle) if row.get('source_id')}


def validate(registry, known_source_ids=None):
    """Problems that make a row unusable. An empty list means every row may be applied."""
    problems = []
    for source_id, row in sorted(registry.items()):
        if known_source_ids is not None and source_id not in set(known_source_ids):
            problems.append(f'{source_id}: not a registered source')
        if not (row.get('source_family') or '').strip():
            problems.append(f'{source_id}: source_family is required')
        kind = (row.get('lineage_kind') or '').strip()
        if kind not in LINEAGE_KINDS:
            problems.append(f'{source_id}: unknown lineage_kind {kind!r}')
        status = (row.get('independence') or '').strip()
        if status not in INDEPENDENCE:
            problems.append(f'{source_id}: unknown independence {status!r}')
        if status != 'unknown' and not (row.get('basis') or '').strip():
            problems.append(f'{source_id}: independence {status!r} needs a recorded basis')
        if (row.get('review_status') or '').strip() not in REVIEW_STATUS:
            problems.append(f'{source_id}: unknown review_status {row.get("review_status")!r}')
        if not (row.get('basis_source') or '').strip():
            problems.append(f'{source_id}: basis_source is required')
    return problems


def apply(store, registry, source_ids=None):
    """Write lineage onto existing evidence rows. Returns what changed; never invents rows.

    `source_ids` may narrow the update to the sources this run actually produced.
    """
    applied = updated = 0
    by_status = {}
    unmapped = []
    with store.connect() as conn:
        for source_id, row in sorted(registry.items()):
            if source_ids is not None and source_id not in set(source_ids):
                continue
            family = (row.get('source_family') or '').strip()
            independence = (row.get('independence') or 'unknown').strip() or 'unknown'
            basis = (row.get('basis') or '').strip()
            group = (row.get('syndication_group') or '').strip()
            cur = conn.execute(
                'UPDATE evidences SET source_family=?, independence=?, lineage_basis=?, syndication_group=? '
                'WHERE source_id=? AND (source_family<>? OR independence<>? OR lineage_basis<>? OR syndication_group<>?)',
                (family, independence, basis, group, source_id, family, independence, basis, group))
            applied += 1
            updated += cur.rowcount
            by_status[independence] = by_status.get(independence, 0) + 1
        mapped = set(registry)
        for row in conn.execute('SELECT DISTINCT source_id FROM evidences'):
            if row[0] and row[0] not in mapped:
                unmapped.append(row[0])
    return {'sources_applied': applied, 'evidences_updated': updated,
            'independence_by_source': by_status, 'unmapped_sources': sorted(unmapped)}


def families_for(registry):
    """{family: [source_id, ...]} - the same organisation seen through several feeds."""
    out = {}
    for source_id, row in registry.items():
        out.setdefault((row.get('source_family') or '').strip(), []).append(source_id)
    return {family: sorted(ids) for family, ids in sorted(out.items()) if family}

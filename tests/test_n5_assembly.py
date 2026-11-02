"""N5 completeness gate and r2-v4 shadow claim assembly."""
import unittest

from opportunity_radar import (article_text, n4_normalization, n5_assembly,
                               numeric_candidates)


def setup(text, title='T'):
    article = article_text.build({'article_id': 'a1', 'source_id': 's1', 'title': title,
                                  'content': text, 'content_format': 'text'})
    return article.to_dict(), numeric_candidates.extract(article)


def find(n1, candidate_type):
    return next(candidate for candidate in n1['candidates']
                if candidate['candidate_type'] == candidate_type)


def interp(candidate, disposition='claim_value', subject='subject', predicate='measure',
           kind='fact', status='resolved', field=None, quote=None):
    return {'candidate_id': candidate['candidate_id'], 'disposition': disposition,
            'subject': subject, 'predicate': predicate, 'kind': kind, 'reason': '',
            'evidence_sentence_ids': [candidate['sentence_id']],
            'evidence_quote': candidate['raw_text'] if quote is None else quote,
            'evidence_start': candidate['start'], 'evidence_end': candidate['end'],
            'evidence_field': field or candidate['field'], 'status': status,
            'deviations': []}


def n2_output(document, items, status='success'):
    return {'node': 'N2', 'node_version': 'n2-v1', 'document_id': document['document_id'],
            'status': status, 'candidate_interpretations': items, 'statistics': {}}


def relationship(document, n1, values, relationship_type='change', periods=(),
                 baselines=(), comparison='unknown', status='resolved', suffix=''):
    first = values[0]
    return {'relationship_id': 'r_' + first['candidate_id'] + '_' + relationship_type + suffix,
            'relationship_type': relationship_type,
            'value_candidate_ids': [candidate['candidate_id'] for candidate in values],
            'baseline_candidate_ids': list(baselines),
            'period_candidate_ids': list(periods),
            'comparison_period_candidate_ids': [], 'denominator_candidate_ids': [],
            'related_expression_ids': [], 'direction': 'increase', 'comparison': comparison,
            'seasonality': 'unknown', 'revision': 'unknown', 'period_raw': '',
            'evidence_sentence_ids': [first['sentence_id']],
            'evidence_quote': first['raw_text'], 'evidence_start': first['start'],
            'evidence_end': first['end'], 'evidence_field': first['field'],
            'status': status, 'reason': '', 'deviations': []}


def n3_output(document, relationships, status='success'):
    return {'node': 'N3', 'node_version': 'n3-v1', 'document_id': document['document_id'],
            'status': status, 'relationships': relationships,
            'candidate_dispositions': [], 'statistics': {}}


def build(text, title='T', n2_status='success', relation_type='change', period=None,
          include_interpretation=True):
    document, n1 = setup(text, title)
    money = find(n1, 'currency') if any(c['candidate_type'] == 'currency'
                                        for c in n1['candidates']) else None
    items = []
    if money and include_interpretation:
        items.append(interp(money))
    n2 = n2_output(document, items, n2_status)
    relationships = []
    if money and relation_type:
        relationships.append(relationship(document, n1, [money], relation_type,
                                          periods=[period['candidate_id']] if period else []))
    n3 = n3_output(document, relationships)
    n4 = n4_normalization.normalize(document, n1, n2, n3)
    return document, n1, n2, n3, n4


class AcceptedClaimTests(unittest.TestCase):
    def test_money_claim_matches_r2v4_and_keeps_lineage(self):
        document, n1 = setup('The deficit was $92.8 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, [interp(money),
                                  interp(period, 'context_only', subject='', predicate='',
                                         kind='unknown')])
        n3 = n3_output(document, [relationship(document, n1, [money],
                                               periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(n5['status'], 'success')
        self.assertEqual(len(n5['claims']), 1)
        claim = n5['claims'][0]
        self.assertEqual((claim['subject'], claim['predicate'], claim['kind']),
                         ('subject', 'measure', 'fact'))
        self.assertEqual((claim['value_num'], claim['unit'], claim['scale'], claim['currency']),
                         (92.8, 'USD', 'billion', 'USD'))
        self.assertEqual(claim['period'], '2026')
        self.assertEqual(claim['quote'], '$92.8 billion')
        self.assertTrue(claim['claim_id'].startswith('c_'))
        self.assertEqual(claim['trace']['relationship_id'],
                         n3['relationships'][0]['relationship_id'])
        self.assertEqual(claim['trace']['n4_record_id'],
                         n4['normalized_records'][0]['record_id'])
        self.assertTrue(claim['trace']['candidate_ids'])
        self.assertTrue(n5['contract_validation']['valid'])
        dispositions = {item['candidate_id']: item for item in n5['candidate_dispositions']}
        self.assertEqual(dispositions[money['candidate_id']]['status'], 'claim_accepted')
        self.assertEqual(dispositions[period['candidate_id']]['status'], 'context_only')
        self.assertTrue(n5['coverage_statistics']['coverage_complete'])

    def test_context_and_non_claim_never_become_claims(self):
        document, n1 = setup('Revenue was $5 billion in 2026. See [12].')
        money = find(n1, 'currency')
        others = [candidate for candidate in n1['candidates']
                  if candidate['candidate_id'] != money['candidate_id']]
        items = [interp(money)] + [
            interp(candidate, 'non_claim' if candidate['candidate_type'] == 'identifier'
                  else 'context_only', subject='', predicate='', kind='unknown')
            for candidate in others]
        n2 = n2_output(document, items)
        n3 = n3_output(document, [relationship(document, n1, [money], 'level')])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(len(n5['claims']), 1)
        statuses = {item['candidate_id']: item['status']
                    for item in n5['candidate_dispositions']}
        for candidate in others:
            self.assertEqual(statuses[candidate['candidate_id']],
                             'non_claim' if candidate['candidate_type'] == 'identifier'
                             else 'context_only')

    def test_one_candidate_with_two_relationships_makes_two_distinct_claims(self):
        document, n1 = setup('Revenue was $105.6 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, [interp(money),
                                  interp(period, 'context_only', subject='', predicate='',
                                         kind='unknown')])
        change = relationship(document, n1, [money], 'change',
                              periods=[period['candidate_id']])
        level = relationship(document, n1, [money], 'level',
                             periods=[period['candidate_id']], suffix='_level')
        n3 = n3_output(document, [change, level])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        # The r2-v4 fields are identical; relationship_type is lineage, so this is one claim
        # with both relationships preserved in its trace.
        self.assertEqual(len(n5['claims']), 1)
        claim = n5['claims'][0]
        self.assertEqual(claim['value_num'], 105.6)
        self.assertEqual(set(claim['trace']['relationship_types']), {'change', 'level'})
        self.assertEqual(len(claim['trace']['relationship_ids']), 2)
        self.assertEqual(len(claim['trace']['n4_record_ids']), 2)
        self.assertIn(claim['trace']['evidence_field'], ('body',))
        self.assertIsNotNone(claim['trace']['evidence_start'])
        self.assertEqual(len(claim['trace']['evidence_items']), 2)
        self.assertEqual(n5['coverage_statistics']['accepted_candidates'], 1)
        self.assertEqual(n5['coverage_statistics']['raw_assembled_claims'], 2)
        self.assertEqual(n5['coverage_statistics']['assembled_claims'], 1)
        self.assertEqual(n5['coverage_statistics']['duplicate_claims'], 1)

    def test_missing_period_is_not_invented(self):
        document, n1, n2, n3, n4 = build('Revenue was $5 billion.', relation_type='change')
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        claim = n5['claims'][0]
        self.assertEqual(claim['period'], '')
        self.assertEqual(claim['trace']['period_candidate_ids'], [])
        self.assertIn('period_missing',
                      [deviation['reason'] for deviation in claim['deviations']])


class RejectionTests(unittest.TestCase):
    def test_title_only_evidence_is_rejected(self):
        document, n1 = setup('The company reported results.', title='Intel shares plunge 20%')
        title_number = next(candidate for candidate in n1['candidates']
                            if candidate['field'] == 'title')
        n2 = n2_output(document, [interp(title_number, field='title')])
        n3 = n3_output(document, [relationship(document, n1, [title_number], 'level')])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(n5['claims'], [])
        self.assertIn('title_only_evidence',
                      [item['reason'] for item in n5['rejected_items']])
        disposition = next(item for item in n5['candidate_dispositions']
                           if item['candidate_id'] == title_number['candidate_id'])
        self.assertEqual(disposition['status'], 'rejected')

    def test_a_claim_without_predicate_is_rejected(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, [interp(money, predicate='')])
        n3 = n3_output(document, [relationship(document, n1, [money], 'level',
                                               periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(n5['claims'], [])
        self.assertIn('contract_invalid',
                      [item['reason'] for item in n5['rejected_items']])

    def test_duplicate_relationships_produce_one_claim(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, [interp(money)])
        first = relationship(document, n1, [money], 'level', periods=[period['candidate_id']])
        second = relationship(document, n1, [money], 'level',
                              periods=[period['candidate_id']], suffix='_dup')
        n3 = n3_output(document, [first, second])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(len(n5['claims']), 1)
        self.assertEqual(n5['coverage_statistics']['duplicate_claims'], 1)
        self.assertEqual(n5['duplicates'][0]['reason'], 'semantic_duplicate_merged')
        self.assertNotEqual(n5['duplicates'][0]['claim_id'],
                            n5['duplicates'][0]['duplicate_of'])
        self.assertNotIn('duplicate_claim',
                         [item['reason'] for item in n5['rejected_items']])

    def test_unsupported_unit_does_not_generate_a_claim(self):
        document, n1 = setup('The device measured 3 gizmos in 2026.')
        value, period = find(n1, 'scalar'), find(n1, 'period')
        value['unit'] = 'gizmos'
        value['unit_family'] = 'unknown'
        n2 = n2_output(document, [interp(value)])
        n3 = n3_output(document, [relationship(document, n1, [value], 'level',
                                               periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(n5['claims'], [])
        disposition = next(item for item in n5['candidate_dispositions']
                           if item['candidate_id'] == value['candidate_id'])
        self.assertEqual(disposition['status'], 'normalization_failed')
        self.assertEqual(disposition['reason'], 'unsupported_unit')


class PartialAndBlockedTests(unittest.TestCase):
    def test_n2_partial_keeps_valid_claims_and_lists_unresolved(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, [interp(money), interp(period, 'context_only',
                                                        subject='', predicate='',
                                                        kind='unknown')],
                       status='partial')
        n3 = n3_output(document, [relationship(document, n1, [money], 'level',
                                               periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(len(n5['claims']), 1)
        self.assertEqual(n5['status'], 'success')

    def test_unresolved_n2_candidate_is_not_a_claim(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, [interp(money, status='unresolved')])
        n3 = n3_output(document, [])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(n5['claims'], [])
        disposition = next(item for item in n5['candidate_dispositions']
                           if item['candidate_id'] == money['candidate_id'])
        self.assertEqual(disposition['status'], 'unresolved')
        self.assertEqual(n5['status'], 'partial')

    def test_n2_failure_blocks_assembly(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        money = find(n1, 'currency')
        n2 = n2_output(document, [interp(money)], status='failed')
        n3 = n3_output(document, [])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(n5['status'], 'blocked')
        self.assertEqual(n5['claims'], [])

    def test_empty_candidates_are_a_valid_success(self):
        document, n1 = setup('Nothing numeric here.')
        n2 = n2_output(document, [])
        n3 = n3_output(document, [])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(n5['status'], 'success')
        self.assertEqual(n5['claims'], [])
        self.assertTrue(n5['coverage_statistics']['coverage_complete'])


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_same_claim_ids(self):
        document, n1, n2, n3, n4 = build('Revenue was $5 billion in 2026.')
        first = n5_assembly.assemble(document, n1, n2, n3, n4)
        second = n5_assembly.assemble(document, n1, n2, n3, n4)
        self.assertEqual(first['claims'], second['claims'])
        self.assertEqual(first['output_hash'], second['output_hash'])

    def test_n5_hash_follows_n4(self):
        document, n1, n2, n3, n4 = build('Revenue was $5 billion in 2026.')
        first = n5_assembly.assemble(document, n1, n2, n3, n4)
        changed = dict(n4, normalized_records=[dict(record, value=6.0)
                                               for record in n4['normalized_records']])
        second = n5_assembly.assemble(document, n1, n2, n3, changed)
        self.assertNotEqual(first['input_hash'], second['input_hash'])
        self.assertNotEqual(first['claims'][0]['claim_id'],
                            second['claims'][0]['claim_id'])


class SemanticMergeTests(unittest.TestCase):
    def build(self, text):
        document, n1 = setup(text)
        money = [candidate for candidate in n1['candidates']
                 if candidate['candidate_type'] == 'currency']
        periods = [candidate for candidate in n1['candidates']
                   if candidate['candidate_type'] in ('date', 'period')]
        n2 = n2_output(document, [interp(candidate) for candidate in money]
                       + [interp(candidate, 'context_only', subject='', predicate='',
                                 kind='unknown') for candidate in periods])
        return document, n1, money, periods, n2

    def assemble(self, document, n1, n2, relationships):
        n3 = n3_output(document, relationships)
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        return n5_assembly.assemble(document, n1, n2, n3, n4)

    def test_identical_claims_merge_and_keep_all_evidence(self):
        document, n1, money, periods, n2 = self.build(
            'Revenue was $5 billion in 2026. Revenue was $5 billion in 2026.')
        first = relationship(document, n1, [money[0]], 'level',
                             periods=[periods[0]['candidate_id']])
        second = relationship(document, n1, [money[1]], 'level',
                              periods=[periods[0]['candidate_id']], suffix='_second')
        n5 = self.assemble(document, n1, n2, [first, second])
        self.assertEqual(len(n5['claims']), 1)
        claim = n5['claims'][0]
        self.assertEqual(len(claim['trace']['merged_claim_ids']), 2)
        self.assertEqual(len(claim['trace']['evidence_items']), 2)
        self.assertEqual(len(claim['trace']['relationship_ids']), 2)
        self.assertEqual(n5['coverage_statistics']['raw_assembled_claims'], 2)
        self.assertEqual(n5['coverage_statistics']['assembled_claims'], 1)
        self.assertEqual(n5['coverage_statistics']['duplicate_claims'], 1)
        self.assertEqual(n5['duplicates'][0]['reason'], 'semantic_duplicate_merged')

    def test_the_same_number_in_different_periods_is_not_merged(self):
        document, n1, money, periods, n2 = self.build(
            'Revenue was $5 billion in 2025. Revenue was $5 billion in 2026.')
        first = relationship(document, n1, [money[0]], 'level',
                             periods=[periods[0]['candidate_id']])
        second = relationship(document, n1, [money[1]], 'level',
                              periods=[periods[1]['candidate_id']], suffix='_second')
        n5 = self.assemble(document, n1, n2, [first, second])
        self.assertEqual(len(n5['claims']), 2)
        self.assertEqual({claim['period'] for claim in n5['claims']}, {'2025', '2026'})
        self.assertEqual(n5['coverage_statistics']['duplicate_claims'], 0)

    def test_opposite_directions_are_not_merged(self):
        document, n1, money, periods, n2 = self.build(
            'Revenue was $5 billion in 2026. Revenue was $5 billion in 2026.')
        first = relationship(document, n1, [money[0]], 'level',
                             periods=[periods[0]['candidate_id']])
        second = relationship(document, n1, [money[1]], 'level',
                              periods=[periods[0]['candidate_id']], suffix='_second')
        second['direction'] = 'decrease'
        n5 = self.assemble(document, n1, n2, [first, second])
        self.assertEqual(len(n5['claims']), 2)
        self.assertEqual(n5['coverage_statistics']['duplicate_claims'], 0)
        self.assertEqual(n5['coverage_statistics']['direction_conflicts'], 1)
        self.assertEqual(n5['merge_conflicts'][0]['reason'], 'direction_conflict')



if __name__ == '__main__':
    unittest.main()

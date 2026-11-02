"""N4 deterministic normalization: value, unit, scale, currency, period and failure states."""
import unittest

from opportunity_radar import article_text, n4_normalization, numeric_candidates


def setup(text):
    article = article_text.build({'article_id': 'a1', 'source_id': 's1', 'title': 'T',
                                  'content': text, 'content_format': 'text'})
    return article.to_dict(), numeric_candidates.extract(article)


def find(n1, candidate_type):
    return next(candidate for candidate in n1['candidates']
                if candidate['candidate_type'] == candidate_type)


def interp(candidate, disposition='claim_value', subject='subject', predicate='measure',
           kind='fact', status='resolved'):
    return {'candidate_id': candidate['candidate_id'], 'disposition': disposition,
            'subject': subject, 'predicate': predicate, 'kind': kind, 'reason': '',
            'evidence_sentence_ids': [candidate['sentence_id']],
            'evidence_quote': candidate['raw_text'],
            'evidence_start': candidate['start'], 'evidence_end': candidate['end'],
            'evidence_field': candidate['field'], 'status': status, 'deviations': []}


def n2_output(document, n1, claims=('currency',), context=('period',)):
    items = []
    for candidate in n1['candidates']:
        kind = candidate['candidate_type']
        if kind in claims:
            items.append(interp(candidate))
        elif kind in context:
            items.append(interp(candidate, 'context_only', subject='', predicate='',
                                kind='unknown'))
        else:
            items.append(interp(candidate, 'non_claim', subject='', predicate='', kind='unknown'))
    return {'node': 'N2', 'node_version': 'n2-v1', 'document_id': document['document_id'],
            'status': 'success', 'candidate_interpretations': items, 'statistics': {}}


def relationship(document, n1, values, relationship_type='change', periods=(),
                 baselines=(), comparison='unknown', status='resolved'):
    first = values[0]
    return {'relationship_id': 'r_' + first['candidate_id'] + '_' + relationship_type,
            'relationship_type': relationship_type,
            'value_candidate_ids': [candidate['candidate_id'] for candidate in values],
            'baseline_candidate_ids': list(baselines),
            'period_candidate_ids': list(periods),
            'comparison_period_candidate_ids': [], 'denominator_candidate_ids': [],
            'related_expression_ids': [], 'direction': 'increase',
            'comparison': comparison, 'seasonality': 'unknown', 'revision': 'unknown',
            'period_raw': '', 'evidence_sentence_ids': [first['sentence_id']],
            'evidence_quote': first['raw_text'], 'evidence_start': first['start'],
            'evidence_end': first['end'], 'evidence_field': first['field'],
            'status': status, 'reason': '', 'deviations': []}


def n3_output(document, relationships):
    return {'node': 'N3', 'node_version': 'n3-v1', 'document_id': document['document_id'],
            'status': 'success', 'relationships': relationships,
            'candidate_dispositions': [], 'statistics': {}}


def record_for(n4, candidate):
    return next(item for item in n4['normalized_records']
                if item['candidate_id'] == candidate['candidate_id'])


class MoneyTests(unittest.TestCase):
    def test_dollar_amount_keeps_value_scale_and_currency_apart(self):
        document, n1 = setup('The deficit was $92.8 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(document, n1, [money],
                                               periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        record = record_for(n4, money)
        self.assertEqual((record['value'], record['unit'], record['scale'], record['currency']),
                         (92.8, 'USD', 'billion', 'USD'))
        self.assertEqual(record['unit_string'], 'USD billion')
        self.assertEqual(record['period'], '2026')
        self.assertEqual(record['status'], 'normalized')
        self.assertEqual(n4['status'], 'success')

    def test_currency_code_amount(self):
        document, n1 = setup('Exports were USD 12.8 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(document, n1, [money],
                                               periods=[period['candidate_id']])])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), money)
        self.assertEqual((record['value'], record['unit'], record['scale'], record['currency']),
                         (12.8, 'USD', 'billion', 'USD'))
        self.assertEqual(record['unit_string'], 'USD billion')

    def test_count_quantity_keeps_the_noun_and_scale(self):
        document, n1 = setup('The company sold 5 million vehicles in 2026.')
        quantity, period = find(n1, 'quantity'), find(n1, 'period')
        n2 = n2_output(document, n1, claims=('quantity',))
        n3 = n3_output(document, [relationship(document, n1, [quantity], 'level',
                                               periods=[period['candidate_id']])])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), quantity)
        self.assertEqual((record['value'], record['unit'], record['scale']),
                         (5.0, 'vehicles', 'million'))
        self.assertEqual(record['unit_string'], 'million vehicles')
        self.assertEqual(record['unit_family'], 'count')
        self.assertEqual(record['status'], 'normalized')


class PercentTests(unittest.TestCase):
    def test_percent_and_percentage_point_stay_distinct(self):
        document, n1 = setup('Output rose 2 percent and prices rose 2 percentage points in 2026.')
        period = find(n1, 'period')
        n2 = n2_output(document, n1, claims=('percentage', 'percentage_point'))
        values = [candidate for candidate in n1['candidates']
                  if candidate['candidate_type'] in ('percentage', 'percentage_point')]
        n3 = n3_output(document, [relationship(document, n1, [value], 'change',
                                               periods=[period['candidate_id']])
                                  for value in values])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        records = [record_for(n4, value) for value in values]
        self.assertEqual({record['unit'] for record in records}, {'%', 'pp'})
        self.assertTrue(all(record['scale'] == '' for record in records))

    def test_negative_percentage_keeps_its_sign(self):
        document, n1 = setup('Output fell -2.5% in 2026.')
        value, period = find(n1, 'percentage'), find(n1, 'period')
        n2 = n2_output(document, n1, claims=('percentage',))
        n3 = n3_output(document, [relationship(document, n1, [value],
                                               periods=[period['candidate_id']])])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['value'], -2.5)
        self.assertEqual(record['status'], 'normalized')

    def test_parenthesized_number_is_normalized_with_a_visible_caveat(self):
        document, n1 = setup('The rate was (0.5%).')
        value = find(n1, 'percentage')
        n2 = n2_output(document, n1, claims=('percentage',), context=())
        n3 = n3_output(document, [relationship(document, n1, [value], 'level')])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['value'], 0.5)
        self.assertEqual(record['status'], 'normalized')
        self.assertIn('parenthesized_sign_not_inferred',
                      [deviation['reason'] for deviation in record['deviations']])


class FailureStateTests(unittest.TestCase):
    def test_range_is_not_assemblable(self):
        document, n1 = setup('The range was 2.1–2.5% in 2026.')
        values = [candidate for candidate in n1['candidates']
                  if candidate['candidate_type'] in ('scalar', 'percentage')]
        period = find(n1, 'period')
        n2 = n2_output(document, n1, claims=('scalar', 'percentage'))
        n3 = n3_output(document, [relationship(document, n1, values, 'range',
                                               periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        statuses = {record_for(n4, value)['status'] for value in values}
        self.assertEqual(statuses, {'invalid_relationship'})
        self.assertEqual(n4['status'], 'failed')

    def test_unknown_unit_is_not_normalized(self):
        document, n1 = setup('The device measured 3 gizmos in 2026.')
        value, period = find(n1, 'scalar'), find(n1, 'period')
        value['unit'] = 'gizmos'
        value['unit_family'] = 'unknown'
        n2 = n2_output(document, n1, claims=('scalar',))
        n3 = n3_output(document, [relationship(document, n1, [value], 'level',
                                               periods=[period['candidate_id']])])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['status'], 'unsupported_unit')
        self.assertIn('unknown_unit', record['reason'])

    def test_currency_conflict_is_ambiguous(self):
        document, n1 = setup('The amount was $5 billion in 2026.')
        value, period = find(n1, 'currency'), find(n1, 'period')
        value['flags'] = ['currency_conflict']
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(document, n1, [value], 'level',
                                               periods=[period['candidate_id']])])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['status'], 'ambiguous_numeric')

    def test_missing_period_is_kept_missing(self):
        document, n1 = setup('Revenue was $5 billion.')
        value = find(n1, 'currency')
        n2 = n2_output(document, n1, context=())
        n3 = n3_output(document, [relationship(document, n1, [value], 'change')])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['period'], '')
        self.assertEqual(record['status'], 'partially_normalized')
        self.assertIn('period_missing',
                      [deviation['reason'] for deviation in record['deviations']])

    def test_missing_baseline_is_kept_missing(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        value, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(document, n1, [value], 'comparison',
                                               periods=[period['candidate_id']])])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['baseline'], [])
        self.assertEqual(record['status'], 'partially_normalized')
        self.assertIn('baseline_missing',
                      [deviation['reason'] for deviation in record['deviations']])

    def test_unknown_relationship_is_invalid(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        value, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(document, n1, [value], 'unknown',
                                               periods=[period['candidate_id']])])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['status'], 'invalid_relationship')

    def test_a_claim_value_without_a_relationship_is_missing_semantics(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        value = find(n1, 'currency')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [])
        record = record_for(n4_normalization.normalize(document, n1, n2, n3), value)
        self.assertEqual(record['status'], 'missing_semantics')
        self.assertEqual(record['reason'], 'no_relationship_value')

    def test_n2_failure_makes_n4_fail(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        n2 = n2_output(document, n1)
        n2['status'] = 'failed'
        n3 = n3_output(document, [])
        self.assertEqual(n4_normalization.normalize(document, n1, n2, n3)['status'], 'failed')


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_give_the_same_records_and_ids(self):
        document, n1 = setup('The deficit was $92.8 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(document, n1, [money],
                                               periods=[period['candidate_id']])])
        first = n4_normalization.normalize(document, n1, n2, n3)
        second = n4_normalization.normalize(document, n1, n2, n3)
        self.assertEqual(first['normalized_records'], second['normalized_records'])
        self.assertEqual(first['output_hash'], second['output_hash'])

    def test_hash_changes_when_n3_changes(self):
        document, n1 = setup('The deficit was $92.8 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        first = n4_normalization.normalize(
            document, n1, n2, n3_output(document, [relationship(
                document, n1, [money], periods=[period['candidate_id']])]))
        second = n4_normalization.normalize(
            document, n1, n2, n3_output(document, [relationship(
                document, n1, [money], 'level', periods=[period['candidate_id']])]))
        self.assertNotEqual(first['input_hash'], second['input_hash'])
        self.assertNotEqual(first['normalized_records'][0]['record_id'],
                            second['normalized_records'][0]['record_id'])


class PeriodEvidenceTests(unittest.TestCase):
    def test_a_full_period_keeps_its_source_locator(self):
        document, n1 = setup('Revenue was $5 billion in 2026.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(document, n1, [money],
                                               periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        record = record_for(n4, money)
        self.assertEqual(record['period'], '2026')
        self.assertEqual(record['period_evidence_quote'], '2026')
        self.assertEqual((record['period_evidence_start'], record['period_evidence_end']),
                         (period['start'], period['end']))
        self.assertEqual(record['period_evidence_field'], period['field'])
        self.assertEqual(record['period_source'], 'n3_period_candidate')

    def test_a_month_without_a_year_keeps_raw_text_and_locator(self):
        document, n1 = setup('Revenue was $5 billion in September.')
        money, period = find(n1, 'currency'), find(n1, 'period')
        n2 = n2_output(document, n1)
        n3 = n3_output(document, [relationship(
            document, n1, [money], 'change', periods=[period['candidate_id']])])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        record = record_for(n4, money)
        self.assertEqual((record['period'], record['period_raw']), ('', 'september'))
        self.assertEqual(record['period_candidate_ids'], [period['candidate_id']])
        self.assertEqual(record['period_evidence_quote'], 'september')
        self.assertEqual(record['period_evidence_start'], period['start'])
        self.assertEqual(record['period_evidence_field'], 'body')
        self.assertIn('period_missing',
                      [deviation['reason'] for deviation in record['deviations']])
        self.assertEqual(record['status'], 'partially_normalized')

    def test_a_relationship_period_without_a_candidate_keeps_raw_text(self):
        document, n1 = setup('Revenue was $5 billion in September.')
        money = find(n1, 'currency')
        n2 = n2_output(document, n1)
        item = relationship(document, n1, [money], 'change')
        item['period_raw'] = 'september'
        item['period_evidence_quote'] = 'september'
        item['period_evidence_start'] = money['start']
        item['period_evidence_end'] = money['end']
        item['period_evidence_field'] = 'body'
        item['period_source'] = 'model'
        n3 = n3_output(document, [item])
        n4 = n4_normalization.normalize(document, n1, n2, n3)
        record = record_for(n4, money)
        self.assertEqual((record['period'], record['period_raw']), ('', 'september'))
        self.assertEqual(record['period_candidate_ids'], [])
        self.assertEqual(record['period_evidence_quote'], 'september')
        self.assertEqual(record['period_source'], 'model')
        self.assertIn('period_missing',
                      [deviation['reason'] for deviation in record['deviations']])



if __name__ == '__main__':
    unittest.main()

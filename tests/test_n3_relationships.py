"""N3 program validation: scoping, enums, evidence, dispositions and comparison guards.

The model is replaced by a deterministic runner. The real-model output is recorded in the
Batch 9 acceptance document; these tests prove the program never accepts a relationship that
references the wrong atom, an unstated comparison, or a non-claim as a value.
"""
import unittest
from unittest.mock import patch

from opportunity_radar import article_text, n3_relationships, numeric_candidates

TEXT = ('Personal income increased $54.5 billion (0.2 percent at a monthly rate) in '
        'September. Personal saving was $911.1 billion.')
TEXT_ID = 'See [12] for the table. Revenue was $5 billion in 2025.'
MODEL = {'provider': 'fake', 'model_id': 'fake', 'model_fingerprint': 'unknown',
         'generation_params': {'temperature': 0.0, 'max_tokens': 600}}


def setup(text=TEXT):
    article = article_text.build({'article_id': 'a1', 'source_id': 's1', 'title': 'T',
                                  'content': text, 'content_format': 'text'})
    return article.to_dict(), numeric_candidates.extract(article)


def candidate_by_id(document, n1, candidate_id):
    return next(candidate for candidate in n1['candidates']
                if candidate['candidate_id'] == candidate_id)


def make_n2(document, n1, claims=('currency', 'percentage'), status='success'):
    items = []
    for candidate in n1['candidates']:
        kind = candidate['candidate_type']
        if kind in claims:
            items.append({
                'candidate_id': candidate['candidate_id'], 'disposition': 'claim_value',
                'subject': 'personal income', 'predicate': 'personal_income', 'kind': 'fact',
                'reason': '', 'evidence_sentence_ids': [candidate['sentence_id']],
                'evidence_quote': candidate['raw_text'], 'status': 'resolved',
                'deviations': []})
        elif kind in ('date', 'period'):
            items.append({
                'candidate_id': candidate['candidate_id'], 'disposition': 'context_only',
                'subject': '', 'predicate': '', 'kind': 'unknown', 'reason': '',
                'evidence_sentence_ids': [candidate['sentence_id']],
                'evidence_quote': candidate['raw_text'], 'status': 'resolved',
                'deviations': []})
        else:
            items.append({
                'candidate_id': candidate['candidate_id'], 'disposition': 'non_claim',
                'subject': '', 'predicate': '', 'kind': 'unknown', 'reason': '',
                'evidence_sentence_ids': [candidate['sentence_id']],
                'evidence_quote': candidate['raw_text'], 'status': 'resolved',
                'deviations': []})
    return {'node': 'N2', 'node_version': 'n2-v1', 'document_id': document['document_id'],
            'status': status, 'input_hash': 'n2hash', 'seconds': 1.0, 'batches': [],
            'candidate_interpretations': items,
            'statistics': {'claim_value_count': sum(1 for item in items
                                                    if item['disposition'] == 'claim_value')}}


class Runner:
    def __init__(self, respond):
        self.respond = respond
        self.calls = 0
        self.payloads = []

    def run(self, payload):
        self.calls += 1
        self.payloads.append(payload)
        return self.respond(payload)


def relationship(candidate, relationship_type='level', comparison='level',
                 direction='not_applicable', **extra):
    item = {
        'relationship_type': relationship_type,
        'value_candidate_ids': [candidate['candidate_id']],
        'baseline_candidate_ids': [],
        'period_candidate_ids': [],
        'comparison_period_candidate_ids': [],
        'denominator_candidate_ids': [],
        'related_expression_ids': [],
        'direction': direction,
        'comparison': comparison,
        'seasonality': 'unknown',
        'revision': 'unknown',
        'period_raw': '',
        'evidence_sentence_ids': [candidate['sentence_id']],
        'evidence_quote': candidate['raw_text'],
        'status': 'resolved',
        'reason': 'test',
    }
    item.update(extra)
    return item


def respond_one_level(payload):
    relationships, dispositions = [], []
    for index, candidate_id in enumerate(payload['claim_value_ids']):
        candidate = next(item for item in payload['candidates']
                         if item['candidate_id'] == candidate_id)
        relationships.append(relationship(candidate))
        dispositions.append({'candidate_id': candidate_id, 'status': 'assigned',
                             'relationship_indexes': [index], 'reason': ''})
    return {'status': 'ok', 'parsed': {'relationships': relationships,
                                       'candidate_dispositions': dispositions}, 'attempts': 1}


class BlockingTests(unittest.TestCase):
    def test_n2_failure_blocks_without_a_model_call(self):
        document, n1 = setup()
        n2 = make_n2(document, n1, status='failed')
        runner = Runner(respond_one_level)
        result = n3_relationships.run(document, n1, n2, runner, MODEL)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(runner.calls, 0)

    def test_no_claim_values_means_no_model_call(self):
        document, n1 = setup()
        n2 = make_n2(document, n1, claims=())
        runner = Runner(respond_one_level)
        result = n3_relationships.run(document, n1, n2, runner, MODEL)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(runner.calls, 0)
        self.assertEqual(result['relationships'], [])


class AssignmentTests(unittest.TestCase):
    def test_every_claim_value_is_assigned(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        result = n3_relationships.run(document, n1, n2, Runner(respond_one_level), MODEL)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(result['relationships']),
                         result['statistics']['input_claim_value_count'])
        self.assertEqual(result['statistics']['assigned_count'],
                         result['statistics']['input_claim_value_count'])
        self.assertTrue(result['statistics']['coverage_complete'])
        self.assertEqual(result['statistics']['evidence_located_relationships'],
                         result['statistics']['relationship_count'])

    def test_a_claim_without_a_relationship_is_unresolved(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        first = next(candidate for candidate in n1['candidates']
                     if candidate['candidate_type'] == 'currency')

        def respond(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == first['candidate_id'])
            return {'status': 'ok', 'parsed': {
                'relationships': [relationship(candidate)],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        unresolved = [item for item in result['candidate_dispositions']
                      if item['status'] == 'unresolved']
        self.assertEqual(len(unresolved), result['statistics']['input_claim_value_count'] - 1)
        self.assertEqual(result['status'], 'partial')

    def test_multiple_relationships_for_one_candidate(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        first = next(candidate for candidate in n1['candidates']
                     if candidate['candidate_type'] == 'currency')

        def respond(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == first['candidate_id'])
            relationships = [relationship(candidate), relationship(
                candidate, relationship_type='comparison', comparison='unknown')]
            return {'status': 'ok', 'parsed': {
                'relationships': relationships,
                'candidate_dispositions': [{'candidate_id': first['candidate_id'],
                                            'status': 'assigned',
                                            'relationship_indexes': [0, 1],
                                            'reason': ''}]}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        disposition = next(item for item in result['candidate_dispositions']
                           if item['candidate_id'] == first['candidate_id'])
        self.assertEqual(disposition['status'], 'assigned')
        self.assertEqual(disposition['relationship_indexes'], [0, 1])
        self.assertEqual(result['statistics']['relationship_count'], 2)


class ReferenceTests(unittest.TestCase):
    def test_a_non_claim_cannot_be_a_value(self):
        document, n1 = setup(TEXT_ID)
        n2 = make_n2(document, n1)
        citation = next(candidate for candidate in n1['candidates']
                        if candidate['candidate_type'] == 'identifier')

        def respond(payload):
            return {'status': 'ok', 'parsed': {
                'relationships': [{
                    'relationship_type': 'level', 'value_candidate_ids': [
                        citation['candidate_id']], 'direction': 'not_applicable',
                    'comparison': 'level', 'evidence_sentence_ids': [
                        citation['sentence_id']], 'evidence_quote': citation['raw_text'],
                    'status': 'resolved', 'reason': ''}],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        self.assertEqual(result['relationships'], [])
        self.assertTrue(any(item['status'] == 'unresolved'
                            for item in result['candidate_dispositions']))

    def test_an_unknown_candidate_is_dropped(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)

        def respond(payload):
            item = relationship(next(candidate for candidate in payload['candidates']
                                     if candidate['candidate_id']
                                     in payload['claim_value_ids']))
            item['value_candidate_ids'] = ['c-missing'] + item['value_candidate_ids']
            return {'status': 'ok', 'parsed': {
                'relationships': [item], 'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        self.assertNotIn('c-missing', result['relationships'][0]['value_candidate_ids'])

    def test_empty_value_ids_drop_the_relationship(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)

        def respond(payload):
            return {'status': 'ok', 'parsed': {
                'relationships': [{'relationship_type': 'level', 'value_candidate_ids': [],
                                   'direction': 'not_applicable', 'comparison': 'level',
                                   'evidence_sentence_ids': [], 'evidence_quote': '',
                                   'status': 'resolved', 'reason': ''}],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        self.assertEqual(result['relationships'], [])


class ComparisonGuardTests(unittest.TestCase):
    def test_monthly_rate_is_rejected_for_the_currency_when_it_belongs_to_the_percentage(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        currency = next(candidate for candidate in n1['candidates']
                        if candidate['candidate_type'] == 'currency')

        def respond(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == currency['candidate_id'])
            return {'status': 'ok', 'parsed': {
                'relationships': [relationship(candidate, 'change', 'monthly_rate',
                                               'increase')],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        item = result['relationships'][0]
        self.assertEqual(item['comparison'], 'unknown')
        self.assertTrue(any(dev['reason'] == 'attached_to_other_candidate'
                            for dev in item['deviations']))

    def test_a_change_cannot_use_comparison_level(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        currency = next(candidate for candidate in n1['candidates']
                        if candidate['candidate_type'] == 'currency')

        def respond(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == currency['candidate_id'])
            return {'status': 'ok', 'parsed': {
                'relationships': [relationship(candidate, 'change', 'level', 'increase')],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        item = result['relationships'][0]
        self.assertEqual(item['comparison'], 'unknown')
        self.assertTrue(any(dev['reason'] == 'change_cannot_be_level'
                            for dev in item['deviations']))

    def test_an_unstated_annual_rate_is_rejected(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        percentage = next(candidate for candidate in n1['candidates']
                          if candidate['candidate_type'] == 'percentage')

        def respond(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == percentage['candidate_id'])
            return {'status': 'ok', 'parsed': {
                'relationships': [relationship(candidate, 'rate', 'annual_rate')],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        item = result['relationships'][0]
        self.assertEqual(item['comparison'], 'level')
        self.assertTrue(any(dev['reason'] == 'not_stated' for dev in item['deviations']))

    def test_revision_and_seasonality_are_kept_only_when_stated(self):
        document, n1 = setup('Output was 3.4 percent, preliminary and seasonally adjusted.')
        n2 = make_n2(document, n1)
        percentage = next(candidate for candidate in n1['candidates']
                          if candidate['candidate_type'] == 'percentage')

        def stated(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == percentage['candidate_id'])
            return {'status': 'ok', 'parsed': {
                'relationships': [relationship(candidate, revision='preliminary',
                                               seasonality='seasonally_adjusted')],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(stated), MODEL)
        item = result['relationships'][0]
        self.assertEqual((item['revision'], item['seasonality']),
                         ('preliminary', 'seasonally_adjusted'))

        document, n1 = setup()
        n2 = make_n2(document, n1)
        currency = next(candidate for candidate in n1['candidates']
                        if candidate['candidate_type'] == 'currency')

        def unstated(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == currency['candidate_id'])
            return {'status': 'ok', 'parsed': {
                'relationships': [relationship(candidate, revision='preliminary',
                                               seasonality='seasonally_adjusted')],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(unstated), MODEL)
        item = result['relationships'][0]
        self.assertEqual((item['revision'], item['seasonality']), ('unknown', 'unknown'))
        reasons = {dev['reason'] for dev in item['deviations']}
        self.assertIn('not_stated', reasons)

    def test_a_period_not_in_the_context_is_cleared(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        currency = next(candidate for candidate in n1['candidates']
                        if candidate['candidate_type'] == 'currency')

        def respond(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == currency['candidate_id'])
            return {'status': 'ok', 'parsed': {
                'relationships': [relationship(candidate, period_raw='december 1999')],
                'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        item = result['relationships'][0]
        self.assertEqual(item['period_raw'], '')
        self.assertTrue(any(dev['reason'] == 'not_in_context'
                            for dev in item['deviations']))

    def test_a_quote_not_in_the_sentences_makes_the_relationship_unresolved(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        currency = next(candidate for candidate in n1['candidates']
                        if candidate['candidate_type'] == 'currency')

        def respond(payload):
            candidate = next(item for item in payload['candidates']
                             if item['candidate_id'] == currency['candidate_id'])
            item = relationship(candidate)
            item['evidence_quote'] = 'not in the text'
            return {'status': 'ok', 'parsed': {
                'relationships': [item], 'candidate_dispositions': []}, 'attempts': 1}

        result = n3_relationships.run(document, n1, n2, Runner(respond), MODEL)
        item = result['relationships'][0]
        self.assertEqual(item['status'], 'unresolved')
        self.assertIn('not_located', [dev['reason'] for dev in item['deviations']])


class HashTests(unittest.TestCase):
    def test_hash_ignores_timing_but_follows_n2_content(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        first = n3_relationships.input_hash(document, n1, n2, MODEL)
        noisy = dict(n2, seconds=999.0, batches=[{'seconds': 5, 'attempts': 2}])
        self.assertEqual(first, n3_relationships.input_hash(document, n1, noisy, MODEL))
        changed = dict(n2, candidate_interpretations=[
            dict(item, subject='different') for item in n2['candidate_interpretations']])
        self.assertNotEqual(first, n3_relationships.input_hash(document, n1, changed, MODEL))

    def test_prompt_and_schema_changes_invalidate_the_hash(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        first = n3_relationships.input_hash(document, n1, n2, MODEL)
        with patch.object(n3_relationships, 'SYSTEM_PROMPT',
                          n3_relationships.SYSTEM_PROMPT + ' extra'):
            self.assertNotEqual(first, n3_relationships.input_hash(document, n1, n2, MODEL))
        with patch.object(n3_relationships, 'SCHEMA', dict(n3_relationships.SCHEMA, title='x')):
            self.assertNotEqual(first, n3_relationships.input_hash(document, n1, n2, MODEL))

    def test_relationship_ids_are_deterministic(self):
        document, n1 = setup()
        n2 = make_n2(document, n1)
        first = n3_relationships.run(document, n1, n2, Runner(respond_one_level), MODEL)
        second = n3_relationships.run(document, n1, n2, Runner(respond_one_level), MODEL)
        self.assertEqual([item['relationship_id'] for item in first['relationships']],
                         [item['relationship_id'] for item in second['relationships']])


if __name__ == '__main__':
    unittest.main()

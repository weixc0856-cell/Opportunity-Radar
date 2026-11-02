"""N2 program validation: coverage, enums, evidence, and the no-relation-leak rule.

The model is replaced by a deterministic runner here; the real-model run is recorded in the
acceptance document. These tests hold the node to its contract: one interpretation per atom,
no invented candidates, no claim without located evidence, and no direction/relationship
word smuggled into the measure.
"""
import unittest
from unittest.mock import patch

from opportunity_radar import article_text, n2_semantic, numeric_candidates, semantic_common

TEXT = ('Personal income increased $54.5 billion (0.2 percent at a monthly rate) in '
        'September, according to estimates released today. Personal saving was $911.1 billion, '
        'and the personal saving rate was 3.8 percent.')
MODEL = {'provider': 'fake', 'model_id': 'fake', 'model_fingerprint': 'unknown',
         'generation_params': {'temperature': 0.0, 'max_tokens': 400}}


def setup():
    article = article_text.build({'article_id': 'a1', 'source_id': 's1', 'title': 'BEA',
                                  'content': TEXT, 'content_format': 'text'})
    return article.to_dict(), numeric_candidates.extract(article)


class Runner:
    def __init__(self, respond):
        self.respond = respond
        self.calls = 0
        self.payloads = []

    def run(self, payload):
        self.calls += 1
        self.payloads.append(payload)
        return self.respond(payload)


def interpretation(candidate, disposition='claim_value', quote=None, status='resolved', **extra):
    item = {
        'candidate_id': candidate['candidate_id'],
        'economic_relevance': extra.pop('economic_relevance', 'economic'),
        'disposition': disposition,
        'subject': 'personal income' if disposition == 'claim_value' else '',
        'predicate': 'personal_income' if disposition == 'claim_value' else '',
        'kind': 'fact' if disposition == 'claim_value' else 'unknown',
        'reason': 'test',
        'evidence_sentence_ids': [candidate['sentence_id']],
        'evidence_quote': candidate['raw_text'] if quote is None else quote,
        'status': status,
    }
    item.update(extra)
    return item


def default_respond(payload):
    items = []
    for candidate in payload['candidates']:
        if candidate['candidate_type'] in ('currency', 'percentage'):
            items.append(interpretation(candidate))
        elif candidate['candidate_type'] in ('date', 'period'):
            items.append(interpretation(candidate, 'context_only', status='resolved'))
        else:
            items.append(interpretation(candidate, 'non_claim', status='resolved'))
    return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}


class CoverageTests(unittest.TestCase):
    def test_happy_path_gives_every_candidate_one_result(self):
        document, n1 = setup()
        runner = Runner(default_respond)
        result = n2_semantic.run(document, n1, runner, MODEL)
        self.assertEqual(result['status'], 'success')
        ids = [item['candidate_id'] for item in result['candidate_interpretations']]
        self.assertEqual(sorted(ids), sorted(candidate['candidate_id']
                                             for candidate in n1['candidates']))
        self.assertEqual(result['statistics']['coverage_complete'], True)
        self.assertEqual(result['statistics']['input_candidate_count'], len(n1['candidates']))
        self.assertGreater(result['statistics']['claim_value_count'], 0)
        for item in result['candidate_interpretations']:
            self.assertIsNotNone(item['evidence_start'])

    def test_an_omitted_candidate_becomes_unresolved_not_dropped(self):
        document, n1 = setup()
        dropped = n1['candidates'][0]['candidate_id']

        def respond(payload):
            items = [item for item in default_respond(payload)['parsed']['interpretations']
                     if item['candidate_id'] != dropped]
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        by_id = {item['candidate_id']: item for item in result['candidate_interpretations']}
        self.assertEqual(by_id[dropped]['status'], 'unresolved')
        self.assertEqual(by_id[dropped]['disposition'], 'unresolved')
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['statistics']['coverage_complete'])

    def test_unknown_and_duplicate_candidates_are_recorded(self):
        document, n1 = setup()

        def respond(payload):
            items = default_respond(payload)['parsed']['interpretations']
            items = items + [dict(items[0]), dict(items[0], candidate_id='c-not-in-input')]
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        self.assertTrue(result['statistics']['coverage_complete'])
        record = result['batches'][0]
        self.assertIn('c-not-in-input', record['unknown_candidate_ids'])
        self.assertTrue(record['duplicate_candidate_ids'])
        self.assertEqual(result['status'], 'partial')

    def test_batch_metrics_are_recorded(self):
        document, n1 = setup()

        def respond(payload):
            base = default_respond(payload)
            base.update(seconds=1.5, input_chars=123, output_chars=45,
                        usage={'prompt_tokens': 80, 'completion_tokens': 20},
                        parse_retry=False)
            return base

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        batch = result['batches'][0]
        self.assertEqual(batch['seconds'], 1.5)
        self.assertEqual(batch['input_chars'], 123)
        self.assertEqual(batch['output_chars'], 45)
        self.assertEqual(batch['prompt_tokens'], 80)
        self.assertEqual(batch['completion_tokens'], 20)
        self.assertEqual(batch['candidate_count'], len(batch['candidate_ids']))

    def test_empty_candidates_do_not_call_the_model(self):
        document, _n1 = setup()
        n1 = dict(_n1, candidates=[])
        runner = Runner(default_respond)
        result = n2_semantic.run(document, n1, runner, MODEL)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(runner.calls, 0)
        self.assertEqual(result['candidate_interpretations'], [])


class EnumAndFieldTests(unittest.TestCase):
    def test_invalid_disposition_and_kind_are_coerced(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, disposition='definitely', kind='system_inference')
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['disposition'], 'unresolved')
        self.assertEqual(item['kind'], 'unknown')
        self.assertTrue(item['deviations'])

    def test_claim_value_without_subject_or_predicate_is_unresolved(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, subject='', predicate='')
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['status'], 'unresolved')

    def test_quote_not_located_is_unresolved_for_a_claim(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, quote='not in the article at all')
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['status'], 'unresolved')
        self.assertTrue(any(dev['reason'] == 'not_located' for dev in item['deviations']))

    def test_a_non_economic_claim_value_is_downgraded_to_non_claim(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, economic_relevance='non_economic')
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['disposition'], 'non_claim')
        self.assertEqual(item['model_disposition'], 'claim_value')
        self.assertEqual(item['economic_relevance'], 'non_economic')
        self.assertEqual(item['kind'], 'unknown')
        self.assertTrue(any(dev['reason'] == 'non_economic_claim_value'
                            for dev in item['deviations']))

    def test_uncertain_economic_relevance_becomes_ambiguous(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, economic_relevance='uncertain')
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['disposition'], 'ambiguous')
        self.assertEqual(item['status'], 'ambiguous')

    def test_a_relationship_word_in_the_predicate_is_rebuilt_from_subject(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, predicate='increase_amount')
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['predicate'], 'personal_income')
        self.assertEqual(item['predicate_raw'], 'increase_amount')
        self.assertEqual(item['predicate_source'], 'subject_fallback')
        self.assertTrue(any(dev['reason'] == 'relationship_leak' for dev in item['deviations']))

    def test_a_direction_word_inside_a_measure_is_removed(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, predicate='plunge_rate')
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['predicate'], 'personal_income')
        self.assertEqual(item['predicate_raw'], 'plunge_rate')
        self.assertEqual(item['predicate_source'], 'subject_fallback')

    def test_a_long_field_is_kept_and_marked_not_truncated(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]
        long_subject = 'x' * 300

        def respond(payload):
            item = interpretation(candidate, subject=long_subject)
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(len(item['subject']), 300)
        self.assertEqual(item['status'], 'unresolved')
        self.assertTrue(any(dev['reason'] == 'too_long' for dev in item['deviations']))

    def test_unknown_evidence_sentence_is_dropped_and_recorded(self):
        document, n1 = setup()
        candidate = n1['candidates'][0]

        def respond(payload):
            item = interpretation(candidate, evidence_sentence_ids=['s9999'])
            return {'status': 'ok', 'parsed': {'interpretations': [
                item] + [interpretation(other) for other in payload['candidates']
                         if other['candidate_id'] != candidate['candidate_id']]},
                'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == candidate['candidate_id'])
        self.assertEqual(item['evidence_sentence_ids'], [])
        self.assertTrue(any(dev['reason'] == 'unknown_sentence' for dev in item['deviations']))


class FailureTests(unittest.TestCase):
    def test_model_failure_marks_every_candidate_unresolved(self):
        document, n1 = setup()
        runner = Runner(lambda payload: {
            'status': 'model_unavailable', 'error': 'connection refused', 'attempts': 1})
        result = n2_semantic.run(document, n1, runner, MODEL)
        self.assertEqual(result['status'], 'model_unavailable')
        self.assertTrue(all(item['status'] == 'unresolved'
                            for item in result['candidate_interpretations']))
        self.assertEqual(len(result['candidate_interpretations']), len(n1['candidates']))

    def test_a_missing_interpretations_list_is_a_schema_failure(self):
        document, n1 = setup()
        runner = Runner(lambda payload: {'status': 'ok', 'parsed': {'wrong': []},
                                        'attempts': 1})
        result = n2_semantic.run(document, n1, runner, MODEL)
        self.assertEqual(result['status'], 'schema_error')
        self.assertTrue(all(item['status'] == 'unresolved'
                            for item in result['candidate_interpretations']))


class BatchTests(unittest.TestCase):
    def test_batches_do_not_mix_title_and_body(self):
        article = article_text.build({'article_id': 'a1', 'source_id': 's1',
                                      'title': 'Fiscal 2026 outlook',
                                      'content': 'Revenue was $5 billion. Costs were 12 percent.',
                                      'content_format': 'text'})
        document = article.to_dict()
        n1 = numeric_candidates.extract(article)
        batches = semantic_common.make_batches(document, n1['candidates'], max_candidates=8)
        fields = {candidate['candidate_id']: candidate['field'] for candidate in n1['candidates']}
        for batch in batches:
            self.assertTrue(batch['candidate_ids'])
            self.assertEqual({fields[value] for value in batch['candidate_ids']}, {batch['field']})

    def test_each_candidate_belongs_to_one_batch(self):
        document, n1 = setup()
        batches = semantic_common.make_batches(document, n1['candidates'], max_candidates=2)
        seen = [value for batch in batches for value in batch['candidate_ids']]
        self.assertEqual(sorted(seen), sorted(candidate['candidate_id']
                                              for candidate in n1['candidates']))
        self.assertEqual(len(seen), len(set(seen)))


class HashTests(unittest.TestCase):
    def test_input_hash_changes_with_n1_or_model(self):
        document, n1 = setup()
        first = n2_semantic.input_hash(document, n1, MODEL)
        changed = dict(n1, candidates=n1['candidates'][:-1])
        self.assertNotEqual(first, n2_semantic.input_hash(document, changed, MODEL))
        other_model = dict(MODEL, generation_params={'temperature': 0.0, 'max_tokens': 999})
        self.assertNotEqual(first, n2_semantic.input_hash(document, n1, other_model))

    def test_prompt_and_schema_changes_invalidate_the_hash(self):
        document, n1 = setup()
        first = n2_semantic.input_hash(document, n1, MODEL)
        with patch.object(n2_semantic, 'SYSTEM_PROMPT', n2_semantic.SYSTEM_PROMPT + ' extra'):
            self.assertNotEqual(first, n2_semantic.input_hash(document, n1, MODEL))
        with patch.object(n2_semantic, 'SCHEMA', dict(n2_semantic.SCHEMA, title='x')):
            self.assertNotEqual(first, n2_semantic.input_hash(document, n1, MODEL))

    def test_same_input_gives_the_same_hash(self):
        document, n1 = setup()
        self.assertEqual(n2_semantic.input_hash(document, n1, MODEL),
                         n2_semantic.input_hash(document, n1, MODEL))


class SubjectAndPredicateRulesTests(unittest.TestCase):
    def build(self, text):
        article = article_text.build({'article_id': 'a2', 'source_id': 's1', 'title': 'T',
                                      'content': text, 'content_format': 'text'})
        return article.to_dict(), numeric_candidates.extract(article)

    def test_a_possessive_is_not_part_of_the_subject_name(self):
        document, n1 = self.build("Intel's shares fell 20 percent.")
        percentage = next(candidate for candidate in n1['candidates']
                          if candidate['candidate_type'] == 'percentage')

        def respond(payload):
            items = []
            for candidate in payload['candidates']:
                if candidate['candidate_id'] == percentage['candidate_id']:
                    items.append(interpretation(candidate, subject="intel's shares",
                                                predicate='price'))
                else:
                    items.append(interpretation(candidate, 'non_claim', subject='',
                                                predicate='', kind='unknown'))
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == percentage['candidate_id'])
        self.assertEqual(item['subject'], 'intel shares')
        self.assertEqual(item['subject_raw'], "intel's shares")

    def test_document_defined_acronyms_expand_in_subject(self):
        document, n1 = self.build(
            'Real gross domestic product (GDP) increased 3.4 percent. '
            'In the second quarter, real GDP increased 2.2 percent.')
        percentages = [candidate for candidate in n1['candidates']
                       if candidate['candidate_type'] == 'percentage']

        def respond(payload):
            items = []
            for candidate in payload['candidates']:
                if candidate['candidate_type'] == 'percentage':
                    subject = ('real gross domestic product (gdp)'
                               if candidate.get('value') == 3.4 else 'real gdp')
                    items.append(interpretation(candidate, subject=subject,
                                                predicate='real_gross_domestic_product'))
                else:
                    items.append(interpretation(candidate, 'non_claim', subject='',
                                                predicate='', kind='unknown'))
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        by_value = {next(c['value'] for c in percentages
                         if c['candidate_id'] == item['candidate_id']): item
                    for item in result['candidate_interpretations']
                    if item['candidate_id'] in {c['candidate_id'] for c in percentages}}
        self.assertEqual(by_value[3.4]['subject'], 'real gross domestic product')
        self.assertEqual(by_value[2.2]['subject'], 'real gross domestic product')
        self.assertEqual(by_value[3.4]['subject_raw'], 'real gross domestic product (gdp)')
        self.assertTrue(any(dev['reason'] == 'normalized_acronym'
                            for dev in by_value[3.4]['deviations']))

    def test_a_generic_amount_predicate_is_rebuilt_from_the_subject(self):
        document, n1 = self.build(
            'The goods deficit increased $12.8 billion in August to $136.6 billion.')
        money = next(candidate for candidate in n1['candidates']
                     if candidate['candidate_type'] == 'currency'
                     and candidate.get('value') == 12.8)

        def respond(payload):
            items = []
            for candidate in payload['candidates']:
                if candidate['candidate_id'] == money['candidate_id']:
                    items.append(interpretation(candidate, subject='goods deficit',
                                                predicate='deficit_amount'))
                else:
                    items.append(interpretation(candidate, 'non_claim', subject='',
                                                predicate='', kind='unknown'))
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == money['candidate_id'])
        self.assertEqual(item['predicate'], 'goods_deficit')
        self.assertEqual(item['predicate_raw'], 'deficit_amount')
        self.assertEqual(item['predicate_source'], 'subject_fallback')
        self.assertTrue(any(dev['reason'] == 'generic_measure'
                            for dev in item['deviations']))

    def test_a_remainder_that_is_part_of_the_subject_uses_the_subject_measure(self):
        document, n1 = self.build(
            'The goods deficit increased $12.8 billion in August to $136.6 billion.')
        money = next(candidate for candidate in n1['candidates']
                     if candidate['candidate_type'] == 'currency'
                     and candidate.get('value') == 12.8)

        def respond(payload):
            items = []
            for candidate in payload['candidates']:
                if candidate['candidate_id'] == money['candidate_id']:
                    items.append(interpretation(candidate, subject='goods deficit',
                                                predicate='deficit_increase'))
                else:
                    items.append(interpretation(candidate, 'non_claim', subject='',
                                                predicate='', kind='unknown'))
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == money['candidate_id'])
        self.assertEqual(item['predicate'], 'goods_deficit')
        self.assertEqual(item['predicate_source'], 'subject_fallback')

    def test_a_bare_partial_measure_is_rebuilt_from_the_subject(self):
        document, n1 = self.build(
            'The services surplus increased less than $0.1 billion in August '
            'to $31.0 billion.')
        money = next(candidate for candidate in n1['candidates']
                     if candidate['candidate_type'] == 'currency'
                     and candidate.get('value') == 31.0)

        def respond(payload):
            items = []
            for candidate in payload['candidates']:
                if candidate['candidate_id'] == money['candidate_id']:
                    items.append(interpretation(candidate, subject='services surplus',
                                                predicate='surplus'))
                else:
                    items.append(interpretation(candidate, 'non_claim', subject='',
                                                predicate='', kind='unknown'))
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == money['candidate_id'])
        self.assertEqual(item['predicate'], 'services_surplus')
        self.assertEqual(item['predicate_source'], 'subject_fallback')
        self.assertTrue(any(dev['reason'] == 'partial_measure'
                            for dev in item['deviations']))

    def test_a_bounded_amount_with_a_same_sentence_measure_is_economic(self):
        document, n1 = self.build(
            'The services surplus increased less than $0.1 billion in August '
            'to $31.0 billion.')
        small = next(candidate for candidate in n1['candidates']
                     if candidate['candidate_type'] == 'currency'
                     and candidate.get('value') == 0.1)
        large = next(candidate for candidate in n1['candidates']
                     if candidate['candidate_type'] == 'currency'
                     and candidate.get('value') == 31.0)

        def respond(payload):
            items = []
            for candidate in payload['candidates']:
                if candidate['candidate_id'] == small['candidate_id']:
                    items.append(interpretation(candidate, 'context_only',
                                                economic_relevance='non_economic'))
                elif candidate['candidate_id'] == large['candidate_id']:
                    items.append(interpretation(candidate, subject='services surplus',
                                                predicate='services_surplus'))
                else:
                    items.append(interpretation(candidate, 'non_claim', subject='',
                                                predicate='', kind='unknown'))
            return {'status': 'ok', 'parsed': {'interpretations': items}, 'attempts': 1}

        result = n2_semantic.run(document, n1, Runner(respond), MODEL)
        item = next(value for value in result['candidate_interpretations']
                    if value['candidate_id'] == small['candidate_id'])
        self.assertEqual(item['disposition'], 'claim_value')
        self.assertEqual(item['economic_relevance'], 'economic')
        self.assertEqual(item['subject'], 'services surplus')
        self.assertEqual(item['predicate'], 'services_surplus')
        self.assertEqual(result['statistics']['promoted_bounded_amounts'], 1)
        self.assertTrue(any(dev['reason'] == 'bounded_economic_amount'
                            for dev in item['deviations']))



if __name__ == '__main__':
    unittest.main()

"""N0 and N1 against the Batch 8 contract.

N0 must keep the whole body, expose paragraphs and sentences whose `text[start:end]` restores
each record, and never rewrite a number. N1 must find every decimal digit, classify it as an
atom, keep the raw expression and position, and record ranges / from-to / direction /
comparison relations as separate groups that reference atoms rather than replacing them.
"""
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import article_text, numeric_candidates, pipeline_store, schema

PERSONAL = (
    'Personal income increased $54.5 billion (0.2 percent at a monthly rate) in September, '
    'according to estimates released today by the U.S. Bureau of Economic Analysis (BEA). '
    'Disposable personal income (DPI)—personal income less personal current taxes—increased '
    '$52.7 billion (0.2 percent), and personal consumption expenditures (PCE) increased '
    '$113.1 billion (0.5 percent). Personal outlays—the sum of PCE, personal interest '
    'payments, and personal current transfer payments—increased $113.0 billion in September. '
    'Personal saving was $911.1 billion, and the personal saving rate—personal saving as a '
    'percentage of DPI—was 3.8 percent.<br>')
TRADE = (
    'The U.S. goods and services trade deficit increased in August 2026 according to the U.S. '
    'Bureau of Economic Analysis and the U.S. Census Bureau. The deficit increased from '
    '$92.8 billion in July (revised) to $105.6 billion in August, as imports increased more '
    'than exports. The goods deficit increased $12.8 billion in August to $136.6 billion. '
    'The services surplus increased less than $0.1 billion in August to $31.0 billion.')
GDP = (
    'Real gross domestic product (GDP) increased at an annual rate of 3.4 percent in the '
    'third quarter of 2026 (July, August, and September), according to the advance estimate '
    'released today by the U.S. Bureau of Economic Analysis (BEA). In the second quarter, '
    'real GDP increased 2.2 percent.')
OBAMACARE = 'Premiums will rise 13 percent on average next year, officials said.'
TITLE = 'Personal Income and Outlays, September 2026'


def document(content, title='', content_format='text', **extra):
    payload = {'article_id': 'a1', 'source_id': 's1', 'title': title,
               'content': content, 'content_format': content_format}
    payload.update(extra)
    return article_text.build(payload)


def scan(content, title='', content_format='text'):
    return numeric_candidates.extract(document(content, title, content_format))


def atoms(result, candidate_type=None):
    return [item for item in result['candidates']
            if candidate_type is None or item['candidate_type'] == candidate_type]


def groups(result, expression_type):
    return [item for item in result['expression_groups']
            if item['expression_type'] == expression_type]


class N0ContractTests(unittest.TestCase):
    SAMPLES = (PERSONAL, TRADE,
               'a</p><p>b &amp; c &nbsp; d',
               'Intel&rsquo;s Shares Plunge 20% as A.I. Hinders Some Parts of Its Business',
               'Price rose 3.4&#37; &mdash; up from 2.2%')

    def test_output_carries_the_contract_fields(self):
        output = document('<p>Alpha 1.5</p>', 'Title', 'html').to_dict()
        for key in ('document_id', 'article_id', 'normalization_version', 'content_hash',
                    'title', 'text', 'paragraphs', 'sentences', 'offset_unit',
                    'offset_convention'):
            self.assertIn(key, output)
        self.assertEqual(output['normalization_version'], 'n0-v1')
        self.assertEqual(output['offset_unit'], 'unicode_codepoint')
        self.assertEqual(output['offset_convention'], 'half_open')
        self.assertEqual(output['article_id'], 'a1')

    def test_html_text_matches_the_evidence_normaliser(self):
        for sample in self.SAMPLES:
            self.assertEqual(document(sample, 'T', 'html').field('body').text,
                             schema._normalize(sample), sample)

    def test_paragraphs_and_sentences_restore_the_text(self):
        article = document(PERSONAL, TITLE)
        output = article.to_dict()
        for record in output['paragraphs'] + output['sentences']:
            self.assertEqual(output['text'][record['start']:record['end']], record['text'])
        for sentence in output['sentences']:
            self.assertIn(sentence['paragraph_id'],
                          {paragraph['paragraph_id'] for paragraph in output['paragraphs']})

    def test_paragraph_and_sentence_ids_are_stable_and_unique(self):
        first = document(PERSONAL, TITLE).to_dict()
        second = document(PERSONAL, TITLE).to_dict()
        self.assertEqual(first['paragraphs'], second['paragraphs'])
        self.assertEqual(first['sentences'], second['sentences'])
        self.assertEqual(len({p['paragraph_id'] for p in first['paragraphs']}),
                         len(first['paragraphs']))
        self.assertEqual(len({s['sentence_id'] for s in first['sentences']}),
                         len(first['sentences']))

    def test_title_is_the_first_paragraph_and_body_start_is_exposed(self):
        output = document(PERSONAL, TITLE).to_dict()
        self.assertEqual(output['paragraphs'][0]['field'], 'title')
        self.assertEqual(output['paragraphs'][0]['text'], TITLE.lower())
        self.assertEqual(output['body_start'],
                         len(output['paragraphs'][0]['text']) + 1)

    def test_html_tags_become_paragraphs_and_plain_text_keeps_angle_brackets(self):
        html = document('<p>one 1</p><p>two 2</p><br>', '', 'html').to_dict()
        self.assertEqual([p['text'] for p in html['paragraphs']], ['one 1', 'two 2'])
        plain = document('one 1 < two 2', '', 'text').to_dict()
        self.assertIn('<', plain['text'])

    def test_blank_lines_split_plain_text_paragraphs(self):
        output = document('first 1\n\nsecond 2', '', 'text').to_dict()
        self.assertEqual([p['text'] for p in output['paragraphs']], ['first 1', 'second 2'])

    def test_the_whole_body_is_kept(self):
        body = 'start 1\n\n' + ('x' * 25000) + ' end 2'
        output = document(body, '', 'text').to_dict()
        self.assertGreater(output['stats']['characters'], 25000)
        self.assertFalse(output['content_truncated'])
        self.assertIn('end 2', output['text'])

    def test_numbers_are_not_rewritten(self):
        article = document('Personal income rose 0.2 percent and $92.8bn in outlays.', 'T')
        self.assertIn('0.2 percent', article.field('body').text)
        self.assertIn('$92.8bn', article.field('body').text)

    def test_unicode_and_newlines_do_not_break_offsets(self):
        content = '营收 5% 😀\n\n第二段 3.5亿元'
        article = document(content, '标题', 'text')
        output = article.to_dict()
        for record in output['paragraphs'] + output['sentences']:
            self.assertEqual(output['text'][record['start']:record['end']], record['text'])

    def test_same_input_is_deterministic(self):
        first = document(PERSONAL, TITLE).to_dict()
        second = document(PERSONAL, TITLE).to_dict()
        self.assertEqual(first, second)
        self.assertEqual(first['document_id'], second['document_id'])

    def test_changed_content_changes_the_hashes(self):
        first = document('one 1', 'T').to_dict()
        second = document('one 2', 'T').to_dict()
        self.assertNotEqual(first['content_hash'], second['content_hash'])
        self.assertNotEqual(first['document_id'], second['document_id'])

    def test_empty_and_whitespace_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            document('', '', 'text')
        with self.assertRaises(ValueError):
            article_text.build({})

    def test_title_only_and_body_only_both_work(self):
        title_only = document('', 'Title 2026').to_dict()
        self.assertEqual([p['field'] for p in title_only['paragraphs']], ['title'])
        body_only = document('body 1').to_dict()
        self.assertEqual(body_only['body_start'], 0)


class AtomTests(unittest.TestCase):
    """Spec §六.B and §六.E: each expression becomes the expected atom."""

    CASES = (
        ('0.2%', 'percentage', '0.2%', 0.2, '%'),
        ('0.2 percent', 'percentage', '0.2 percent', 0.2, '%'),
        ('2 percentage points', 'percentage_point', '2 percentage points', 2.0, 'pp'),
        ('$92.8bn', 'currency', '$92.8bn', 92.8, 'USD'),
        ('USD 12.8 billion', 'currency', 'usd 12.8 billion', 12.8, 'USD'),
        ('5 million vehicles', 'quantity', '5 million vehicles', 5.0, 'vehicles'),
        ('1.5', 'scalar', '1.5', 1.5, ''),
        ('-0.5%', 'percentage', '-0.5%', -0.5, '%'),
        ('1,234,567', 'scalar', '1,234,567', 1234567.0, ''),
        ('0.002', 'scalar', '0.002', 0.002, ''),
    )

    def test_cases(self):
        for text, candidate_type, raw, value, unit in self.CASES:
            result = scan(text)
            self.assertEqual(len(result['candidates']), 1, text)
            atom = result['candidates'][0]
            self.assertEqual(atom['candidate_type'], candidate_type, text)
            self.assertEqual(atom['raw_text'], raw, text)
            self.assertAlmostEqual(atom['value'], value, places=9)
            self.assertEqual(atom['unit'], unit, text)
            self.assertEqual(atom['start'], 0, text)
            self.assertEqual(atom['end'], len(raw), text)

    def test_a_range_keeps_two_atoms_and_a_group(self):
        result = scan('2.1–2.5%')
        self.assertEqual([atom['raw_text'] for atom in result['candidates']], ['2.1', '2.5%'])
        self.assertEqual(result['statistics']['candidate_count'], 2)
        relation = groups(result, 'range')[0]
        self.assertEqual(relation['raw_text'], '2.1–2.5%')
        self.assertEqual(len(relation['candidate_ids']), 2)

    def test_scale_is_separate_from_value(self):
        atom = atoms(scan('$92.8 billion'), 'currency')[0]
        self.assertEqual((atom['value'], atom['scale'], atom['currency']),
                         (92.8, 'billion', 'USD'))
        self.assertNotIn('scaled_value', atom)

    def test_percent_and_percentage_point_stay_distinct(self):
        result = scan('Output rose 5 percent while prices rose 2 percentage points.')
        seen = {atom['unit'] for atom in result['candidates']}
        self.assertEqual(seen, {'%', 'pp'})

    def test_parenthesised_number_is_flagged_and_ambiguous(self):
        atom = atoms(scan('(0.5%)'), 'percentage')[0]
        self.assertEqual(atom['value'], 0.5)
        self.assertIn('parenthesized', atom['flags'])
        self.assertEqual(atom['detection_status'], 'ambiguous')

    def test_scientific_notation_is_one_atom(self):
        atom = atoms(scan('1.2e-5'), 'scalar')[0]
        self.assertAlmostEqual(atom['value'], 1.2e-05)
        self.assertIn('scientific', atom['flags'])

    def test_every_atom_records_a_detection_method(self):
        for atom in scan(PERSONAL)['candidates']:
            self.assertEqual(atom['detection_method'], 'regex')


class RelationTests(unittest.TestCase):
    """Spec §六.C and §六.D: relations reference atoms, never replace them."""

    def test_increased_and_declined_cues(self):
        for text, cue in (('increased 0.2%', 'increased'),
                          ('declined by 0.5 percent', 'declined'),
                          ('up 2 percentage points', 'up')):
            result = scan(text)
            relation = groups(result, 'increase_decrease')[0]
            self.assertIn(cue, relation['raw_text'])
            self.assertEqual(len(relation['candidate_ids']), 1)
            self.assertIn(relation['candidate_ids'][0],
                          [atom['candidate_id'] for atom in result['candidates']])

    def test_from_to_forward(self):
        result = scan('rose from 3.2% to 3.8%')
        relation = groups(result, 'from_to')[0]
        self.assertEqual(relation['raw_text'], 'from 3.2% to 3.8%')
        self.assertEqual(len(relation['candidate_ids']), 2)
        self.assertEqual(len(atoms(result)), 2)

    def test_from_to_reversed(self):
        result = scan('fell to $92.8bn from $95bn')
        relation = groups(result, 'from_to')[0]
        self.assertEqual(len(relation['candidate_ids']), 2)
        self.assertEqual([atom['raw_text'] for atom in atoms(result)],
                         ['$92.8bn', '$95bn'])

    def test_comparison_cue_links_to_its_atom(self):
        relation = groups(scan('compared with 3.2%'), 'comparison')[0]
        self.assertEqual(relation['raw_text'], 'compared with 3.2%')
        self.assertEqual(len(relation['candidate_ids']), 1)

    def test_temporal_comparison_without_a_number(self):
        for text in ('year over year', 'month-on-month'):
            relation = groups(scan(text), 'temporal_comparison')[0]
            self.assertEqual(relation['raw_text'], text)
            self.assertEqual(relation['candidate_ids'], [])

    def test_duration_is_a_quantity_and_carries_the_temporal_cue(self):
        result = scan('over the past 12 months')
        atom = atoms(result, 'quantity')[0]
        self.assertEqual((atom['raw_text'], atom['unit'], atom['unit_family']),
                         ('12 months', 'months', 'duration'))
        relation = groups(result, 'temporal_comparison')[0]
        self.assertEqual(relation['raw_text'], 'over the past 12 months')
        self.assertEqual(relation['candidate_ids'], [atom['candidate_id']])

    def test_related_candidates_are_symmetric(self):
        result = scan('rose from 3.2% to 3.8%')
        relation = groups(result, 'from_to')[0]
        by_id = {atom['candidate_id']: atom for atom in result['candidates']}
        first, second = relation['candidate_ids']
        self.assertIn(second, by_id[first]['related_candidates'])
        self.assertIn(first, by_id[second]['related_candidates'])

    def test_a_sentence_can_hold_two_atoms_and_two_relations(self):
        text = ('personal income increased 0.4 percent in september, following a '
                '0.3 percent increase in august.')
        result = scan(text)
        self.assertEqual([atom['raw_text'] for atom in atoms(result)],
                         ['0.4 percent', '0.3 percent'])
        self.assertEqual(len(groups(result, 'increase_decrease')), 2)


class DatePeriodTests(unittest.TestCase):
    def test_dates_and_periods(self):
        self.assertEqual(atoms(scan('September 2026'), 'date')[0]['temporal'],
                         {'kind': 'month', 'month': 9, 'year': 2026})
        self.assertEqual(atoms(scan('Q3 2026'), 'period')[0]['temporal'],
                         {'kind': 'quarter', 'year': 2026, 'quarter': 3})
        self.assertEqual(atoms(scan('FY2025'), 'period')[0]['temporal'],
                         {'kind': 'fiscal_year', 'year': 2025})
        self.assertEqual(atoms(scan('2026-11-01'), 'date')[0]['temporal'],
                         {'kind': 'day', 'year': 2026, 'month': 11, 'day': 1})
        self.assertEqual(atoms(scan('1997-2024'), 'period')[0]['temporal'],
                         {'kind': 'range', 'start_year': 1997, 'end_year': 2024})

    def test_a_year_alone_is_a_period_not_a_quantity(self):
        atom = atoms(scan('The data cover 2026.'))[0]
        self.assertEqual(atom['candidate_type'], 'period')
        self.assertIsNone(atom['value'])


class EdgeCaseTests(unittest.TestCase):
    def test_article_number_is_still_a_candidate(self):
        atom = atoms(scan('Article 5 applies.'))[0]
        self.assertEqual((atom['candidate_type'], atom['raw_text']), ('scalar', '5'))

    def test_phone_number_is_one_identifier(self):
        atom = atoms(scan('call +1-800-555-1234'), 'identifier')[0]
        self.assertEqual(atom['identifier'], 'phone')
        self.assertEqual(atom['raw_text'], '+1-800-555-1234')

    def test_citation_and_sec_forms_are_identifiers(self):
        self.assertEqual(atoms(scan('see [12]'), 'identifier')[0]['identifier'], 'citation')
        self.assertEqual(atoms(scan('10-K'), 'identifier')[0]['raw_text'], '10-k')
        self.assertEqual(atoms(scan('Form 8-K'), 'identifier')[0]['raw_text'], 'form 8-k')

    def test_url_digits_do_not_disappear(self):
        result = scan('https://example.com/item?id=50321622')
        self.assertTrue(result['candidates'])
        self.assertEqual(result['statistics']['coverage']['uncovered'], [])

    def test_version_digits_are_unclassified_not_dropped(self):
        atom = atoms(scan('v2.0'), 'unclassified_numeric')[0]
        self.assertEqual(atom['raw_text'], '2.0')
        self.assertEqual(atom['detection_status'], 'unclassified')

    def test_a_word_without_digits_yields_nothing(self):
        self.assertEqual(scan('AAPL ticker').get('candidates'), [])

    def test_repeated_numbers_are_not_deduplicated(self):
        result = scan('Revenue rose 5%. Costs rose 5%.')
        percents = atoms(result, 'percentage')
        self.assertEqual(len(percents), 2)
        self.assertNotEqual(percents[0]['candidate_id'], percents[1]['candidate_id'])

    def test_same_sentence_multiple_atoms(self):
        result = scan('Revenue rose from 3.2% to 3.8%, while costs fell 0.5%.')
        self.assertEqual(len(result['candidates']), 3)

    def test_adjacent_numbers_are_not_merged(self):
        result = scan('2.1–2.5%')
        self.assertEqual([atom['raw_text'] for atom in result['candidates']], ['2.1', '2.5%'])
        self.assertEqual(result['candidates'][0]['end'], 3)


class LocatingTests(unittest.TestCase):
    def test_every_atom_round_trips_and_finds_its_parents(self):
        article = document(PERSONAL, TITLE)
        output = article.to_dict()
        result = numeric_candidates.extract(article)
        sentences = {s['sentence_id']: s for s in output['sentences']}
        paragraphs = {p['paragraph_id']: p for p in output['paragraphs']}
        for atom in result['candidates']:
            self.assertEqual(atom['raw_text'], output['text'][atom['start']:atom['end']])
            self.assertIn(atom['sentence_id'], sentences)
            self.assertIn(atom['paragraph_id'], paragraphs)
            self.assertTrue(paragraphs[atom['paragraph_id']]['start']
                            <= atom['start'] < paragraphs[atom['paragraph_id']]['end'])
            self.assertEqual(atom['context'],
                             sentences[atom['sentence_id']]['text'])

    def test_every_decimal_digit_belongs_to_an_atom(self):
        text = ('Version v2.0 by covid19 watchers at https://example.com/item?id=50321622; '
                'area 3m², see [4], 12.5%.')
        result = scan(text)
        coverage = result['statistics']['coverage']
        self.assertEqual(coverage['uncovered'], [])
        self.assertEqual(coverage['covered'], coverage['digits'])

    def test_deterministic_ids_order_and_positions(self):
        first = scan(PERSONAL, TITLE)
        second = scan(PERSONAL, TITLE)
        self.assertEqual(first, second)
        spans = sorted((atom['field'], atom['start'], atom['end'])
                       for atom in first['candidates'])
        for (field_a, _start_a, end_a), (field_b, start_b, _end_b) in zip(spans, spans[1:]):
            if field_a == field_b:
                self.assertLessEqual(end_a, start_b)

    def test_changed_content_changes_atom_ids(self):
        first = scan('Revenue rose 5%.')['candidates'][0]
        second = scan('Revenue rose 6%.')['candidates'][0]
        self.assertNotEqual(first['candidate_id'], second['candidate_id'])
        third = scan('Costs fell first. Revenue rose 5%.')['candidates'][0]
        self.assertNotEqual(first['candidate_id'], third['candidate_id'])

    def test_group_ids_resolve_to_atoms(self):
        result = scan(PERSONAL, TITLE)
        atom_ids = {atom['candidate_id'] for atom in result['candidates']}
        for relation in result['expression_groups']:
            for candidate_id in relation['candidate_ids']:
                self.assertIn(candidate_id, atom_ids)
            self.assertEqual(relation['raw_text'],
                             document(PERSONAL, TITLE).to_dict()['text'][
                                 relation['start']:relation['end']])

    def test_empty_article_and_no_numbers_are_normal(self):
        result = scan('Nothing numeric here.')
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['statistics']['candidate_count'], 0)
        self.assertEqual(result['statistics']['coverage'],
                         {'digits': 0, 'covered': 0, 'uncovered': []})


class HumanBenchmarkTests(unittest.TestCase):
    """The 19 numbers annotated by hand in R2 Batch 6, re-checked on the new contract."""

    def test_personal_income_figures(self):
        result = scan(PERSONAL, TITLE)
        money = atoms(result, 'currency')
        percent = atoms(result, 'percentage')
        self.assertEqual([atom['value'] for atom in money], [54.5, 52.7, 113.1, 113.0, 911.1])
        self.assertEqual([atom['value'] for atom in percent], [0.2, 0.2, 0.5, 3.8])

    def test_trade_figures(self):
        result = scan(TRADE, 'U.S. International Trade in Goods and Services, August 2026')
        self.assertEqual([atom['value'] for atom in atoms(result, 'currency')],
                         [92.8, 105.6, 12.8, 136.6, 0.1, 31.0])

    def test_gdp_intel_obamacare(self):
        self.assertEqual([atom['value'] for atom in atoms(scan(GDP), 'percentage')], [3.4, 2.2])
        self.assertEqual([atom['value'] for atom in atoms(
            scan('', 'Intel’s Shares Plunge 20% as A.I. Hinders Some Parts of Its Business'),
            'percentage')], [20.0])
        self.assertEqual([atom['value'] for atom in atoms(scan(OBAMACARE), 'percentage')],
                         [13.0])

    def test_the_five_batch5_misses_have_locations(self):
        personal = scan(PERSONAL, TITLE)
        found = {(atom['value'], atom['unit']) for atom in personal['candidates']}
        self.assertIn((0.2, '%'), found)
        self.assertIn((0.5, '%'), found)
        trade = scan(TRADE)
        found = {(atom['value'], atom['unit']) for atom in trade['candidates']}
        self.assertIn((92.8, 'USD'), found)
        self.assertIn((12.8, 'USD'), found)
        self.assertIn((0.1, 'USD'), found)
        for atom in trade['candidates']:
            self.assertIsNotNone(atom['sentence_id'])
            self.assertIsNotNone(atom['paragraph_id'])


class PipelineStoreTests(unittest.TestCase):
    def test_record_and_find(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = pipeline_store.PipelineStore(Path(tmp) / 'runs.sqlite3')
            output = {'candidates': [], 'statistics': {'candidate_count': 0}}
            inserted, output_hash = store.record(
                article_id='a1', document_id='d1', content_hash='h1', node_name='N1',
                node_version='n1-v1', input_hash='i1', output=output)
            self.assertTrue(inserted)
            self.assertEqual(store.find('a1', 'N1', 'n1-v1', 'i1'), output)
            self.assertIsNone(store.find('a1', 'N1', 'n1-v1', 'other'))
            run = store.runs('a1')[0]
            self.assertEqual(run['output_hash'], output_hash)
            self.assertEqual(run['execution_status'], 'ok')

    def test_a_rerun_does_not_overwrite_the_first_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = pipeline_store.PipelineStore(Path(tmp) / 'runs.sqlite3')
            store.record(article_id='a1', document_id='d1', content_hash='h1', node_name='N1',
                         node_version='n1-v1', input_hash='i1', output={'value': 1})
            inserted, _ = store.record(article_id='a1', document_id='d1', content_hash='h1',
                                       node_name='N1', node_version='n1-v1', input_hash='i1',
                                       output={'value': 2})
            self.assertFalse(inserted)
            self.assertEqual(store.find('a1', 'N1', 'n1-v1', 'i1'), {'value': 1})

    def test_a_new_version_or_input_is_a_new_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = pipeline_store.PipelineStore(Path(tmp) / 'runs.sqlite3')
            store.record(article_id='a1', document_id='d1', content_hash='h1', node_name='N1',
                         node_version='n1-v1', input_hash='i1', output={'value': 1})
            store.record(article_id='a1', document_id='d1', content_hash='h1', node_name='N1',
                         node_version='n1-v2', input_hash='i1', output={'value': 2})
            store.record(article_id='a1', document_id='d1', content_hash='h2', node_name='N1',
                         node_version='n1-v1', input_hash='i2', output={'value': 3})
            self.assertEqual(len(store.runs('a1')), 3)
            self.assertEqual(store.find('a1', 'N1', 'n1-v1', 'i2'), {'value': 3})

    def test_failed_runs_are_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = pipeline_store.PipelineStore(Path(tmp) / 'runs.sqlite3')
            store.record(article_id='a1', document_id='', content_hash='', node_name='N0',
                         node_version='n0-v1', input_hash='i1', output={'error': 'x'},
                         status='failed')
            self.assertIsNone(store.find('a1', 'N0', 'n0-v1', 'i1'))

    def test_a_failed_run_does_not_block_a_later_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = pipeline_store.PipelineStore(Path(tmp) / 'runs.sqlite3')
            store.record(article_id='a1', document_id='d1', content_hash='h1', node_name='N1',
                         node_version='n1-v1', input_hash='i1', output={'error': 'x'},
                         status='failed')
            inserted, _ = store.record(article_id='a1', document_id='d1', content_hash='h1',
                                       node_name='N1', node_version='n1-v1', input_hash='i1',
                                       output={'value': 2})
            self.assertTrue(inserted)
            self.assertEqual(store.find('a1', 'N1', 'n1-v1', 'i1'), {'value': 2})
            self.assertEqual(len(store.runs('a1')), 2)


if __name__ == '__main__':
    unittest.main()

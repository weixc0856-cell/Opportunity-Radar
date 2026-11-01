"""N0 and N1: the deterministic head of the claim pipeline.

N0 must produce exactly the text the evidence locator uses, with offsets that point back
into the raw HTML. N1 must find every decimal digit in that text and attach a lexical class
to it without computing anything. These tests hold both to that contract.
"""
import unittest
from types import SimpleNamespace

from opportunity_radar import article_text, numeric_candidates, schema

TITLE = 'Personal Income and Outlays, September 2026'
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


def scan(title, summary):
    return numeric_candidates.extract(article_text.build({'title': title, 'summary': summary}))


def candidates(title, summary, category=None):
    result = scan(title, summary)
    return [item for item in result['candidates']
            if category is None or item['category'] == category]


class N0NormalisationTests(unittest.TestCase):
    SAMPLES = (
        PERSONAL, TRADE,
        'a</p><p>b &amp; c &nbsp; d',
        'Intel&rsquo;s Shares Plunge 20% as A.I. Hinders Some Parts of Its Business',
        'Price rose 3.4&#37; &mdash; up from 2.2%',
        '<b>x</b>y &lt;b&gt;z&lt;/b&gt;',
    )

    def test_canonical_text_matches_the_evidence_normaliser(self):
        for sample in self.SAMPLES:
            article = article_text.build({'title': 'T', 'summary': sample})
            self.assertEqual(article.field('summary').text, schema._normalize(sample), sample)

    def test_offsets_match_the_evidence_locator(self):
        article = article_text.build({'title': TITLE, 'summary': PERSONAL})
        quote = 'personal income increased $54.5 billion'
        locator = schema._locate(quote, TITLE, PERSONAL)
        self.assertIsNotNone(locator)
        self.assertEqual(locator['field'], 'summary')
        self.assertEqual(locator['start'], article.field('summary').text.find(quote))

    def test_segments_and_sentences_tile_the_text(self):
        article = article_text.build({'title': TITLE, 'summary': PERSONAL})
        for record in article.segments + article.sentences:
            field = article.field(record['field'])
            self.assertEqual(field.text[record['start']:record['end']], record['text'])
        for name, field in article.fields.items():
            covered = set()
            for sentence in article.sentences:
                if sentence['field'] == name:
                    covered.update(range(sentence['start'], sentence['end']))
            missing = [index for index, char in enumerate(field.text)
                       if not char.isspace() and index not in covered]
            self.assertEqual(missing, [], name)

    def test_title_is_the_first_segment(self):
        article = article_text.build({'title': TITLE, 'summary': PERSONAL})
        self.assertEqual(article.segments[0]['field'], 'title')
        self.assertEqual(article.segments[0]['text'], TITLE.lower())

    def test_raw_spans_point_into_the_original_html(self):
        raw = 'Price rose 3.4&#37; &mdash; up from 2.2%'
        article = article_text.build({'title': 'T', 'summary': raw})
        field = article.field('summary')
        start = field.text.find('3.4%')
        raw_start, raw_end = article.raw_span('summary', start, start + 4)
        self.assertEqual(raw[raw_start:raw_end], '3.4&#37;')

    def test_build_is_deterministic(self):
        first = article_text.build({'title': TITLE, 'summary': PERSONAL})
        second = article_text.build({'title': TITLE, 'summary': PERSONAL})
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.text_hash, second.text_hash)
        self.assertEqual(first.source_hash, second.source_hash)

    def test_an_article_object_is_accepted_like_a_dict(self):
        article = article_text.build(SimpleNamespace(title=TITLE, summary=PERSONAL))
        self.assertIn('personal income', article.field('summary').text)

    def test_an_empty_article_is_rejected(self):
        with self.assertRaises(ValueError):
            article_text.build({'title': '', 'summary': ''})
        with self.assertRaises(ValueError):
            article_text.build({})

    def test_abbreviations_do_not_end_a_sentence(self):
        article = article_text.build({
            'title': 'T',
            'summary': 'The U.S. Bureau said so. It gave no figure.'})
        sentences = [s for s in article.sentences if s['field'] == 'summary']
        self.assertEqual(len(sentences), 2)
        self.assertIn('u.s.', sentences[0]['text'])

    def test_decimal_points_do_not_end_a_sentence(self):
        article = article_text.build({
            'title': 'T', 'summary': 'GDP rose 3.4 percent. It fell 2.2 percent.'})
        self.assertEqual(len([s for s in article.sentences if s['field'] == 'summary']), 2)


class HumanBenchmarkTests(unittest.TestCase):
    """The 19 numbers the R2 Batch 6 review annotated by hand, all from real releases."""

    def test_personal_income_figures(self):
        money = candidates(TITLE, PERSONAL, 'money')
        percent = candidates(TITLE, PERSONAL, 'percent')
        self.assertEqual([item['value'] for item in money], [54.5, 52.7, 113.1, 113.0, 911.1])
        self.assertEqual([item['value'] for item in percent], [0.2, 0.2, 0.5, 3.8])
        self.assertTrue(all(item['currency'] == 'USD' for item in money))
        self.assertTrue(all(item['scale'] == 'billion' for item in money))

    def test_trade_figures(self):
        money = candidates('U.S. International Trade in Goods and Services, August 2026',
                           TRADE, 'money')
        self.assertEqual([item['value'] for item in money], [92.8, 105.6, 12.8, 136.6, 0.1, 31.0])

    def test_gdp_and_single_figures(self):
        self.assertEqual([item['value'] for item in candidates(
            'GDP (Advance Estimate), 3rd Quarter 2026', GDP, 'percent')], [3.4, 2.2])
        self.assertEqual([item['value'] for item in candidates(
            'Intel’s Shares Plunge 20% as A.I. Hinders Some Parts of Its Business', '',
            'percent')], [20.0])
        self.assertEqual([item['value'] for item in candidates(
            'Obamacare Policies Hit Again With Steep Premium Increases for 2027',
            OBAMACARE, 'percent')], [13.0])


class ClassificationTests(unittest.TestCase):
    def test_percent_and_percentage_point_stay_distinct(self):
        result = candidates('T', 'Output rose 5 percent while prices rose 2 percentage points.', None)
        units_seen = {item['unit'] for item in result}
        self.assertIn('%', units_seen)
        self.assertIn('pp', units_seen)
        self.assertEqual(candidates('T', 'prices rose 2 percentage points.', 'percent'), [])

    def test_money_keeps_the_scale_separate(self):
        item = candidates('T', 'The deficit was $92.8 billion.', 'money')[0]
        self.assertEqual((item['value'], item['scale'], item['currency']), (92.8, 'billion', 'USD'))
        self.assertEqual(item['scale_factor'], 1e9)
        self.assertNotIn('scaled', item)

    def test_short_scale_words_attach(self):
        item = candidates('T', 'Revenue reached $6.3bn this year.', 'money')[0]
        self.assertEqual((item['value'], item['scale']), (6.3, 'billion'))
        item = candidates('T', 'Revenue reached $1tn this year.', 'money')[0]
        self.assertEqual((item['value'], item['scale']), (1.0, 'trillion'))

    def test_thousands_separators_are_parsed(self):
        item = candidates('T', 'The plant made 1,234.5 tonnes.', 'quantity')[0]
        self.assertEqual((item['value'], item['unit']), (1234.5, 'tonnes'))

    def test_parenthesised_number_is_flagged_not_silently_signed(self):
        item = candidates('T', 'The revision was (1.2).', 'bare')[0]
        self.assertEqual(item['value'], 1.2)
        self.assertIn('parenthesized', item['flags'])

    def test_dates_and_periods_are_classified_by_shape(self):
        dated = candidates('T', 'Reported on 2026-11-01 in Washington.', 'date')[0]
        self.assertEqual(dated['temporal'], {'kind': 'day', 'year': 2026, 'month': 11, 'day': 1})
        month = candidates('T', 'The data cover 2026-09.', 'period')[0]
        self.assertEqual(month['temporal'], {'kind': 'month', 'year': 2026, 'month': 9})
        span = candidates('T', 'The series runs 1997-2024.', 'period')[0]
        self.assertEqual(span['temporal'], {'kind': 'range', 'start_year': 1997, 'end_year': 2024})
        quarter = candidates('T', 'Output rose in Q3 2026.', 'period')[0]
        self.assertEqual(quarter['temporal'], {'kind': 'quarter', 'year': 2026, 'quarter': 3})

    def test_a_year_is_not_a_quantity(self):
        result = candidates('T', 'The data cover 2026.', None)
        self.assertEqual([item['category'] for item in result], ['period'])
        self.assertIsNone(result[0]['value'])

    def test_a_clock_time_is_not_a_ratio(self):
        item = candidates('T', 'The call starts at 3:30 today.', 'time')[0]
        self.assertEqual(item['temporal'], {'kind': 'time', 'hour': 3, 'minute': 30})
        self.assertEqual(candidates('T', 'The call starts at 3:30 today.', 'ratio'), [])

    def test_phone_numbers_and_citations_are_identifiers(self):
        phone = candidates('T', 'Call +1-800-555-1234 for details.', 'identifier')[0]
        self.assertEqual(phone['identifier'], 'phone')
        citation = candidates('T', 'See the appendix [12] for the table.', 'identifier')[0]
        self.assertEqual((citation['identifier'], citation['digits']), ('citation', '12'))

    def test_chinese_percent_and_scaled_amount(self):
        result = scan('标题', '营收增长了5%，达到3.5亿元。')
        percent = [item for item in result['candidates'] if item['category'] == 'percent'][0]
        self.assertEqual((percent['value'], percent['unit']), (5.0, '%'))
        magnitude = [item for item in result['candidates'] if item['scale_factor'] == 1e8][0]
        self.assertEqual((magnitude['value'], magnitude['scale']), (3.5, '亿'))
        self.assertEqual(result['stats']['coverage']['uncovered'], [])

    def test_scaled_value_is_not_multiplied(self):
        item = candidates('T', '5 million cells were counted.', 'quantity')[0]
        self.assertEqual((item['value'], item['scale'], item['unit']), (5.0, 'million', 'cells'))


class CoverageTests(unittest.TestCase):
    def test_every_decimal_digit_belongs_to_a_candidate(self):
        text = ('Version v2.0 was reported by covid19 watchers on https://example.com/item?id=50321622 '
                'and the area is 3m². See [4] for 12.5%.')
        result = scan('T', text)
        coverage = result['stats']['coverage']
        self.assertEqual(coverage['uncovered'], [])
        self.assertEqual(coverage['covered'], coverage['digits'])
        embedded = [item for item in result['candidates'] if item['category'] == 'embedded']
        self.assertTrue(embedded)

    def test_a_text_without_numbers_yields_no_candidates(self):
        result = scan('Title without figures', 'Nothing numeric here.')
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['stats']['coverage'], {'digits': 0, 'covered': 0, 'uncovered': []})

    def test_candidates_do_not_overlap_and_ids_are_deterministic(self):
        first = scan(TITLE, PERSONAL)
        second = scan(TITLE, PERSONAL)
        self.assertEqual(first, second)
        spans = sorted((item['field'], item['start'], item['end']) for item in first['candidates'])
        for (field_a, _start_a, end_a), (field_b, start_b, _end_b) in zip(spans, spans[1:]):
            if field_a == field_b:
                self.assertLessEqual(end_a, start_b)
        self.assertEqual([item['id'] for item in first['candidates']],
                         [f'c{index:04d}' for index in range(1, len(first['candidates']) + 1)])

    def test_n1_refuses_a_missing_article(self):
        with self.assertRaises(ValueError):
            numeric_candidates.extract(None)


class CueTests(unittest.TestCase):
    def test_direction_and_comparison_cues_are_recorded(self):
        item = candidates(TITLE, PERSONAL, 'money')[0]
        terms = {(cue['term'], cue['role']) for cue in item['cues']}
        self.assertIn(('increased', 'direction'), terms)
        self.assertIn(('at a monthly rate', 'comparison'), terms)

    def test_cue_offsets_point_into_the_field_text(self):
        article = article_text.build({'title': TITLE, 'summary': PERSONAL})
        result = numeric_candidates.extract(article)
        item = result['candidates'][1]
        field = article.field(item['field'])
        for cue in item['cues']:
            self.assertEqual(field.text[cue['start']:cue['start'] + cue['length']], cue['term'])

    def test_n1_does_not_interpret_the_cues(self):
        item = candidates('T', 'Output fell 3 percent from a year earlier.', 'percent')[0]
        roles = {cue['term']: cue['role'] for cue in item['cues']}
        self.assertEqual(roles['fell'], 'direction')
        self.assertEqual(roles['from a year earlier'], 'comparison')
        self.assertNotIn('direction_of_change', item)


if __name__ == '__main__':
    unittest.main()

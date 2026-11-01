"""N0/N1 reuse and N2 -> N3 cache invalidation across the node store."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import (n2_semantic, n3_relationships, numeric_candidates,
                               pipeline_store)
from tools.run_n1 import prepare_document

MODEL = {'provider': 'fake', 'model_id': 'fake', 'model_fingerprint': 'unknown',
         'generation_params': {'temperature': 0.0, 'max_tokens': 600}}


class DocumentReuseTests(unittest.TestCase):
    def test_n1_is_reused_by_the_store(self):
        article = SimpleNamespace(
            article_id='a1', title='Revenue', summary='Revenue was $5 billion in 2025.',
            url='https://example.org/a1', source_name='test', feed_id='f1')
        with tempfile.TemporaryDirectory() as tmp:
            store = pipeline_store.PipelineStore(Path(tmp) / 'runs.sqlite3')
            _text, _document, first, reused = prepare_document(article, store)
            self.assertFalse(reused)
            _text, _document, second, reused = prepare_document(article, store)
            self.assertTrue(reused)
            self.assertEqual(first, second)
            runs = store.runs('a1')
            self.assertEqual(sorted(run['node_name'] for run in runs), ['N0', 'N1'])


class CacheInvalidationTests(unittest.TestCase):
    def test_changing_an_n2_interpretation_changes_the_n3_key(self):
        article = SimpleNamespace(
            article_id='a1', title='Revenue', summary='Revenue was $5 billion in 2025.',
            url='https://example.org/a1', source_name='test', feed_id='f1')
        from opportunity_radar import article_text
        text = article_text.build({'article_id': 'a1', 'source_id': 'f1',
                                   'title': article.title, 'content': article.summary,
                                   'content_format': 'text'})
        document = text.to_dict()
        n1 = numeric_candidates.extract(text)
        items = []
        for candidate in n1['candidates']:
            items.append({
                'candidate_id': candidate['candidate_id'],
                'disposition': 'claim_value' if candidate['candidate_type'] == 'currency'
                else 'context_only',
                'subject': 'revenue', 'predicate': 'revenue', 'kind': 'fact', 'reason': '',
                'evidence_sentence_ids': [candidate['sentence_id']],
                'evidence_quote': candidate['raw_text'], 'status': 'resolved',
                'deviations': []})
        n2 = {'node': 'N2', 'node_version': n2_semantic.NODE_VERSION,
              'document_id': document['document_id'], 'status': 'success',
              'candidate_interpretations': items, 'statistics': {}}
        first = n3_relationships.input_hash(document, n1, n2, MODEL)
        changed = dict(n2, candidate_interpretations=[
            dict(item, subject='different') for item in items])
        self.assertNotEqual(first, n3_relationships.input_hash(document, n1, changed, MODEL))

    def test_n2_and_n3_rule_hashes_are_recorded(self):
        self.assertEqual(len(n2_semantic.RULESET), 16)
        self.assertEqual(len(n3_relationships.RULESET), 16)
        self.assertNotEqual(n2_semantic.RULESET, n3_relationships.RULESET)


if __name__ == '__main__':
    unittest.main()

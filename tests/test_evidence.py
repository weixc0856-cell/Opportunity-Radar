import unittest
from opportunity_radar.evidence import (content_basis, content_basis_estimate, state_for, state_of,
                                        rank_of, rank_at_least, looks_truncated, LEGACY_LEVEL,
                                        EVIDENCE_RANK)

LONG='A complete paragraph of reporting. '*40

class ContentBasisTests(unittest.TestCase):
 def test_empty_body_is_title_only(self):
  self.assertEqual(content_basis({'summary':''}),'title_only')
  self.assertEqual(content_basis_estimate({'summary':''}),'title_only')
 def test_short_body_is_excerpt(self):
  self.assertEqual(content_basis({'summary':'short teaser'}),'excerpt')
 def test_an_unreviewed_long_body_is_still_an_excerpt(self):
  # The estimate may guess "complete", but only a reviewed declaration grants E2.
  self.assertEqual(content_basis_estimate({'summary':LONG}),'full_text')
  self.assertEqual(content_basis({'summary':LONG}),'excerpt')
 def test_declared_full_text_grants_it(self):
  self.assertEqual(content_basis({'summary':'short'},{'content_access_level':'full_text'}),'full_text')
 def test_declared_excerpt_never_grants_it(self):
  self.assertEqual(content_basis({'summary':LONG},{'content_access_level':'excerpt'}),'excerpt')
 def test_declared_title_only(self):
  self.assertEqual(content_basis({'summary':LONG},{'content_access_level':'title_only'}),'title_only')
 def test_unknown_declaration_falls_back_to_auto(self):
  self.assertEqual(content_basis({'summary':LONG},{'content_access_level':'nonsense'}),'excerpt')
 def test_estimate_respects_truncation_markers(self):
  self.assertEqual(content_basis_estimate({'summary':LONG+'Read more'}),'excerpt')
 def test_html_is_stripped_before_estimating(self):
  self.assertEqual(content_basis_estimate({'summary':'<p>'+LONG+'</p>'}),'full_text')
 def test_truncation_markers(self):
  self.assertTrue(looks_truncated('a long piece of text…'))
  self.assertTrue(looks_truncated('whatever Continue reading'))
  self.assertFalse(looks_truncated('a complete sentence.'))

class StateTests(unittest.TestCase):
 def test_no_quotes_is_none(self):
  self.assertEqual(state_for('full_text',[]),'none')
 def test_any_unlocated_quote_dominates(self):
  self.assertEqual(state_for('full_text',['summary','unlocated']),'unlocated_quotes')
 def test_title_only_quotes_are_e0(self):
  self.assertEqual(state_for('excerpt',['title']),'title_only')
 def test_excerpt_state(self):
  self.assertEqual(state_for('excerpt',['summary']),'rss_excerpt_only')
 def test_full_text_state(self):
  self.assertEqual(state_for('full_text',['summary']),'full_text_verified')
 def test_primary_provenance(self):
  self.assertEqual(state_for('full_text',['summary'],provenance='first_party'),'primary_source_located')
 def test_primary_outranks_multi_source(self):
  # "The actor published this" is a stronger statement than "several outlets ran it".
  self.assertEqual(state_for('full_text',['summary'],multi_source=True,provenance='first_party'),'primary_source_located')
 def test_multi_source_coverage_is_not_confirmation(self):
  self.assertEqual(state_for('full_text',['summary'],multi_source=True),'multi_source_coverage')
 def test_vendor_is_not_primary(self):
  self.assertEqual(state_for('full_text',['summary'],provenance='vendor_marketing'),'full_text_verified')
 def test_legacy_records_reconstruct_state(self):
  self.assertEqual(state_of({'evidence_level':'summary'}),'rss_excerpt_only')
  self.assertEqual(state_of({'evidence_level':'title'}),'title_only')
  self.assertEqual(state_of({'evidence_level':'untraceable'}),'unlocated_quotes')
  self.assertEqual(state_of({}),'none')
  self.assertEqual(state_of({'evidence_state':'multi_source_coverage'}),'multi_source_coverage')
 def test_retired_state_names_still_resolve(self):
  self.assertEqual(state_of({'evidence_state':'cross_source_confirmed'}),'multi_source_coverage')
  self.assertEqual(state_of({'evidence_state':'primary_source_verified'}),'primary_source_located')
 def test_rank_gate(self):
  self.assertEqual(rank_of('rss_excerpt_only'),'E1')
  self.assertTrue(rank_at_least('E2','E1'))
  self.assertFalse(rank_at_least('E1','E2'))
  self.assertFalse(rank_at_least('E0','nonsense'))
 def test_legacy_level_mapping(self):
  self.assertEqual(LEGACY_LEVEL['multi_source_coverage'],'full_text')
  self.assertEqual(EVIDENCE_RANK['unlocated_quotes'],'E0')

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from opportunity_radar import youtube_source


VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
Hello and welcome to the interview.

00:00:04.000 --> 00:00:08.000
We spent $2 million on procurement last quarter.

00:00:08.000 --> 00:00:12.000
The data center power bottleneck is real.
"""


class VttTests(unittest.TestCase):
    def test_parses_cues_and_drops_music(self):
        cues = youtube_source.parse_vtt(VTT + "\n00:00:12.000 --> 00:00:14.000\n[Music]\n")
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[1][2], 'We spent $2 million on procurement last quarter.')

    def test_deduplicates_rolling_auto_captions(self):
        raw = VTT + "\n00:00:12.000 --> 00:00:15.000\nThe data center power bottleneck is real.\n"
        cues = youtube_source.parse_vtt(raw)
        self.assertEqual(len(cues), 3)


class ExcerptTests(unittest.TestCase):
    def test_selects_the_commercial_window(self):
        cues = youtube_source.parse_vtt(VTT)
        excerpt = youtube_source.select_excerpt(cues, max_chars=600, require_signal=True)
        self.assertGreater(excerpt['score'], 0)
        self.assertIn('procurement', excerpt['text'])
        self.assertIn('power bottleneck', excerpt['text'])

    def test_refuses_an_irrelevant_transcript_when_signal_is_required(self):
        cues = youtube_source.parse_vtt(
            "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nToday we talk about the weather.\n")
        excerpt = youtube_source.select_excerpt(cues, max_chars=600, require_signal=True)
        self.assertEqual(excerpt['reason'], 'no_signal_keywords')
        self.assertEqual(excerpt['text'], '')


class CandidateTests(unittest.TestCase):
    def test_filters_short_long_live_and_old(self):
        config = {'max_age_days': 7, 'min_duration': 300, 'max_duration': 10800}
        source = {}
        self.assertEqual(youtube_source._source_matches({'title': 'x', 'duration': 100}, source, config)[1], 'too_short')
        self.assertEqual(youtube_source._source_matches({'title': 'x', 'duration': 20000}, source, config)[1], 'too_long')
        self.assertEqual(youtube_source._source_matches({'title': 'x', 'live_status': 'is_live'}, source, config)[1], 'live_or_upcoming')
        self.assertEqual(youtube_source._source_matches({'title': 'x', 'upload_date': '20200101'}, source, config)[1], 'too_old')
        self.assertEqual(youtube_source._source_matches({'title': 'AI interview', 'duration': 600,
                                                        'upload_date': '20261112'}, {'keywords': ['AI']}, config)[0], True)


class CollectTests(unittest.TestCase):
    def test_builds_one_article_with_an_excerpt_and_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            source = {'source_id': 'yt-test', 'name': 'Test Channel', 'channel_url': 'https://youtube.com/@x'}
            pick = {'source': source, 'entry': {'id': 'vid1', 'title': 'AI interview'},
                    'video_id': 'vid1'}
            info = {'id': 'vid1', 'title': 'AI interview', 'channel': 'Test Channel',
                    'upload_date': '20261110', 'duration': 600,
                    'subtitles': {'en': [{'ext': 'vtt'}]}, 'automatic_captions': {}}

            def fake_subtitles(url, video_id, config, info, cache_root):
                path = cache_root / video_id / 'transcript.vtt'
                path.parent.mkdir(parents=True)
                path.write_text(VTT, encoding='utf-8')
                return path, 'manual', ''

            class FakeStore:
                def youtube_video_seen(self, video_id): return False
                def save_youtube_video(self, record): self.record = record

            store = FakeStore()
            with (patch.object(youtube_source, 'plan_candidates', return_value=([pick], {}, [])),
                  patch.object(youtube_source, 'video_info', return_value=info),
                  patch.object(youtube_source, 'fetch_subtitles', side_effect=fake_subtitles)):
                articles, stats, issues = youtube_source.collect({'languages': ['en'], 'max_transcript_chars': 600,
                                                                  'require_signal': True}, store=store, cache_root=cache)
            self.assertEqual(len(articles), 1)
            article = articles[0]
            self.assertEqual(article.source_id, 'yt-test')
            self.assertEqual(article.source_name, 'Test Channel')
            self.assertEqual(article.youtube['transcript_kind'], 'manual')
            self.assertIn('procurement', article.summary)
            self.assertEqual(stats['fetched'], 1)
            self.assertEqual(store.record['status'], 'fetched')


class ConfigTests(unittest.TestCase):
    def test_enabled_source_requires_approval(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'youtube.json'
            path.write_text(json.dumps({'enabled': True, 'sources': [
                {'source_id': 'yt', 'name': 'x', 'channel_url': 'https://youtube.com/@x',
                 'enabled': True, 'permission_status': 'review_required'}]}), encoding='utf-8')
            config = youtube_source.load_config(path)
            self.assertTrue(any(i['code'] == 'youtube_not_approved' for i in config['issues']))
            self.assertEqual(youtube_source.enabled_sources(config), [])

    def test_missing_config_means_no_youtube(self):
        config = youtube_source.load_config('reports/does-not-exist-youtube.json')
        self.assertFalse(config['enabled'])
        self.assertEqual(config['sources'], [])

import unittest
from datetime import datetime, timezone

from opportunity_radar.digest import render_digest
from opportunity_radar.sampling import filter_articles, in_window, parse_bound, parse_window


class Article:
    def __init__(self, published):
        self.published = published


SINCE = "2026-10-16"
UNTIL = "2026-10-23"


class ParseTests(unittest.TestCase):
    def test_date_only_means_midnight_utc(self):
        self.assertEqual(parse_bound("2026-10-16"), datetime(2026, 10, 16, tzinfo=timezone.utc))
        self.assertIsNone(parse_bound(""))

    def test_naive_datetime_is_treated_as_utc(self):
        self.assertEqual(parse_bound("2026-10-16T12:00:00"), datetime(2026, 10, 16, 12, tzinfo=timezone.utc))

    def test_offset_is_converted_to_utc(self):
        self.assertEqual(parse_bound("2026-10-16T08:00:00+08:00"), datetime(2026, 10, 16, 0, tzinfo=timezone.utc))

    def test_window_rejects_reversed_bounds(self):
        with self.assertRaises(ValueError):
            parse_window("2026-10-23", "2026-10-16")
        with self.assertRaises(ValueError):
            parse_window("2026-10-23", "2026-10-23")

    def test_invalid_date_raises(self):
        with self.assertRaises(ValueError):
            parse_bound("16/10/2026")


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.start, self.end = parse_window(SINCE, UNTIL)

    def test_since_is_inclusive_and_until_exclusive(self):
        self.assertTrue(in_window("2026-10-16T00:00:00+00:00", self.start, self.end))
        self.assertFalse(in_window("2026-10-15T23:59:59+00:00", self.start, self.end))
        self.assertTrue(in_window("2026-10-22T23:59:59+00:00", self.start, self.end))
        self.assertFalse(in_window("2026-10-23T00:00:00+00:00", self.start, self.end))

    def test_missing_or_broken_timestamp_is_outside_a_window(self):
        self.assertFalse(in_window("", self.start, self.end))
        self.assertFalse(in_window("not-a-date", self.start, self.end))
        self.assertTrue(in_window("", None, None))

    def test_filter_preserves_order_and_identity(self):
        items = [Article("2026-10-15T00:00:00+00:00"), Article("2026-10-18T00:00:00+00:00"),
                 Article("2026-10-20T00:00:00+00:00")]
        kept = filter_articles(items, self.start, self.end)
        self.assertEqual(kept, items[1:])

    def test_no_window_keeps_everything(self):
        items = [Article(""), Article("2020-01-01T00:00:00+00:00")]
        self.assertEqual(filter_articles(items, None, None), items)


class ReportTests(unittest.TestCase):
    def test_text_report_states_the_window(self):
        stats = {"fetched": 3, "new": 3, "queued": 3, "analyzed": 3, "failed": 0, "skipped": 0,
                 "counts": {"priority": 0, "watch": 0, "filtered": 0},
                 "sample_window": {"since": SINCE, "until": UNTIL, "pool": 120, "in_window": 40, "sampled": 30}}
        _, body = render_digest([], stats, "2026-10-23")
        self.assertIn("样本窗口：2026-10-16 至 2026-10-23 UTC", body)
        self.assertIn("池 120 → 窗口内 40 → 取 30", body)


if __name__ == '__main__':
    unittest.main()

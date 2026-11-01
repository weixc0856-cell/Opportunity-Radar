import unittest
from opportunity_radar.freshrss_client import FreshRSSClient, Article

def art(i,feed): return Article(str(i),f't{i}',f'https://example.invalid/{feed}/{i}','s','2026-10-20T00:00:00+00:00',f'f{feed}',str(feed))

class Fake(FreshRSSClient):
    def __init__(self,feeds): super().__init__('http://127.0.0.1:1','u','k'); self.feeds=feeds
    def _fetch_feed(self,feed_id=None):
        if feed_id is None: feed_id=None
        return list(self.feeds.get(feed_id,[]))

class Tests(unittest.TestCase):
 def test_interleaves_feeds(self):
  c=Fake({1:[art(1,1),art(2,1)],2:[art(3,2),art(4,2)]})
  self.assertEqual([a.feed_id for a in c.fetch_articles(3,feed_ids=[1,2])],['1','2','1'])
 def test_dedupes_by_url(self):
  a1=art(1,1); dup=Article('9','dup',a1.url,'s','','',  '2')
  c=Fake({1:[a1],2:[dup]})
  self.assertEqual(len(c.fetch_articles(5,feed_ids=[1,2])),1)
 def test_without_feed_ids_uses_global_fetch(self):
  c=Fake({None:[art(1,None)]})
  self.assertEqual(len(c.fetch_articles(5)),1)


def raw_item(url,title='Title',feed=1,ts=1790000000):
    return {'title':title,'url':url,'feed_id':feed,'created_on_time':ts,'description':'body'}

class UpgradeTests(unittest.TestCase):
    """http links are only kept after the https variant is verified on the same host."""
    class C(Fake):
        def __init__(self,ok):
            super().__init__({}); self.ok=ok; self.calls=[]
        def _https_ok(self,url):
            self.calls.append(url); return self.ok
    def articles(self,client,*urls):
        return client._articles({'feeds':[{'id':1,'title':'F'}],'items':[raw_item(u) for u in urls]})
    def test_verified_http_link_is_upgraded(self):
        c=self.C(True)
        out=self.articles(c,'http://www.bea.gov/news/2026/x')
        self.assertEqual([a.url for a in out],['https://www.bea.gov/news/2026/x'])
    def test_unverified_http_link_is_dropped(self):
        c=self.C(False)
        self.assertEqual(self.articles(c,'http://legacy.example/a'),[])
    def test_https_link_is_not_rechecked(self):
        c=self.C(True)
        self.assertEqual(len(self.articles(c,'https://example.org/a')),1)
        self.assertEqual(c.calls,[])
    def test_result_is_cached_per_url(self):
        c=self.C(True)
        self.articles(c,'http://www.bea.gov/a','http://www.bea.gov/a')
        self.assertEqual(len(c.calls),1)
    def test_non_http_schemes_are_dropped(self):
        c=self.C(True)
        self.assertEqual(self.articles(c,'ftp://example.org/a','mailto:x@example.org'),[])


class FeedOrderTests(unittest.TestCase):
    def test_numeric_ids_sort_numerically(self):
        from opportunity_radar.freshrss_client import ordered_feed_ids
        self.assertEqual(ordered_feed_ids({'3', '17', '9', '24'}), ['3', '9', '17', '24'])

    def test_non_numeric_ids_sort_after_numeric_ones(self):
        from opportunity_radar.freshrss_client import ordered_feed_ids
        self.assertEqual(ordered_feed_ids({'b', '2', 'a'}), ['2', 'a', 'b'])


class SamplingFairnessTests(unittest.TestCase):
    def test_duplicate_url_does_not_starve_a_later_feed(self):
        first = art(1, 1)
        duplicate = Article('9', 'dup', first.url, 's', '', '', '2')
        other = art(3, 2)
        client = Fake({1: [first], 2: [duplicate, other]})
        picked = client.fetch_articles(2, feed_ids=[1, 2])
        self.assertEqual([a.feed_id for a in picked], ['1', '2'])
        self.assertEqual(len({a.url for a in picked}), 2)

    def test_first_pass_covers_every_feed_before_seconds(self):
        client = Fake({1: [art(1, 1), art(2, 1)], 2: [art(3, 2), art(4, 2)], 3: [art(5, 3)]})
        picked = client.fetch_articles(3, feed_ids=[1, 2, 3])
        self.assertEqual([a.feed_id for a in picked], ['1', '2', '3'])

    def test_limit_below_feed_count_is_respected(self):
        client = Fake({1: [art(1, 1)], 2: [art(2, 2)]})
        picked = client.fetch_articles(1, feed_ids=[1, 2])
        self.assertEqual([a.feed_id for a in picked], ['1'])

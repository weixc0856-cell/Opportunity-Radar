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

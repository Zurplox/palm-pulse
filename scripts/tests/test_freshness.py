#!/usr/bin/env python3
"""Locks the news freshness window.

The edition must contain recent news only. collect() drops anything published
before MAX_NEWS_AGE_DAYS (4) days ago, and these tests pin that behaviour so a
later change to feed handling cannot quietly let last week's headlines back in.
Dates are computed relative to now, so the tests never expire.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fetch_news as fn  # noqa: E402


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class FakeResponse:
    content = b"<rss></rss>"

    def raise_for_status(self):
        return None


class FakeFeed:
    bozo = 0
    bozo_exception = None

    def __init__(self, entries):
        self.entries = entries


class NewsFreshnessWindow(unittest.TestCase):
    def setUp(self):
        self.saved = (fn.SOURCES, fn.requests.get, fn.feedparser.parse,
                      fn.MAX_NEWS_AGE_DAYS)
        fn.SOURCES = [{"name": "Test Feed", "url": "https://example.com/rss",
                       "category": "Market", "country": "Indonesia", "lang": "en"}]
        fn.requests.get = lambda url, **kwargs: FakeResponse()

    def tearDown(self):
        fn.SOURCES, fn.requests.get, fn.feedparser.parse, fn.MAX_NEWS_AGE_DAYS = self.saved

    def collect_titles(self, entries):
        fn.feedparser.parse = lambda content: FakeFeed(entries)
        stories, errors = fn.collect()
        self.assertEqual(errors, [])
        return [s["title"] for s in stories]

    def entry(self, title, days_old):
        return {"title": title, "link": "https://example.com/" + title.replace(" ", "-"),
                "published": ago(days_old), "summary": "Isi berita contoh yang cukup panjang."}

    def test_default_window_is_four_days(self):
        self.assertEqual(fn.MAX_NEWS_AGE_DAYS, 4)

    def test_drops_news_older_than_four_days(self):
        titles = self.collect_titles([
            self.entry("Berita hari ini", 0.2),
            self.entry("Berita tiga hari lalu", 3.0),
            self.entry("Berita lima hari lalu", 5.0),
            self.entry("Berita dua pekan lalu", 14.0),
        ])
        self.assertIn("Berita hari ini", titles)
        self.assertIn("Berita tiga hari lalu", titles)
        self.assertNotIn("Berita lima hari lalu", titles)
        self.assertNotIn("Berita dua pekan lalu", titles)

    def test_boundary_just_inside_and_just_outside(self):
        titles = self.collect_titles([
            self.entry("Masih dalam jendela", 3.9),
            self.entry("Sudah lewat jendela", 4.1),
        ])
        self.assertEqual(titles, ["Masih dalam jendela"])

    def test_window_is_configurable(self):
        fn.MAX_NEWS_AGE_DAYS = 2
        titles = self.collect_titles([
            self.entry("Satu hari", 1.0),
            self.entry("Tiga hari", 3.0),
        ])
        self.assertEqual(titles, ["Satu hari"])

    def test_undated_entry_is_kept_as_now(self):
        """Documents existing behaviour: a feed item with no usable date is
        treated as published now rather than discarded, so a publisher that omits
        dates does not vanish from the edition."""
        fn.feedparser.parse = lambda content: FakeFeed([
            {"title": "Tanpa tanggal", "link": "https://example.com/x",
             "summary": "Isi berita contoh."}])
        stories, _ = fn.collect()
        self.assertEqual([s["title"] for s in stories], ["Tanpa tanggal"])

    def test_stories_are_ordered_newest_first(self):
        titles = self.collect_titles([
            self.entry("Kemarin", 1.0),
            self.entry("Baru saja", 0.1),
            self.entry("Tiga hari", 3.0),
        ])
        self.assertEqual(titles, ["Baru saja", "Kemarin", "Tiga hari"])


if __name__ == "__main__":
    unittest.main()

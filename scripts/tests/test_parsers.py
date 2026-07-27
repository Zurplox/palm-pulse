#!/usr/bin/env python3
"""Characterization tests for the fragile parsing layer.

These lock in CURRENT behaviour on purpose. Some assertions encode known
quirks (noted inline) rather than ideal behaviour, so that any future change to
classification or price parsing shows up as a deliberate, reviewed diff instead
of a silent shift in what the website and the Android app display.
"""
import os
import sys
import types
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fetch_news as fn  # noqa: E402


class NumberParsing(unittest.TestCase):
    def test_indonesian_decimal_comma(self):
        self.assertAlmostEqual(fn.parse_id_number("3.930,55"), 3930.55)

    def test_thousands_separator_only(self):
        self.assertAlmostEqual(fn.parse_id_number("3.930"), 3930.0)

    def test_plain_integer(self):
        self.assertAlmostEqual(fn.parse_id_number("3930"), 3930.0)

    def test_garbage_returns_none(self):
        self.assertIsNone(fn.parse_id_number("tidak ada"))


class PeriodParsing(unittest.TestCase):
    def test_same_month_range(self):
        self.assertEqual(
            fn.parse_tbs_period("Harga TBS Sawit Plasma Riau 22 - 28 Juli 2026"),
            ("2026-07-22", "2026-07-28"),
        )

    def test_cross_month_range(self):
        self.assertEqual(
            fn.parse_tbs_period("periode 29 Juni - 5 Juli 2026"),
            ("2026-06-29", "2026-07-05"),
        )

    def test_no_period_returns_none(self):
        self.assertIsNone(fn.parse_tbs_period("Harga TBS naik pekan ini"))


class PriceBand(unittest.TestCase):
    def test_price_band_is_configurable(self):
        # Guards against the old hardcoded 2000-8000 window.
        self.assertEqual((fn.PRICE_MIN, fn.PRICE_MAX), (2000.0, 8000.0))

    def test_candidate_extracts_age_table_and_marks_source(self):
        text = (
            "Harga TBS Sawit Plasma Riau periode 22 - 28 Juli 2026 naik Rp39,58 per Kg. "
            "Untuk sawit umur 4 tahun Rp3.434,68, umur 5 tahun Rp3.639,59, "
            "umur 6 tahun Rp3.797,84 dan umur 9 tahun Rp3.930,55."
        )
        item = fn.parse_tbs_candidate(
            "Harga TBS Sawit Plasma Riau 22-28 Juli 2026",
            text,
            "https://www.infosawit.com/2026/07/21/contoh/",
            "InfoSAWIT",
            datetime(2026, 7, 21, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["scheme"], "Plasma")
        self.assertEqual(item["region"], "Riau")
        self.assertEqual(item["valid_from"], "2026-07-22")
        self.assertEqual(item["valid_to"], "2026-07-28")
        self.assertAlmostEqual(item["age_prices_rp_per_kg"]["5"], 3639.59)
        self.assertAlmostEqual(item["age_prices_rp_per_kg"]["9"], 3930.55)
        self.assertAlmostEqual(item["change_rp_per_kg"], 39.58)


class Classification(unittest.TestCase):
    def test_market_signal_vocabulary(self):
        # The Android widget matches these strings; they must not drift.
        self.assertEqual(fn.market_signal([{"impact": "Positive"}] * 3), "Constructive")
        self.assertEqual(fn.market_signal([{"impact": "Negative"}] * 3), "Cautious")
        self.assertEqual(fn.market_signal([{"impact": "Neutral"}]), "Balanced")

    def test_impact_vocabulary(self):
        category, impact = fn.classify("Harga CPO naik tajam", "", "Market")
        self.assertIn(impact, {"Positive", "Negative", "Neutral"})
        self.assertEqual(impact, "Positive")

    def test_known_quirk_weather_counts_as_negative(self):
        # QUIRK: drought is price-bullish, but 'kemarau' sits in NEGATIVE.
        # Locked deliberately: the Android filter chips and impact badges are
        # built from these values, so changing it is a user-visible change.
        _, impact = fn.classify("Kemarau panjang di Riau", "", "Plantation")
        self.assertEqual(impact, "Negative")

    def test_known_quirk_market_keywords_dominate_category(self):
        # QUIRK: 'harga'/'cpo' live in MARKET, so most stories land in Market
        # regardless of the per-source default category.
        category, _ = fn.classify("Harga CPO hari ini", "", "Indonesia")
        self.assertEqual(category, "Market")


class TextHelpers(unittest.TestCase):
    def test_title_key_drops_stopwords(self):
        self.assertEqual(fn.title_key("The price of palm oil in Riau"), "price palm oil riau")

    def test_clip_sentence_fallback(self):
        self.assertEqual(
            fn.clip_sentence(""),
            "Preview unavailable. Open the original article to read more.",
        )

    def test_source_from_title_splits_multiword_publisher(self):
        title, publisher = fn.source_from_title("CPO prices climb - The Star Online", "Feed")
        self.assertEqual(title, "CPO prices climb")
        self.assertEqual(publisher, "The Star Online")

    def test_known_quirk_single_word_publisher_is_not_split(self):
        # QUIRK: source_from_title only splits when the trailing publisher has
        # 2-7 words, so 'Reuters' stays inside the headline. Locked because the
        # app displays both title and source verbatim.
        title, publisher = fn.source_from_title("CPO prices climb - Reuters", "Feed")
        self.assertEqual(title, "CPO prices climb - Reuters")
        self.assertEqual(publisher, "Feed")

    def test_slug_strips_publisher_suffix(self):
        self.assertEqual(
            fn.infosawit_slug("Harga TBS Sawit Plasma Riau 22-28 Juli 2026 - InfoSAWIT"),
            "harga-tbs-sawit-plasma-riau-22-28-juli-2026",
        )


class UrlDiscovery(unittest.TestCase):
    def test_candidates_are_valid_absolute_urls(self):
        candidates = fn.infosawit_url_candidates(
            "Harga TBS Sawit Swadaya Riau 22-28 Juli 2026 - InfoSAWIT",
            datetime(2026, 7, 21, 3, 0, tzinfo=timezone.utc),
            "https://news.google.com/rss/articles/abc",
        )
        self.assertTrue(candidates)
        for url in candidates:
            self.assertRegex(url, r"^https://[a-z.]+infosawit\.com/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/$")

    def test_existing_infosawit_url_is_preferred_first(self):
        candidates = fn.infosawit_url_candidates(
            "Harga TBS",
            datetime(2026, 7, 21, tzinfo=timezone.utc),
            "https://www.infosawit.com/2026/07/21/asli/?utm_source=x",
        )
        self.assertEqual(candidates[0], "https://www.infosawit.com/2026/07/21/asli/")


class Batching(unittest.TestCase):
    def test_chunks_cover_every_item_once(self):
        items = [{"id": i} for i in range(18)]
        chunks = fn._chunks(items, 6)
        self.assertEqual([len(c) for c in chunks], [6, 6, 6])
        self.assertEqual([i["id"] for c in chunks for i in c], list(range(18)))

    def test_uneven_chunks(self):
        self.assertEqual([len(c) for c in fn._chunks(list(range(7)), 3)], [3, 3, 1])


class ArticleRetryMemo(unittest.TestCase):
    """The same InfoSAWIT price article is surfaced by several TBS feeds.

    It must not be refetched once per feed (that is what made runs take over an
    hour), but a transient anti-bot block must still get a real second chance,
    because price coverage matters more than speed.
    """

    def setUp(self):
        self.real_requests = fn.requests
        self.calls = []
        fn._ARTICLE_CACHE.clear()
        fn._ARTICLE_ATTEMPTS.clear()

        def fake_get(url, **kwargs):
            self.calls.append(url)
            raise RuntimeError("blocked")

        fn.requests = types.SimpleNamespace(get=fake_get)

    def tearDown(self):
        fn.requests = self.real_requests
        fn._ARTICLE_CACHE.clear()
        fn._ARTICLE_ATTEMPTS.clear()

    def test_failed_url_is_retried_but_bounded(self):
        url = "https://www.infosawit.com/2026/07/22/harga-tbs-riau/"
        for _ in range(8):  # eight feeds surfacing the same article
            self.assertEqual(fn.fetch_tbs_article(url), ("", url))
        self.assertEqual(fn._ARTICLE_ATTEMPTS[url], fn.ARTICLE_MAX_ATTEMPTS)
        # Each attempt tries 2 variants (plain + /amp/): 2 x 2, not 8 x 2.
        self.assertEqual(len(self.calls), 2 * fn.ARTICLE_MAX_ATTEMPTS)

    def test_successful_fetch_is_never_refetched(self):
        url = "https://www.infosawit.com/2026/07/22/ok/"
        fn._ARTICLE_CACHE[url] = ("teks tbs riau siak", url)
        self.assertEqual(fn.fetch_tbs_article(url), ("teks tbs riau siak", url))
        self.assertEqual(self.calls, [])


class FallbackContract(unittest.TestCase):
    def test_fallback_master_keeps_widget_headline_structure(self):
        # The Android widget shows the first non-blank line as its headline.
        text = fn.fallback_master([
            {"title": "Contoh berita", "country": "Indonesia"},
            {"title": "Berita kedua", "country": "Malaysia"},
        ])
        first_line = next(line.strip() for line in text.splitlines() if line.strip())
        self.assertEqual(first_line, "RINGKASAN EKSEKUTIF")


if __name__ == "__main__":
    unittest.main(verbosity=2)

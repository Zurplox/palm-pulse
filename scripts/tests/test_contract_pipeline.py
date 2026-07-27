#!/usr/bin/env python3
"""Pairs the producer with the validator.

The unit tests cover parsing, and scripts/qa.py validates a published edition,
but for a while nothing ran qa.py against output that main() had actually
written: qa.py was only ever pointed at the committed seed, whose timestamps are
already in the exact shape the Android app prefers. A real run writes
datetime.isoformat() instead, and a contract assertion on that shape once failed
the whole workflow AFTER a successful 21-minute crawl, discarding a good edition.

These tests generate an edition the way CI does, then validate exactly that file,
for each failure mode the workflow can realistically hit. The rule they enforce:
qa.py may WARN about anything, but it may only FAIL on something that would crash
the Android app.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fetch_news as fn  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
# Everything scripts/qa.py reads, plus the script itself. qa.py resolves its own
# location, so it must be copied into the sandbox to validate the sandbox.
COPY = ["index.html", "manifest.webmanifest", "config/sources.json",
        "data/latest.json", "scripts/qa.py", "sw.js",
        "assets/styles.css", "assets/app.js", "assets/icon.svg"]


class FakeResponse:
    def __init__(self, status):
        self.status_code = status


class FakeHttpError(Exception):
    def __init__(self, status):
        super().__init__("HTTP %d" % status)
        self.response = FakeResponse(status)


def stories(count=6):
    return [{
        "id": "s%02d" % i,
        "title": "Harga CPO pada sesi ke-%d" % i,
        "url": "https://example.com/berita-%d" % i,
        "source": "InfoSAWIT",
        "country": "Indonesia",
        "category": "Market",
        "published_at": "2026-07-26T02:00:00+00:00",
        "snippet": "cuplikan berita " * 8,
        "summary": "Ringkasan ekstraktif sementara.",
        "summary_type": "extract",
        "summary_model": None,
        "impact": "Neutral",
    } for i in range(count)]


def prices():
    return [{
        "region": "Riau", "scheme": "Swadaya", "price_rp_per_kg": 3930.55,
        "change_rp_per_kg": 13.25, "change_percent": 0.34,
        "valid_from": "2026-07-22", "valid_to": "2026-07-28",
        "source_name": "InfoSAWIT",
        "source_url": "https://www.infosawit.com/2026/07/22/harga-tbs-riau/",
        "status": "current_period", "trend": "up",
        "age_prices_rp_per_kg": {"4": 3400.0, "5": 3639.59, "6": 3800.0, "9": 3930.55},
        "data_quality": "full_age_table", "price_source": "published",
        "confidence": "infosawit", "cross_checked_sources": 1,
    }]


def ai(model, prompt, max_tokens, **kwargs):
    # Both calls use the same token budget, and the master prompt also embeds
    # story titles, so the only reliable discriminator is json_mode: story
    # batches ask for JSON, the master brief asks for plain text.
    if not kwargs.get("json_mode"):
        # Must clear the 80-character floor in build_master_summary, or the
        # builder silently discards it and falls back to the extractive brief.
        return ("RINGKASAN EKSEKUTIF\n"
                "- Harga CPO bergerak naik pada perdagangan pekan ini.\n"
                "- Kebijakan biodiesel B50 masih menjadi penggerak utama pasar.")
    items = json.loads(prompt[prompt.index("["):])
    return json.dumps([{"id": it["id"], "summary": "Ringkasan AI lengkap. " * 4}
                       for it in items])


def dead_key(model, prompt, max_tokens, **kwargs):
    raise FakeHttpError(401)


class GeneratedEditionPassesQa(unittest.TestCase):
    """Generate like CI, then validate exactly what was generated."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for rel in COPY:
            target = self.tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, target)
        # Every monkeypatched attribute is restored in tearDown. Leaking a
        # stubbed collect() into later test modules once made the freshness
        # tests fail while passing in isolation.
        self.saved = {name: getattr(fn, name) for name in
                      ("DATA", "KEY", "collect", "collect_tbs_prices",
                       "call_gemini", "fetch_json")}
        self.saved_sleep = fn.time.sleep
        fn.DATA = self.tmp / "data"
        fn.KEY = "fake-key"
        fn.time.sleep = lambda seconds: None
        fn.STAGE_STATUS.clear()
        fn.fetch_json = lambda url: None

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(fn, name, value)
        fn.time.sleep = self.saved_sleep
        fn.STAGE_STATUS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def generate(self, gemini, tbs_prices, found=None):
        fn.collect = lambda: (stories() if found is None else found, [])
        fn.collect_tbs_prices = lambda: (tbs_prices, [])
        fn.call_gemini = gemini
        self.assertEqual(fn.main(), 0, "main() must exit 0 so the deploy proceeds")
        return json.loads((self.tmp / "data/latest.json").read_text(encoding="utf-8"))

    def gate(self):
        result = subprocess.run([sys.executable, str(self.tmp / "scripts/qa.py")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         "qa.py must not reject a real edition:\n" + result.stdout + result.stderr)
        return result

    def assert_android_can_decode(self, data):
        """Moshi throws JsonDataException on a missing or null non-null field."""
        for key, kind in (("generated_at", str), ("story_count", int),
                          ("master_summary", str), ("stories", list)):
            self.assertIsInstance(data.get(key), kind, "PalmPulseNews.%s" % key)
        for i, story in enumerate(data["stories"]):
            for key in ("id", "title", "url", "source", "published_at"):
                self.assertTrue(isinstance(story.get(key), str) and story[key].strip(),
                                "story %d PalmPulseStory.%s" % (i, key))

    def test_happy_path_edition_passes_the_gate(self):
        data = self.generate(ai, prices())
        result = self.gate()
        self.assert_android_can_decode(data)
        # The regression that broke the workflow: isoformat() output must warn,
        # never fail.
        self.assertIn("+00:00", data["generated_at"])
        self.assertIn("freshness shows STALE", result.stderr)
        # Guards against a stub that quietly degrades to the extractive path and
        # makes this test pass without exercising any AI code at all.
        self.assertEqual(data["master_summary_type"], "ai")
        self.assertEqual(data["ai_summary_count"], data["story_count"])

    def test_dead_api_key_edition_passes_the_gate(self):
        data = self.generate(dead_key, prices())
        self.gate()
        self.assert_android_can_decode(data)
        self.assertEqual(data["master_summary_type"], "extract")

    def test_edition_without_any_price_passes_the_gate(self):
        data = self.generate(ai, [])
        self.gate()
        self.assert_android_can_decode(data)
        self.assertEqual(data["tbs_prices"], [])

    def test_single_story_edition_passes_the_gate(self):
        data = self.generate(ai, prices(), found=stories(1))
        self.gate()
        self.assert_android_can_decode(data)
        self.assertEqual(data["story_count"], 1)


if __name__ == "__main__":
    unittest.main()

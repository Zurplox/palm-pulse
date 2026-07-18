#!/usr/bin/env python3
"""Collect palm-oil RSS news, optionally summarize with Gemini, and write static JSON."""
from __future__ import annotations
import html, json, os, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCES = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
MAX_STORIES = int(os.getenv("MAX_STORIES", "18"))
MAX_AI = int(os.getenv("MAX_AI_SUMMARIES", "8"))
USER_AGENT = "PalmPulse/1.0 (+personal news reader)"

POSITIVE = {"rise", "rises", "gain", "gains", "higher", "tight", "shortage", "decline in stocks", "b50", "b40", "strong demand", "export growth"}
NEGATIVE = {"fall", "falls", "drop", "drops", "lower", "surplus", "weak demand", "export decline", "higher output", "oversupply"}
POLICY = {"policy", "law", "regulation", "levy", "duty", "tax", "eudr", "ispo", "mspo", "rspo", "biodiesel", "b40", "b50"}
PLANTATION = {"plantation", "smallholder", "fertilizer", "fertiliser", "ganoderma", "replanting", "yield", "harvest", "tbs", "ffb"}
MARKET = {"price", "futures", "fcpo", "cpo", "stock", "export", "import", "production", "demand", "supply"}


def clean_text(value: str | None) -> str:
    soup = BeautifulSoup(html.unescape(value or ""), "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clip_sentence(text: str, limit: int = 300) -> str:
    text = clean_text(text)
    if not text:
        return "Preview unavailable. Open the original article to read more."
    parts = re.split(r"(?<=[.!?])\s+", text)
    chosen = parts[0]
    if len(chosen) < 70 and len(parts) > 1:
        chosen += " " + parts[1]
    if len(chosen) <= limit:
        return chosen
    cut = chosen[: limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


def parse_date(entry) -> datetime:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                dt = dateparser.parse(value)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def title_key(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "as", "at", "from"}
    return " ".join(w for w in words if w not in stop)[:140]


def classify(title: str, snippet: str, default_category: str) -> tuple[str, str]:
    text = f"{title} {snippet}".lower()
    category = default_category
    if any(k in text for k in POLICY): category = "Policy"
    elif any(k in text for k in PLANTATION): category = "Plantation"
    elif any(k in text for k in MARKET): category = "Market"
    pos = sum(k in text for k in POSITIVE)
    neg = sum(k in text for k in NEGATIVE)
    impact = "Positive" if pos > neg else "Negative" if neg > pos else "Neutral"
    return category, impact


def source_from_title(title: str, fallback: str) -> tuple[str, str]:
    # Google News often appends the original publisher after " - ".
    if " - " in title:
        base, publisher = title.rsplit(" - ", 1)
        if 1 < len(publisher.split()) < 8:
            return base.strip(), publisher.strip()
    return title.strip(), fallback


def collect() -> tuple[list[dict], list[str]]:
    found, errors = [], []
    cutoff = datetime.now(timezone.utc) - timedelta(days=5)
    for source in SOURCES:
        try:
            response = requests.get(source["url"], timeout=22, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            feed = feedparser.parse(response.content.lstrip())
            if feed.bozo and not feed.entries:
                raise RuntimeError(str(feed.bozo_exception))
            for entry in feed.entries[:25]:
                title = clean_text(entry.get("title"))
                url = entry.get("link", "").strip()
                if not title or not url: continue
                published = parse_date(entry).astimezone(timezone.utc)
                if published < cutoff: continue
                raw = entry.get("summary") or entry.get("description") or ""
                snippet = clip_sentence(raw)
                clean_title, publisher = source_from_title(title, source["name"])
                category, impact = classify(clean_title, snippet, source["category"])
                country = source["country"]
                lower = f"{clean_title} {snippet}".lower()
                if "indonesia" in lower or "jakarta" in lower: country = "Indonesia"
                elif "malaysia" in lower or "mpob" in lower or "kuala lumpur" in lower: country = "Malaysia"
                found.append({
                    "id": title_key(clean_title), "title": clean_title, "url": url,
                    "source": publisher, "country": country, "category": category,
                    "impact": impact, "published_at": published.isoformat(),
                    "snippet": snippet, "summary": snippet, "summary_type": "extract"
                })
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")
    found.sort(key=lambda x: x["published_at"], reverse=True)
    unique, seen = [], set()
    for story in found:
        key = story["id"]
        tokens = set(key.split())
        duplicate = key in seen or any(len(tokens & set(old.split())) / max(1, len(tokens | set(old.split()))) > .82 for old in seen)
        if duplicate: continue
        seen.add(key); unique.append(story)
        if len(unique) >= MAX_STORIES: break
    return unique, errors


def gemini_summary(story: dict) -> str | None:
    if not KEY: return None
    prompt = f"""Summarize this palm-oil news item in 2 short factual sentences (maximum 60 words total). Use only the supplied text. Do not invent numbers, causes, or implications. If the text is insufficient, return exactly: INSUFFICIENT\n\nHeadline: {story['title']}\nPublisher preview: {story['snippet']}"""
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(MODEL, safe="") + ":generateContent?key=" + quote(KEY, safe="")
    payload = {"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.15,"maxOutputTokens":130}}
    response = None
    for attempt in range(3):
        response = requests.post(endpoint, json=payload, timeout=35, headers={"Content-Type":"application/json"})
        if response.status_code != 429 or attempt == 2:
            break
        retry_after = response.headers.get("Retry-After", "15")
        try: delay = max(10, min(int(retry_after), 45))
        except ValueError: delay = 15
        time.sleep(delay)
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text == "INSUFFICIENT" or len(text) < 30: return None
    return clean_text(text)


def apply_summaries(stories: list[dict]) -> list[str]:
    errors = []
    if not KEY: return errors
    for story in stories[:MAX_AI]:
        try:
            summary = gemini_summary(story)
            if summary:
                story["summary"] = summary
                story["summary_type"] = "ai"
            # Stay comfortably below typical free-tier request-per-minute limits.
            time.sleep(12)
        except Exception as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if status:
                errors.append(f"Gemini HTTP {status}; publisher preview used.")
            else:
                errors.append(f"Gemini request failed ({type(exc).__name__}); publisher preview used.")
            # Stop quickly on quota/auth errors; all remaining items keep extracts.
            if status in {400, 401, 403, 404, 429}: break
    return errors


def market_signal(stories: list[dict]) -> str:
    score = sum(1 if s["impact"] == "Positive" else -1 if s["impact"] == "Negative" else 0 for s in stories)
    return "Constructive" if score >= 3 else "Cautious" if score <= -3 else "Balanced"


def main() -> int:
    DATA.mkdir(exist_ok=True)
    stories, feed_errors = collect()
    existing = DATA / "latest.json"
    if not stories and existing.exists():
        print("No fresh stories; preserving existing edition.")
        print("\n".join(feed_errors), file=sys.stderr)
        return 0
    ai_errors = apply_summaries(stories)
    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(), "timezone": "Asia/Singapore",
        "market_signal": market_signal(stories), "story_count": len(stories),
        "gemini_enabled": bool(KEY), "stories": stories,
        # Store counts only. Exception strings can contain request URLs and secrets.
        "health": {"feed_error_count": len(feed_errors), "summary_error_count": len(ai_errors)}
    }
    if existing.exists():
        try:
            old = json.loads(existing.read_text(encoding="utf-8"))
            old_date = dateparser.parse(old.get("generated_at", "")).strftime("%Y-%m-%d")
            archive = DATA / "archive"; archive.mkdir(exist_ok=True)
            (archive / f"{old_date}.json").write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception: pass
    existing.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Published {len(stories)} stories; {sum(s['summary_type']=='ai' for s in stories)} AI summaries.")
    if feed_errors: print("Feed warnings:\n- " + "\n- ".join(feed_errors), file=sys.stderr)
    if ai_errors: print("Summary warnings:\n- " + "\n- ".join(ai_errors), file=sys.stderr)
    return 0

if __name__ == "__main__": raise SystemExit(main())

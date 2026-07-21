#!/usr/bin/env python3
"""Collect palm-oil RSS news, optionally summarize with Gemini, and write static JSON."""
from __future__ import annotations
import html, json, os, re, sys, time
from datetime import date, datetime, timedelta, timezone
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
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
MAX_STORIES = int(os.getenv("MAX_STORIES", "18"))
MAX_AI = int(os.getenv("MAX_AI_SUMMARIES", "18"))
USER_AGENT = "PalmPulse/1.0 (+personal news reader)"
LIVE_JSON = "https://zurplox.github.io/palm-pulse/data/latest.json"
MONTHS_ID = {"januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,"juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12}
TBS_FEEDS = [
    ("InfoSAWIT", "https://www.infosawit.com/feed/"),
    ("Google News · InfoSAWIT Riau", "https://news.google.com/rss/search?q=site%3Ainfosawit.com%20%22harga%20TBS%22%20Riau&hl=id&gl=ID&ceid=ID:id"),
    ("Google News · TBS Riau", "https://news.google.com/rss/search?q=%28%22harga%20TBS%22%20OR%20%22TBS%20sawit%22%29%20Riau&hl=id&gl=ID&ceid=ID:id"),
    ("Google News · TBS Siak", "https://news.google.com/rss/search?q=%28%22harga%20TBS%22%20OR%20%22TBS%20sawit%22%29%20Siak&hl=id&gl=ID&ceid=ID:id"),
    ("Google News · Official Riau", "https://news.google.com/rss/search?q=%28site%3Adisbun.riau.go.id%20OR%20site%3Ariau.go.id%20OR%20site%3Amediacenter.riau.go.id%29%20%22harga%20TBS%22&hl=id&gl=ID&ceid=ID:id"),
]

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


def clean_multiline(value: str | None) -> str:
    soup = BeautifulSoup(html.unescape(value or ""), "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


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


def call_gemini(model: str, prompt: str, max_tokens: int, preserve_lines: bool = False, json_mode: bool = False) -> str:
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(model, safe="") + ":generateContent?key=" + quote(KEY, safe="")
    generation = {"temperature":0.15,"maxOutputTokens":max_tokens}
    if json_mode: generation["responseMimeType"] = "application/json"
    payload = {"contents":[{"parts":[{"text":prompt}]}],"generationConfig":generation}
    response = None
    for attempt in range(2):
        response = requests.post(endpoint, json=payload, timeout=35, headers={"Content-Type":"application/json"})
        if response.status_code != 429 or attempt == 1:
            break
        retry_after = response.headers.get("Retry-After", "15")
        try: delay = max(10, min(int(retry_after), 20))
        except ValueError: delay = 15
        time.sleep(delay)
    response.raise_for_status()
    data = response.json()
    candidate = data["candidates"][0]
    finish_reason = candidate.get("finishReason")
    if finish_reason not in (None, "STOP"):
        raise RuntimeError(f"Gemini returned incomplete output ({finish_reason})")
    text = candidate["content"]["parts"][0]["text"].strip()
    return clean_multiline(text) if preserve_lines else clean_text(text)


def safe_ai_error(exc: Exception, context: str) -> str:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return f"{context}: Gemini HTTP {status}; publisher preview used." if status else f"{context}: Gemini request failed ({type(exc).__name__}); publisher preview used."


def fallback_master(stories: list[dict]) -> str:
    counts = {country: sum(s["country"] == country for s in stories) for country in ("Indonesia", "Malaysia", "Global")}
    headlines = "\n".join(f"- {s['title']}" for s in stories[:5])
    return f"EXECUTIVE OVERVIEW\n- Today's edition contains {len(stories)} palm-oil stories: {counts['Indonesia']} from Indonesia, {counts['Malaysia']} from Malaysia and {counts['Global']} global items.\n\nLEADING HEADLINES\n{headlines}\n\nIMPORTANT NOTE\n- AI synthesis was unavailable, so verify the publisher previews and original sources below."


def build_master_summary(stories: list[dict]) -> tuple[str, str, list[str], str | None]:
    if not KEY:
        return fallback_master(stories), "extract", [], None
    source_text = "\n".join(f"{i+1}. {s['title']} — {s['snippet']}" for i, s in enumerate(stories))
    prompt = f"""Create a comprehensive, highly structured morning master brief from the palm-oil news items below. Synthesize the major themes, Indonesia and Malaysia developments, CPO price drivers, policy changes, risks, and likely smallholder implications. Prioritize accuracy and distinguish confirmed facts from outlook or opinion. Do not invent facts.

Return plain text in EXACTLY this structure:
EXECUTIVE OVERVIEW
- bullet points

INDONESIA
- bullet points

MALAYSIA
- bullet points

PRICE & MARKET DRIVERS
- bullet points

SMALLHOLDER IMPLICATIONS
- bullet points

WATCHLIST
- bullet points

Use 2–5 concise bullets per section. Each bullet may contain multiple sentences when useful. Do not use Markdown headings, hashes, bold markers, tables, or numbered lists. Only section names and dash bullets.

NEWS ITEMS:
{source_text}"""
    errors = []
    for model in dict.fromkeys([MODEL, FALLBACK_MODEL]):
        if not model: continue
        try:
            text = call_gemini(model, prompt, 8192, preserve_lines=True)
            if len(text) >= 80:
                return text, "ai", errors, model
        except Exception as exc:
            errors.append(safe_ai_error(exc, f"Master summary ({model})"))
    return fallback_master(stories), "extract", errors, None


def apply_summaries(stories: list[dict], active_model: str | None) -> list[str]:
    errors = []
    if not KEY or not active_model: return errors
    selected = stories[:MAX_AI]
    source_items = [{"id": story["id"], "title": story["title"], "preview": story["snippet"]} for story in selected]
    prompt = f"""Summarize every palm-oil news item in the JSON input. Return ONLY a valid JSON array in the same order, with objects containing exactly two keys: id and summary. Each summary must contain 3 to 5 factual sentences, maximum 130 words, covering what happened, relevant details, and why it may matter. Use only the supplied title and publisher preview. Never invent facts; when details are limited, clearly say so rather than padding.

INPUT:
{json.dumps(source_items, ensure_ascii=False)}"""
    # The master summary is deliberately requested first. Pause before the
    # second and final AI request to stay within free-tier RPM limits.
    time.sleep(15)
    for model in dict.fromkeys([active_model, FALLBACK_MODEL]):
        if not model: continue
        try:
            raw = call_gemini(model, prompt, 16384, preserve_lines=True, json_mode=True)
            parsed = json.loads(raw)
            if isinstance(parsed, dict): parsed = parsed.get("summaries", [])
            by_id = {item.get("id"): item.get("summary") for item in parsed if isinstance(item, dict)}
            for story in selected:
                summary = clean_text(by_id.get(story["id"], ""))
                if len(summary) >= 30:
                    story["summary"] = summary
                    story["summary_type"] = "ai"
                    story["summary_model"] = model
            if any(story["summary_type"] == "ai" for story in selected):
                return errors
            raise RuntimeError("Gemini batch returned no usable summaries")
        except Exception as exc:
            errors.append(safe_ai_error(exc, f"Batch story summaries ({model})"))
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in {400, 401, 403, 404, 429, None}: break
    return errors


def parse_id_number(raw: str) -> float | None:
    raw = raw.strip().replace(" ", "")
    if "," in raw: raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") and all(len(p) == 3 for p in raw.split(".")[1:]): raw = raw.replace(".", "")
    try: return float(raw)
    except ValueError: return None


def parse_tbs_period(text: str) -> tuple[str, str] | None:
    text = re.sub(r"\s+", " ", text)
    patterns = [
        r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})",
        r"(\d{1,2})\s+([A-Za-z]+)\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, re.I)
        if not match: continue
        try:
            if index == 0:
                d1, d2, month, year = int(match[1]), int(match[2]), MONTHS_ID[match[3].lower()], int(match[4])
                return date(year, month, d1).isoformat(), date(year, month, d2).isoformat()
            d1, m1, d2, m2, year = int(match[1]), MONTHS_ID[match[2].lower()], int(match[3]), MONTHS_ID[match[4].lower()], int(match[5])
            return date(year, m1, d1).isoformat(), date(year, m2, d2).isoformat()
        except (KeyError, ValueError): pass
    return None


def parse_tbs_candidate(title: str, body: str, url: str, publisher: str, published: datetime) -> dict | None:
    text = clean_text(f"{title} {body}"); lower = text.lower()
    if "tbs" not in lower or not ("riau" in lower or "siak" in lower): return None
    period = parse_tbs_period(text)
    if not period: return None
    age_prices = {}
    for age in (4, 5, 6, 9):
        match = re.search(rf"(?:sawit\s*)?(?:umur|usia)\s*{age}\s*tahun\s*(?:[:=-]?\s*)?(?:Rp\.?\s*)?([\d.]+(?:,\d+)?)", text, re.I)
        value = parse_id_number(match[1]) if match else None
        if value is not None and 2000 <= value <= 8000: age_prices[str(age)] = round(value, 2)
    targeted = re.search(r"(?:umur|usia)\s*9\s*tahun.{0,260}?(?:menjadi|sebesar|mencapai|dipatok|harga)\s*(?:rp\.?\s*)?([\d.]+(?:,\d+)?)", text, re.I)
    if "9" not in age_prices and targeted:
        value = parse_id_number(targeted[1])
        if value is not None and 2000 <= value <= 8000: age_prices["9"] = round(value, 2)
    if not age_prices: return None
    price = age_prices.get("9") or age_prices.get("6") or age_prices.get("5") or age_prices.get("4")
    change_match = re.search(r"\b(naik|turun)\s*(?:sebesar\s*)?Rp\.?\s*([\d.]+(?:,\d+)?)", text, re.I)
    change = None
    if change_match:
        magnitude = parse_id_number(change_match[2])
        if magnitude is not None and magnitude < 1000: change = round(magnitude if change_match[1].lower() == "naik" else -magnitude, 2)
    scheme = "Swadaya" if "swadaya" in lower else "Plasma" if "plasma" in lower else "Umum"
    region = "Siak" if "siak" in title.lower() else "Riau"
    source_text = f"{publisher} {url}".lower()
    official = ("disbun", "riau.go.id", "siak.go.id", "media center riau", "pemprov riau", "diskominfo siak")
    priority = 0 if "infosawit" in source_text else 1 if any(x in source_text for x in official) else 2
    return {"region":region,"reference_for":None if region=="Siak" else "Siak","scheme":scheme,
            "palm_age_years":9,"price_rp_per_kg":round(price,2),"age_prices_rp_per_kg":age_prices,
            "change_rp_per_kg":change,"valid_from":period[0],"valid_to":period[1],
            "published_at":published.isoformat(),"source_name":publisher,"source_url":url,"source_priority":priority}


def previous_tbs_prices() -> list[dict]:
    for mode in ("live", "local"):
        try:
            if mode == "live":
                response = requests.get(LIVE_JSON, params={"t":int(time.time())}, timeout=12, headers={"Cache-Control":"no-cache","User-Agent":USER_AGENT})
                response.raise_for_status(); payload = response.json()
            else: payload = json.loads((DATA / "latest.json").read_text(encoding="utf-8"))
            values = payload.get("tbs_prices")
            if isinstance(values, list) and values: return values
        except Exception: pass
    return []


def collect_tbs_prices() -> tuple[list[dict], list[str]]:
    candidates, errors = [], []
    for feed_name, feed_url in TBS_FEEDS:
        try:
            response = requests.get(feed_url, timeout=22, headers={"User-Agent":USER_AGENT}); response.raise_for_status()
            feed = feedparser.parse(response.content.lstrip())
            for entry in feed.entries[:30]:
                title = clean_text(entry.get("title")); url = entry.get("link", "").strip(); content = entry.get("content") or []
                raw = entry.get("summary") or entry.get("description") or (content[0].get("value", "") if content else "")
                clean_title, publisher = source_from_title(title, feed_name)
                item = parse_tbs_candidate(clean_title, raw, url, publisher, parse_date(entry).astimezone(timezone.utc))
                if item: candidates.append(item)
        except Exception as exc: errors.append(f"{feed_name}: {type(exc).__name__}")
    chosen = []
    for scheme in ("Plasma", "Swadaya", "Umum"):
        pool = [x for x in candidates if x["scheme"] == scheme]
        pool.sort(key=lambda x:(x["valid_to"],-x["source_priority"],x["published_at"]), reverse=True)
        if pool:
            best = pool[0]; matches = {x["source_name"] for x in pool if x["valid_to"]==best["valid_to"] and abs(x["price_rp_per_kg"]-best["price_rp_per_kg"])<2}
            best["cross_checked_sources"] = len(matches); best["confidence"] = "infosawit" if best["source_priority"]==0 else "official" if best["source_priority"]==1 else "reported"; chosen.append(best)
    if not chosen: chosen = previous_tbs_prices()
    today = datetime.now(timezone.utc).date()
    for item in chosen:
        try:
            start,end=date.fromisoformat(item["valid_from"]),date.fromisoformat(item["valid_to"]); item["status"]="current_period" if start<=today<=end else "latest_available"
        except Exception: item["status"]="latest_available"
        change=item.get("change_rp_per_kg"); item["trend"]="up" if change and change>0 else "down" if change and change<0 else "flat"
        if change and item.get("price_rp_per_kg"):
            previous=item["price_rp_per_kg"]-change; item["change_percent"]=round(change/previous*100,2) if previous else None
        item.pop("source_priority",None)
    return chosen[:3], errors


def market_signal(stories: list[dict]) -> str:
    score = sum(1 if s["impact"] == "Positive" else -1 if s["impact"] == "Negative" else 0 for s in stories)
    return "Constructive" if score >= 3 else "Cautious" if score <= -3 else "Balanced"


def main() -> int:
    DATA.mkdir(exist_ok=True)
    stories, feed_errors = collect()
    tbs_prices, tbs_errors = collect_tbs_prices()
    existing = DATA / "latest.json"
    if not stories and existing.exists():
        print("No fresh stories; preserving existing edition.")
        print("\n".join(feed_errors), file=sys.stderr)
        return 0
    master_summary, master_type, master_errors, active_model = build_master_summary(stories)
    ai_errors = master_errors + apply_summaries(stories, active_model)
    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(), "timezone": "Asia/Singapore",
        "market_signal": market_signal(stories), "story_count": len(stories),
        "gemini_enabled": bool(KEY), "ai_model": active_model,
        "master_summary": master_summary, "master_summary_type": master_type,
        "ai_summary_count": sum(s["summary_type"] == "ai" for s in stories),
        "tbs_prices": tbs_prices, "tbs_price_updated_at": now.isoformat(),
        "stories": stories,
        # Store counts only. Exception strings can contain request URLs and secrets.
        "health": {"feed_error_count": len(feed_errors), "tbs_error_count": len(tbs_errors), "summary_error_count": len(ai_errors)}
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
    if tbs_errors: print("TBS warnings:\n- " + "\n- ".join(tbs_errors), file=sys.stderr)
    if ai_errors: print("Summary warnings:\n- " + "\n- ".join(ai_errors), file=sys.stderr)
    return 0

if __name__ == "__main__": raise SystemExit(main())

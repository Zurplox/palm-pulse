# Data contract for `data/latest.json`

This file is consumed by **two** clients:

1. The website in this repo (`assets/app.js`).
2. An **Android app** (Kotlin/Compose) with a home-screen widget, which parses
   this JSON with **Moshi + KotlinJsonAdapterFactory**.

The Android app is a separate codebase that cannot be updated in lockstep with
this repo, so this file is the boundary. `scripts/qa.py` enforces everything
below on every CI run and fails the build if it drifts.

## The two rules that matter

1. **Adding a field is safe.** Moshi ignores unknown JSON keys, so new keys
   (`price_source`, `health`, ...) are invisible to the app.
2. **Removing, renaming or nulling a field can crash the app.** Moshi throws
   `JsonDataException` when a non-null Kotlin property is missing or null.

## Fields that must never be missing or null

| JSON field | Kotlin type |
| --- | --- |
| `generated_at` | String |
| `story_count` | Int |
| `master_summary` | String |
| `stories` | List |
| `stories[].id` | String |
| `stories[].title` | String |
| `stories[].url` | String |
| `stories[].source` | String |
| `stories[].published_at` | String |

Everything else the app reads is nullable and may be omitted: `timezone`,
`market_signal`, `gemini_enabled`, `ai_model`, `master_summary_type`,
`ai_summary_count`, `tbs_prices`, `tbs_price_updated_at`, the optional story
fields, and every `tbs_prices[]` field.

## String vocabularies the app matches on

These are compared as strings inside the app. Changing the wording changes app
behaviour even though the JSON stays structurally valid.

- `market_signal`: exactly `Constructive`, `Cautious` or `Balanced`.
  The widget sentiment classifier scans this string for "positive", "negative",
  "bullish", "bearish", "menguat", "melemah". The current three values match
  **none** of those, so the signal contributes no score. Renaming `Constructive`
  to `Positive` would silently add weight to the widget outlook and change what
  users see. **Do not rename these.**
- `stories[].impact`: `Positive`, `Negative` or `Neutral`.
- `stories[].category`: builds the app's **filter chips** and its top-driver
  line. Any new or renamed category appears directly in the app UI.
- `stories[].summary_type`: `ai` or `extract` (the app shows an AI badge for `ai`).
- `tbs_prices[].trend`: `up`, `down` or `flat` (drives the arrow icon).
- `tbs_prices[].status`: `current_period` or `latest_available`.
- `tbs_prices[].scheme`: `Plasma`, `Swadaya` or `Umum`. The widget prefers
  `Swadaya`, then `Plasma`.

## Structural expectations

- **`master_summary` layout is load-bearing.** The widget headline is the first
  non-blank line of this string, and the app splits the body into sections. Keep
  the ALL-CAPS heading followed by bullet lines.
- **`age_prices_rp_per_kg` keys must be plain digit strings** ("4", "5", "6",
  "9") mapping to positive numbers. The app resolves a palm age by trying 5,
  then 6, then 4, then 9.
- **`generated_at` must match one of these shapes**, because the app parses it
  with a fixed list of SimpleDateFormat patterns: `yyyy-MM-dd'T'HH:mm:ss.SSS'Z'`,
  `yyyy-MM-dd'T'HH:mm:ss'Z'`, `yyyy-MM-dd'T'HH:mm:ssXXX`, `yyyy-MM-dd HH:mm:ss`,
  `yyyy-MM-dd`. An unparseable value makes the app treat the data as stale.
- **`valid_from` and `valid_to` must be strict `yyyy-MM-dd`** for the same reason.
- `stories[].url` and `tbs_prices[].source_url` must be http or https.

## Fields no current client reads

`data_quality`, `price_source`, `lang`, `health` and the whole of
`data/history.json` are ignored by both clients today. They are safe places to
add information, and safe to change.

## Before changing this feed

1. Run `python scripts/qa.py` locally.
2. If a breaking change is unavoidable, ship the Android app update **first**,
   then relax the matching check in `scripts/qa.py` in the same commit.

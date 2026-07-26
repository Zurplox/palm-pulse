# Palm Pulse 🌴

A polished, installable palm-oil news dashboard for Indonesia, Malaysia and global markets. GitHub Actions collects RSS stories every morning, optionally summarizes them with Gemini’s free API tier, and deploys the site to GitHub Pages.

## What you get

- Mobile-first PWA dashboard with light/dark themes
- Indonesia, Malaysia, market, policy and plantation filters
- Daily automated collection at **06:30 Singapore/Malaysia / 05:30 WIB**
- Structured master AI summary with bullet-point sections, generated before individual summaries
- Individual AI summaries expanded to 3–5 sentences
- Only two AI requests per run: master summary first, then all article summaries in one batch
- Automatic headline + publisher-preview fallback
- Deduplication, simple market-impact tags and JSON feed
- InfoSAWIT-first Riau/Siak TBS tracking for ages 4–6, with age 9 as a reference
- Built-in security and QA checks
- No Telegram and no server to maintain

## 1. Upload to GitHub

1. Create a new **public** GitHub repository.
2. Extract this ZIP and upload **the contents of the `palm-pulse` folder** to the repository root.
3. Commit to the `main` branch.

> Keep the `.github` folder. Your file manager may hide folders beginning with a dot.

## 2. Enable GitHub Pages

1. Open repository **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Open the **Actions** tab and run **Build daily palm-oil briefing** once.
4. Your dashboard will appear at `https://YOUR-USERNAME.github.io/YOUR-REPO/`.

## 3. Add Gemini (optional)

1. Create a free Gemini API key in Google AI Studio.
2. In the repository, open **Settings → Secrets and variables → Actions**.
3. Add a repository secret named exactly `GEMINI_API_KEY`.
4. Run the workflow again.

If the key is missing, invalid, rate-limited or out of free quota, the workflow still publishes the headline and RSS preview. No paid AI is required. Gemini errors are sanitized before generated data is saved, so API keys cannot be copied into `data/latest.json`.

Generated news is deployed directly to GitHub Pages and is **not pushed back to `main`**. This prevents non-fast-forward conflicts when multiple workflow runs overlap.

Summaries are written in **Bahasa Indonesia**. The model chain is `gemini-3.6-flash` → `gemini-3.5-flash` → `gemini-3.1-flash-lite`; the first model that responds wins. Override any step with the Actions **variables** `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL` or `GEMINI_FALLBACK_MODEL_2`.

## Customise sources

Edit `config/sources.json`. Each source needs:

```json
{"name":"Publisher","url":"https://example.com/feed/","country":"Indonesia","category":"Indonesia"}
```

Supported categories: `Indonesia`, `Malaysia`, `Market`, `Policy`, `Plantation`.

## TBS prices for Riau and Siak

For TBS only, Palm Pulse performs a fresh weekly discovery instead of using a fixed article URL. Every workflow run searches dedicated Google News RSS queries and the InfoSAWIT Riau feed for the newest Plasma and Swadaya pages, reconstructs the new direct InfoSAWIT URL, then fetches the article (including its AMP fallback) to extract the validity period and age table. Official Riau/Siak and InfoSAWIT Sumatera reports are used as cross-checks.

Ages 4, 5 and 6 are the primary field view, with age 9 retained as the standard comparison benchmark. If a newly discovered page is temporarily protected from crawling, Palm Pulse still flags its new period and calculates only the published age-9 movement from the previous confirmed benchmark; it never relabels older age 4–6 values as current. Every card links to the newly discovered source page.

## Local testing

```bash
python -m pip install -r requirements.txt
python scripts/fetch_news.py
python scripts/qa.py
python -m http.server 8000
```

Open `http://localhost:8000`. Do not open `index.html` directly if you want service-worker testing.

## Important notes

- The dashboard stores headlines, short summaries/previews and links—not full articles.
- Publisher websites may block extraction or change their feeds.
- Gemini’s free tier has limits and can change; the fallback is deliberate.
- AI summaries can be wrong. Verify important policy, legal and price decisions at the original source.
- HTTP 429 means the free Gemini quota is temporarily unavailable. The collector retries, then safely uses publisher previews.
- If GitHub previously blocked a push containing your key, rotate that key in AI Studio and update the GitHub secret.
- GitHub Pages is public. Never put your Gemini key in a file; use GitHub Secrets only.

## Files

- `index.html`, `assets/` — dashboard
- `data/latest.json` — latest app/API feed
- `data/archive/` — previous editions
- `scripts/fetch_news.py` — collection and summarisation
- `scripts/qa.py` — validation
- `.github/workflows/daily-news.yml` — schedule, QA and deployment

## License

Code is provided under the MIT License. News content remains the property of its publishers.

## Data contract with the Android app

`data/latest.json` is read by the website **and** by a separate Android app and
home-screen widget. See [CONTRACT.md](CONTRACT.md) for the exact fields,
vocabularies and timestamp formats that must not change, and why some odd-looking
values are deliberate. `scripts/qa.py` enforces the whole contract in CI, so a
breaking feed change fails the build instead of crashing the app.

## Data persistence

Generated data is committed to a separate `data` branch after each successful
deploy, and restored at the start of the next run. This is what makes
`data/archive/` and `data/history.json` genuinely accumulate; `data/latest.json`
on `main` is only a seed for the very first run.

If a run finds no fresh stories it republishes the last genuinely live edition
rather than the seed, and if even that is unavailable it fails so the previous
deployment stays in place. It will never present week-old news as today's edition.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | none | Enables AI summaries. Without it, extractive fallbacks are used. |
| `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_FALLBACK_MODEL_2` | see workflow | Model chain, tried in order. |
| `MAX_STORIES`, `MAX_AI_SUMMARIES` | 18 | Story and summary caps. |
| `AI_BATCH_SIZE` | 6 | Stories per summary request. Smaller batches survive token limits. |
| `AI_BATCH_PAUSE` | 15 | Seconds between AI requests, for free-tier rate limits. |
| `TBS_PRICE_MIN`, `TBS_PRICE_MAX` | 2000 / 8000 | Sanity band for TBS prices in Rp/kg. |
| `PAGES_BASE_URL` | derived from the repo | Overrides the published site URL used for price continuity. |
| `ARTICLE_MAX_ATTEMPTS` | 2 | Fetch attempts per InfoSAWIT article URL per run. The same article appears in several feeds; this stops the identical URL (and its timeouts) being retried once per feed, while still allowing one real retry if the site blocks the first try. Raise it to trade run time for price coverage. |

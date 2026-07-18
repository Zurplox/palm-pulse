# Palm Pulse 🌴

A polished, installable palm-oil news dashboard for Indonesia, Malaysia and global markets. GitHub Actions collects RSS stories every morning, optionally summarizes them with Gemini’s free API tier, and deploys the site to GitHub Pages.

## What you get

- Mobile-first PWA dashboard with light/dark themes
- Indonesia, Malaysia, market, policy and plantation filters
- Daily automated collection at **06:30 Singapore/Malaysia / 05:30 WIB**
- Optional 2-sentence Gemini summaries
- Automatic headline + publisher-preview fallback
- Deduplication, simple market-impact tags and JSON feed
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

The model defaults to `gemini-3.5-flash`, which currently has a Gemini API free tier. To override it, add an Actions **variable** called `GEMINI_MODEL` with another available model name.

## Customise sources

Edit `config/sources.json`. Each source needs:

```json
{"name":"Publisher","url":"https://example.com/feed/","country":"Indonesia","category":"Indonesia"}
```

Supported categories: `Indonesia`, `Malaysia`, `Market`, `Policy`, `Plantation`.

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

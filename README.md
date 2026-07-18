# Palm Pulse 🌴

An installable palm-oil news dashboard for Indonesia, Malaysia and global markets. GitHub Actions collects RSS stories daily, optionally summarizes them with Gemini’s free API tier, and publishes to GitHub Pages.

## Install

1. Create a new **public** GitHub repository.
2. Extract the ZIP and upload everything inside the `palm-pulse` folder, including `.github`.
3. Open **Settings → Pages** and choose **GitHub Actions** as the source.
4. Open **Actions → Build daily palm-oil briefing → Run workflow**.
5. Visit `https://YOUR-USERNAME.github.io/YOUR-REPO/`.

## Add free Gemini summaries

1. Create a Gemini API key in Google AI Studio.
2. Open **Repository Settings → Secrets and variables → Actions**.
3. Add a repository secret named exactly `GEMINI_API_KEY`.
4. Run the workflow again.

Gemini is optional. If the key is absent, blocked or out of free quota, the site automatically shows the publisher’s preview/first sentence. Never put the key directly in a file.

The default model is `gemini-2.5-flash-lite`. If Google changes its free models, add an Actions variable named `GEMINI_MODEL` with the new model name.

## Schedule

Runs daily at **06:30 Singapore/Malaysia / 05:30 WIB**. Change the cron in `.github/workflows/daily-news.yml` if required.

## Customise sources

Edit `config/sources.json`. The generated app data is available at `data/latest.json`, so a future Android app can use the same feed.

## Important

- Free API limits and model availability can change.
- Summaries can be wrong; verify important policy, legal and price decisions at the original source.
- Headlines and article content remain the property of their publishers.

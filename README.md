# PH Typhoon Watch

A small auto-updating dashboard tracking tropical cyclone activity for the Philippines.

**Live site:** https://ph-typhoon-watch.vercel.app

## What it shows

- **Current status** — whether a tropical cyclone is active within the Philippine Area of Responsibility (PAR), from PAGASA's official bulletin.
- **7-Day Typhoon Outlook** — PAGASA's "TC-Threat Potential" week-1/week-2 forecast summary (issued Mondays/Thursdays).
- **Activity Trend** — a daily timeline of clear vs. active days, built up from the site's own history since it started tracking.

The page auto-refreshes its data every 5 minutes (and whenever the tab regains focus), so it stays current without a manual reload.

## How it works

A GitHub Action (`.github/workflows/update.yml`) runs every 6 hours:

1. `scripts/update_status.py` fetches PAGASA's tropical cyclone bulletin page and writes `data.json`, and appends/updates today's entry in `history.json`.
2. `scripts/update_outlook.py` downloads PAGASA's TC-Threat Potential PDF and extracts the week-1/week-2 outlook text into `outlook.json`.
3. If anything changed, the Action commits and pushes it back to `main`.

The static site (`index.html`) fetches `data.json`, `outlook.json`, and `history.json` directly from `raw.githubusercontent.com` at load time — so the deployed Vercel build doesn't need to be redeployed for data to update, only when the page/logic itself changes.

## Sources

- [PAGASA Tropical Cyclone Bulletin](https://www.pagasa.dost.gov.ph/tropical-cyclone-bulletin-iframe)
- [PAGASA TC-Threat Potential (S2S) PDF](https://pubfiles.pagasa.dost.gov.ph/pagasaweb/files/climate/tcthreat/TC_Threat_and_S2S_Forecast.pdf)
- [JTWC](https://www.metoc.navy.mil/jtwc/jtwc.html) and [DeepMind Weather Lab](https://deepmind.google.com/science/weatherlab/) are linked for reference but not scraped (JTWC blocks automated requests; Weather Lab has no public data feed).

## Disclaimer

This is an unofficial personal project, not an official warning system. For official advisories, always refer to **PAGASA**.

## Local development

```
pip install -r requirements.txt
python3 scripts/update_status.py
python3 scripts/update_outlook.py
```

Then open `index.html` in a browser (it reads data from GitHub directly, not local files).

# PH Typhoon Watch

A small auto-updating dashboard tracking tropical cyclone activity for the Philippines.

**Live site:** https://ph-typhoon-watch.vercel.app

## What it shows

- **Current status** — whether a tropical cyclone is active within the Philippine Area of Responsibility (PAR), from PAGASA's official bulletin.
- **Activity Trend** — a daily timeline of clear vs. active days, built up from the site's own history since it started tracking.

The page auto-refreshes its data every 5 minutes (and whenever the tab regains focus), so it stays current without a manual reload.

## How it works

A GitHub Action (`.github/workflows/update.yml`) runs every 6 hours:

1. `scripts/update_status.py` fetches PAGASA's tropical cyclone bulletin page and writes `data.json`, and appends/updates today's entry in `history.json`.
2. If anything changed, the Action commits and pushes it back to `main`.

The static site (`index.html`) fetches `data.json` and `history.json` directly from `raw.githubusercontent.com` at load time — so the deployed Vercel build doesn't need to be redeployed for data to update, only when the page/logic itself changes.

## Sources

- [PAGASA Tropical Cyclone Bulletin](https://www.pagasa.dost.gov.ph/tropical-cyclone-bulletin-iframe)
- [JTWC](https://www.metoc.navy.mil/jtwc/jtwc.html) and [DeepMind Weather Lab](https://deepmind.google.com/science/weatherlab/) are linked for reference but not scraped (JTWC blocks automated requests; Weather Lab has no public data feed).

## Disclaimer

This is an unofficial personal project, not an official warning system. For official advisories, always refer to **PAGASA**.

## Local development

```
pip install -r requirements.txt
python3 scripts/update_status.py
```

Then open `index.html` in a browser (it reads data from GitHub directly, not local files).

# PH Typhoon Watch

A small auto-updating dashboard tracking tropical cyclone activity for the Philippines.

**Live site:** https://ph-typhoon-watch.vercel.app

## What it shows

- **Current status** — whether a tropical cyclone is active within the Philippine Area of Responsibility (PAR), from PAGASA's official bulletin.
- **Activity Trend** — a daily timeline of clear vs. active days, built up from the site's own history since it started tracking.
- **Flood Areas** — nationwide regional-center screening plus search for any Philippine locality,
  with Project NOAH links for detailed street/barangay hazard inspection.

The page auto-refreshes its data every 5 minutes (and whenever the tab regains focus), so it stays current without a manual reload.

## How it works

There are two independent status paths, both ultimately sourced from PAGASA's bulletin/advisory PDFs (discovered and parsed directly — the old `tropical-cyclone-bulletin-iframe` text page is unreliable and no longer trusted for status detection):

- **The Status tab** calls `/api/index` (a Vercel Python function) live on every page load — always current, no cron lag.
- **Activity Trend + alerts** are driven by a GitHub Action (`.github/workflows/update.yml`), scheduled every 15 minutes (GitHub throttles very frequent schedules in practice, so real-world runs land more like every 1–3 hours):
  1. `scripts/update_status.py` re-fetches the same PDF-based status and writes `data.json` + appends/updates today's entry in `history.json`.
  2. `scripts/update_flood_risk.py` builds a nationwide heavy-rain flood-risk snapshot.
  3. `scripts/send_alerts.py` sends alerts (see **Alerts** below) if the cyclone status is active,
     today's Metro Manila rain forecast crosses a threshold, or Luzon/Cebu flood-risk locations change.
  4. If anything changed, the Action commits and pushes it back to `main`.

The static site (`index.html`) fetches `data.json` and `history.json` directly from `raw.githubusercontent.com` for the Activity Trend — so the deployed Vercel build doesn't need to be redeployed for that data to update, only when the page/logic itself changes.

## Alerts

`scripts/send_alerts.py` fans each alert out to every configured channel:

- **Google Chat** — set the `GCHAT_WEBHOOK_URL` repo secret to an incoming webhook URL.
- **ntfy.sh** — set the `NTFY_TOPIC` repo secret to a topic name. Anyone who knows that exact topic name can subscribe to it (via the [ntfy app](https://ntfy.sh/app), `ntfy subscribe <topic>` on the CLI, or just visiting `https://ntfy.sh/<topic>` in a browser for web push) — that's the intended way for someone else to plug this into their own notification setup without needing repo access. Since topic names are only as private as "not publicly written down," don't commit the actual value anywhere, including here.

Flood-risk notifications initially cover monitored locations in **Luzon and Cebu**. The portal tab
shows a nationwide overview and can search any Philippine locality. These alerts are heavy-rain
screening signals, not confirmation that a road or barangay is currently flooded. Use the linked
Project NOAH map and local government emergency notices to confirm current conditions.

To add another channel (Discord, Slack, email, ...): add a `send_<channel>(text, title, priority, tags)` function in `send_alerts.py` following the same shape, then call it from `notify()`. The two alert conditions (`check_typhoon`, `check_rain`) don't need to change.

## Sources

- [PAGASA Tropical Cyclone Bulletin](https://www.pagasa.dost.gov.ph/tropical-cyclone-bulletin-iframe) / [severe weather bulletin PDFs](https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin)
- [Project NOAH area-level flood map](https://noah.up.edu.ph/know-your-hazards-realtimefloodmap)
- [JTWC](https://www.metoc.navy.mil/jtwc/jtwc.html) and [DeepMind Weather Lab](https://deepmind.google.com/science/weatherlab/) are linked for reference but not scraped (JTWC blocks automated requests; Weather Lab has no public data feed).

## Disclaimer

This is an unofficial personal project, not an official warning system. For official advisories, always refer to **PAGASA**.

## Local development

```
pip install -r requirements.txt
python3 scripts/update_status.py
```

Then open `index.html` in a browser (it reads data from GitHub directly, not local files).

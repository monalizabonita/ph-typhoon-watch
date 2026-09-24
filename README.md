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

There are two independent status paths, both ultimately sourced from PAGASA's bulletin PDFs
(discovered and parsed directly — the old `tropical-cyclone-bulletin-iframe` text page is
unreliable and no longer trusted for status detection). PAGASA Advisories describe systems
outside PAR and are not classified as active in-PAR cyclones. Exit bulletins are also classified
as clear:

- **The Status tab** calls `/api/index` (a Vercel Python function) live on every page load — always current, no cron lag.
- **Activity Trend + alerts** are driven by GitHub Actions. The full weather workflow
  (`.github/workflows/update.yml`) is scheduled every 15 minutes. A separate lightweight
  typhoon check (`.github/workflows/typhoon-alert.yml`) is staggered every 10 minutes so an
  urgent bulletin does not depend on the larger weather job's queue. GitHub schedules are
  best-effort and may still be delayed:
  1. `scripts/update_status.py` re-fetches the same PDF-based status and writes `data.json` + appends/updates today's entry in `history.json`.
  2. `scripts/update_flood_risk.py` builds a nationwide heavy-rain flood-risk snapshot.
  3. `scripts/update_flood_advisories.py` retrieves every active official PAGASA General Flood
     Advisory that covers Luzon or Cebu.
  4. `scripts/generate_flood_report.py` renders all advisory details into one high-resolution PNG.
  5. `scripts/send_alerts.py` sends alerts (see **Alerts** below) only if a fresh PAGASA Bulletin
     confirms the cyclone is active inside PAR,
     today's Metro Manila rain forecast crosses a threshold, official flood advisories change,
     or Luzon/Cebu flood-risk locations change.
  6. If anything changed, the Action commits and pushes it back to `main`.

The static site (`index.html`) fetches `data.json` and `history.json` directly from `raw.githubusercontent.com` for the Activity Trend — so the deployed Vercel build doesn't need to be redeployed for that data to update, only when the page/logic itself changes.

## Alerts

As of 2026-09-16, scheduled flood-advisory and flood-risk notifications are temporarily
paused on all channels. Typhoon and rain alerts remain active; flood data and reports
continue updating. To resume flood notifications, restore the advisory step's
`if: steps.flood_advisories.outcome == 'success'` condition and remove the flood-risk
step's `if: ${{ false }}` condition in `.github/workflows/update.yml`.

`scripts/send_alerts.py` fans each alert out to every configured channel:

Rain alerts include the next estimated rain window for Taguig in **PHT**, using
[Open-Meteo hourly forecasts](https://open-meteo.com/en/docs). Consecutive hours with
at least 60% precipitation probability or 0.1 mm forecast precipitation form a window;
timestamps represent the preceding hour. Only remaining windows today are considered.
An overlapping window says “possible now,” which is a forecast, not a rain observation.
Timing can shift and varies across Metro Manila. If hourly data is unavailable, the
daily alert still sends with an explicit timing-unavailable message. The existing
once-per-day schedule and alert threshold are unchanged.

- **Google Chat** — set the `GCHAT_WEBHOOK_URL` repo secret to an incoming webhook URL.
- **ntfy.sh** — set the `NTFY_TOPIC` repo secret to a topic name. Anyone who knows that exact topic name can subscribe to it (via the [ntfy app](https://ntfy.sh/app), `ntfy subscribe <topic>` on the CLI, or just visiting `https://ntfy.sh/<topic>` in a browser for web push) — that's the intended way for someone else to plug this into their own notification setup without needing repo access. Since topic names are only as private as "not publicly written down," don't commit the actual value anywhere, including here.

Flood-risk notifications initially cover monitored locations in **Luzon and Cebu**. The portal tab
shows a nationwide overview and can search any Philippine locality. Alerts include the complete
set of active official PAGASA General Flood Advisories for Luzon and Cebu, plus the fixed-location
heavy-rain screening signals. PAGASA may name only a province or metro area; city/barangay forecast
details are supplemental and are not confirmation that a road is currently flooded. The official
advisory notification includes `flood-alert-report.png`, a self-contained infographic with
all affected areas, named watercourses, PAGASA instructions, issued/valid times, and the source.
Use the linked Project NOAH map and local government emergency notices to confirm current conditions.

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

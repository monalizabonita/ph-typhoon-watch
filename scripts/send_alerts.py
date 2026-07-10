#!/usr/bin/env python3
"""Sends Google Chat webhook alerts for two conditions:
1. PAGASA reports an active tropical cyclone (data.json's pagasa_active) — alerted once per
   activation, not on every run, via alert_state.json.
2. Today's rain forecast (Open-Meteo, no API key needed) for Metro Manila/Taguig crosses a
   threshold — alerted once per day.

Requires GCHAT_WEBHOOK_URL as an environment variable (a GitHub Actions secret in CI — never
commit the webhook URL itself, since this repo is public).
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WEBHOOK_URL = os.environ.get("GCHAT_WEBHOOK_URL", "")

DATA_PATH = Path(__file__).resolve().parent.parent / "data.json"
STATE_PATH = Path(__file__).resolve().parent.parent / "alert_state.json"

# Taguig, Metro Manila
LATITUDE = 14.5176
LONGITUDE = 121.0509
RAIN_PROBABILITY_THRESHOLD = 60  # percent


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"typhoon_alerted": False, "rain_alerted_date": ""}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def send_gchat(text: str) -> None:
    if not WEBHOOK_URL:
        print("GCHAT_WEBHOOK_URL not set — skipping alert send.", file=sys.stderr)
        return
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        print(f"Failed to send Google Chat alert: {exc}", file=sys.stderr)


def fetch_rain_forecast() -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&daily=precipitation_probability_max,precipitation_sum"
        "&timezone=Asia%2FManila&forecast_days=1"
    )
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read())
    daily = data.get("daily", {})
    return {
        "date": (daily.get("time") or [""])[0],
        "probability": (daily.get("precipitation_probability_max") or [0])[0],
        "mm": (daily.get("precipitation_sum") or [0])[0],
    }


def check_typhoon(state: dict) -> dict:
    try:
        data = json.loads(DATA_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return state

    active = bool(data.get("pagasa_active"))
    if active and not state.get("typhoon_alerted"):
        send_gchat(
            "🌀 Typhoon alert: PAGASA reports an active tropical cyclone in the Philippine "
            f"Area of Responsibility.\n{data.get('pagasa_message', '')}"
        )
        state["typhoon_alerted"] = True
    elif not active:
        state["typhoon_alerted"] = False
    return state


def check_rain(state: dict) -> dict:
    manila_today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")
    if state.get("rain_alerted_date") == manila_today:
        return state

    try:
        forecast = fetch_rain_forecast()
    except Exception as exc:
        print(f"Failed to fetch rain forecast: {exc}", file=sys.stderr)
        return state

    if forecast["probability"] >= RAIN_PROBABILITY_THRESHOLD:
        send_gchat(
            f"🌧️ Rain alert for today ({forecast['date']}, Metro Manila): "
            f"{forecast['probability']}% chance of rain, ~{forecast['mm']}mm expected."
        )
        state["rain_alerted_date"] = manila_today
    return state


def main() -> int:
    state = load_state()
    state = check_typhoon(state)
    state = check_rain(state)
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sends alerts, fanned out to every configured channel, for two conditions:
1. PAGASA reports an active tropical cyclone (data.json's pagasa_active) — alerted once per
   activation, not on every run, via alert_state.json.
2. Today's rain forecast (Open-Meteo, no API key needed) for Metro Manila/Taguig crosses a
   threshold — alerted once per day.

Channels (each optional — skipped with a stderr note if its env var isn't set):
- Google Chat: GCHAT_WEBHOOK_URL (an incoming webhook URL)
- ntfy.sh: NTFY_TOPIC (a topic name — anyone who knows it can subscribe via the ntfy app/CLI/
  curl at https://ntfy.sh/<topic>; this is how a friend plugs in their own client)

To add another channel: write a send_<channel>(text, title, priority, tags) function following
the same shape, then add a call to it inside notify(). None of the existing channels need to
change.

All of these are environment variables (GitHub Actions secrets in CI) — never commit their
values, since this repo is public.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

GCHAT_WEBHOOK_URL = os.environ.get("GCHAT_WEBHOOK_URL", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else ""

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


def send_gchat(text: str, title: str, priority: str, tags: str) -> None:
    if not GCHAT_WEBHOOK_URL:
        print("GCHAT_WEBHOOK_URL not set — skipping Google Chat send.", file=sys.stderr)
        return
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        GCHAT_WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        print(f"Failed to send Google Chat alert: {exc}", file=sys.stderr)


def send_ntfy(text: str, title: str, priority: str, tags: str) -> None:
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set — skipping ntfy send.", file=sys.stderr)
        return
    req = urllib.request.Request(
        NTFY_URL,
        data=text.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        print(f"Failed to send ntfy alert: {exc}", file=sys.stderr)


def notify(text: str, *, title: str, priority: str = "default", tags: str = "") -> None:
    """Fans a single alert out to every configured channel."""
    send_gchat(text, title, priority, tags)
    send_ntfy(text, title, priority, tags)


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
        notify(
            "🌀 Typhoon alert: PAGASA reports an active tropical cyclone in the Philippine "
            f"Area of Responsibility.\n{data.get('pagasa_message', '')}",
            title="Typhoon Alert",
            priority="urgent",
            tags="cyclone,warning",
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
        notify(
            f"🌧️ Rain alert for today ({forecast['date']}, Metro Manila): "
            f"{forecast['probability']}% chance of rain, ~{forecast['mm']}mm expected.",
            title="Rain Alert",
            priority="default",
            tags="cloud_with_rain,umbrella",
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

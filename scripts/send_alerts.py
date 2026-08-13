#!/usr/bin/env python3
"""Sends alerts, fanned out to every configured channel, for three conditions:
1. PAGASA reports an active tropical cyclone (data.json's pagasa_active) — alerted once per
   day while it stays active, via alert_state.json.
2. Today's rain forecast (Open-Meteo, no API key needed) for Metro Manila/Taguig crosses a
   threshold — alerted once per day.
3. Official PAGASA General Flood Advisories cover any part of Luzon or Cebu — at most one flood
   notification per Manila calendar day.
4. Heavy-rain flood-risk screening flags Luzon or Cebu locations — also covered by the same
   once-per-day flood gate. This is explicitly described
   as potential risk and links to Project NOAH for area-level hazard inspection.

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
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

GCHAT_WEBHOOK_URL = os.environ.get("GCHAT_WEBHOOK_URL", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else ""

DATA_PATH = Path(__file__).resolve().parent.parent / "data.json"
STATE_PATH = Path(__file__).resolve().parent.parent / "alert_state.json"
FLOOD_RISK_PATH = Path(__file__).resolve().parent.parent / "flood_risk.json"
FLOOD_ADVISORIES_PATH = Path(__file__).resolve().parent.parent / "flood_advisories.json"
NOAH_FLOOD_URL = "https://noah.up.edu.ph/know-your-hazards-realtimefloodmap"
FLOOD_REPORT_URL = (
    "https://raw.githubusercontent.com/monalizabonita/ph-typhoon-watch/main/"
    "flood-alert-report.png"
)
FLOOD_SUMMARY_URL = (
    "https://raw.githubusercontent.com/monalizabonita/ph-typhoon-watch/main/"
    "flood-alert-summary.png"
)
FLOOD_ADVISORY_URL = (
    "https://raw.githubusercontent.com/monalizabonita/ph-typhoon-watch/main/"
    "flood-alert-advisory-{}.png"
)

# Taguig, Metro Manila
LATITUDE = 14.5176
LONGITUDE = 121.0509
RAIN_PROBABILITY_THRESHOLD = 60  # percent


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "typhoon_alerted_date": "",
            "rain_alerted_date": "",
            "flood_alerted_date": "",
            "flood_advisory_signature": "",
            "flood_risk_signature": "",
        }


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def manila_today() -> str:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")


def send_gchat(
    text: str, title: str, priority: str, tags: str, image_url: str = "",
    image_urls: Optional[List[str]] = None,
) -> None:
    if not GCHAT_WEBHOOK_URL:
        print("GCHAT_WEBHOOK_URL not set — skipping Google Chat send.", file=sys.stderr)
        return
    payload_data = {"text": text}
    display_images = image_urls or ([image_url] if image_url else [])
    if display_images:
        payload_data["cardsV2"] = [{
            "cardId": f"pagasa-flood-report-{index}",
            "card": {
                "header": {
                    "title": title if index == 1 else f"Flood advisory {index - 1}",
                    "subtitle": "Large inline report • No tap required",
                },
                "sections": [{"widgets": [{"image": {
                    "imageUrl": url,
                    "altText": "Complete PAGASA flood alert report",
                    "onClick": {"openLink": {"url": url}},
                }}]}],
            },
        } for index, url in enumerate(display_images, 1)]
    payload = json.dumps(payload_data).encode()
    req = urllib.request.Request(
        GCHAT_WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        print(f"Failed to send Google Chat alert: {exc}", file=sys.stderr)


def send_ntfy(text: str, title: str, priority: str, tags: str, image_url: str = "") -> None:
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set — skipping ntfy send.", file=sys.stderr)
        return
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Content-Type": "text/plain; charset=utf-8",
    }
    if image_url:
        headers["Attach"] = image_url
        headers["Filename"] = "pagasa-flood-alert-report.png"
    req = urllib.request.Request(
        NTFY_URL,
        data=text.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        print(f"Failed to send ntfy alert: {exc}", file=sys.stderr)


def notify(
    text: str, *, title: str, priority: str = "default", tags: str = "", image_url: str = "",
    image_urls: Optional[List[str]] = None,
) -> None:
    """Fans a single alert out to every configured channel."""
    send_gchat(text, title, priority, tags, image_url, image_urls)
    send_ntfy(text, title, priority, tags, image_url)


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
    today = manila_today()
    if active:
        if state.get("typhoon_alerted_date") != today:
            notify(
                "🌀 Typhoon alert: PAGASA reports an active tropical cyclone in the Philippine "
                f"Area of Responsibility.\n{data.get('pagasa_message', '')}",
                title="Typhoon Alert",
                priority="urgent",
                tags="cyclone,warning",
            )
            state["typhoon_alerted_date"] = today
    else:
        state["typhoon_alerted_date"] = ""
    return state


def check_rain(state: dict) -> dict:
    today = manila_today()
    if state.get("rain_alerted_date") == today:
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
        state["rain_alerted_date"] = today
    return state


def check_flood_risk(state: dict) -> dict:
    # Flood alerts are intentionally limited to one notification per Manila day. Keep this gate
    # shared with official advisories so the two flood sources cannot flood the group in one run.
    today = manila_today()
    if state.get("flood_alerted_date") == today:
        return state

    try:
        snapshot = json.loads(FLOOD_RISK_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return state

    flagged = [
        area for area in snapshot.get("areas", [])
        if area.get("region") in {"Luzon", "Cebu"} and area.get("risk") in {"WATCH", "HIGH"}
    ]
    signature = "|".join(
        f"{area['name']}:{area['risk']}" for area in sorted(flagged, key=lambda item: item["name"])
    )
    if not signature:
        state["flood_risk_signature"] = ""
        return state
    def barangay_label(area: dict) -> str:
        name = area.get("barangay")
        if not name:
            return ""
        prefix = "" if name.casefold().startswith(("barangay ", "brgy. ", "brgy ")) else "Brgy. "
        return f" — {prefix}{name}"

    lines = [
        f"• {area.get('city') or area['name']}"
        + barangay_label(area)
        + f", {area['province']}: {area['risk']} "
        f"({area['rain_probability']:.0f}% rain, ~{area['rain_mm']:.1f} mm)"
        for area in sorted(flagged, key=lambda item: (item["risk"] != "HIGH", -item["rain_mm"]))
    ]
    notify(
        "🌊 Potential flood-risk areas from heavy-rain screening (Luzon + Cebu):\n"
        + "\n".join(lines)
        + f"\n\nCheck the street/barangay hazard map in Project NOAH: {NOAH_FLOOD_URL}"
        + "\nThis is a forecast risk, not confirmation that an area is currently flooded.",
        title="PH Flood Risk Alert",
        priority="high" if any(area["risk"] == "HIGH" for area in flagged) else "default",
        tags="ocean,warning",
    )
    state["flood_risk_signature"] = signature
    state["flood_alerted_date"] = today
    return state


def check_flood_advisories(state: dict) -> dict:
    """Alert at most once per Manila calendar day for active official advisories."""
    today = manila_today()
    if state.get("flood_alerted_date") == today:
        return state

    try:
        snapshot = json.loads(FLOOD_ADVISORIES_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return state

    advisories = snapshot.get("advisories", [])
    signature = "|".join(sorted(
        f"{item.get('identifier', '')}:{item.get('severity', '')}:"
        f"{','.join(item.get('areas', []))}"
        for item in advisories
    ))
    if not signature:
        state["flood_advisory_signature"] = ""
        return state
    source_url = snapshot.get("source_url", "https://panahon.gov.ph/")
    report_url = FLOOD_REPORT_URL + "?v=" + urllib.parse.quote(snapshot.get("checked_at_utc", ""))
    notify(
        f"🌊 PAGASA Flood Alert Report — {len(advisories)} active advisories for Luzon + Cebu.\n"
        + "The attached image contains the complete affected areas, watercourses, validity times, "
        + f"instructions, and official source.\n{source_url}",
        title="Official PAGASA Flood Advisory",
        priority="urgent" if any(item.get("severity") == "EXTREME" for item in advisories) else "high",
        tags="ocean,warning",
        image_url=report_url,
    )
    state["flood_advisory_signature"] = signature
    state["flood_alerted_date"] = today
    return state


def main() -> int:
    state = load_state()
    state = check_typhoon(state)
    state = check_rain(state)
    state = check_flood_advisories(state)
    state = check_flood_risk(state)
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

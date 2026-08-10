#!/usr/bin/env python3
"""Build a nationwide heavy-rain flood-risk snapshot for the portal.

This is a screening signal, not a report of confirmed flooding. Project NOAH remains the
street/barangay-level hazard reference linked by the UI and alerts.
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent.parent / "flood_risk.json"
NOAH_URL = "https://noah.up.edu.ph/know-your-hazards-realtimefloodmap"

# Regional centers provide a quick nationwide overview. The tab also supports searching any
# Philippine locality, so the overview is not presented as exhaustive barangay coverage.
LOCATIONS = [
    ("Laoag", "Ilocos Norte", "Luzon", 18.1960, 120.5927),
    ("Baguio", "Benguet", "Luzon", 16.4023, 120.5960),
    ("Tuguegarao", "Cagayan", "Luzon", 17.6132, 121.7270),
    ("Baler", "Aurora", "Luzon", 15.7589, 121.5607),
    ("Angeles", "Pampanga", "Luzon", 15.1450, 120.5887),
    ("Metro Manila", "NCR", "Luzon", 14.5995, 120.9842),
    ("Marikina City", "NCR", "Luzon", 14.6481, 121.1133),
    ("Taguig", "NCR", "Luzon", 14.5176, 121.0509),
    ("Batangas City", "Batangas", "Luzon", 13.7565, 121.0583),
    ("Naga", "Camarines Sur", "Luzon", 13.6218, 123.1948),
    ("Legazpi", "Albay", "Luzon", 13.1391, 123.7438),
    ("Puerto Princesa", "Palawan", "Luzon", 9.7392, 118.7353),
    ("Cebu City", "Cebu", "Cebu", 10.3157, 123.8854),
    ("Mandaue", "Cebu", "Cebu", 10.3236, 123.9222),
    ("Lapu-Lapu", "Cebu", "Cebu", 10.3103, 123.9494),
    ("Danao", "Cebu", "Cebu", 10.5208, 124.0270),
    ("Toledo", "Cebu", "Cebu", 10.3770, 123.6386),
    ("Iloilo City", "Iloilo", "Visayas", 10.7202, 122.5621),
    ("Bacolod", "Negros Occidental", "Visayas", 10.6765, 122.9509),
    ("Tacloban", "Leyte", "Visayas", 11.2447, 125.0036),
    ("Tagbilaran", "Bohol", "Visayas", 9.6496, 123.8530),
    ("Davao City", "Davao del Sur", "Mindanao", 7.1907, 125.4553),
    ("Cagayan de Oro", "Misamis Oriental", "Mindanao", 8.4542, 124.6319),
    ("Zamboanga City", "Zamboanga del Sur", "Mindanao", 6.9214, 122.0790),
    ("Butuan", "Agusan del Norte", "Mindanao", 8.9475, 125.5406),
    ("General Santos", "South Cotabato", "Mindanao", 6.1164, 125.1716),
]


def risk_level(probability: float, rain_mm: float) -> str:
    if probability >= 80 and rain_mm >= 50:
        return "HIGH"
    if probability >= 60 and rain_mm >= 20:
        return "WATCH"
    return "LOW"


def load_existing_places() -> dict:
    try:
        previous = json.loads(OUT_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        area.get("name"): {
            "city": area.get("city"), "barangay": area.get("barangay"),
            "geocoded": area.get("geocoded", False),
        }
        for area in previous.get("areas", [])
    }


def reverse_geocode(latitude: float, longitude: float) -> dict:
    params = urllib.parse.urlencode({
        "lat": latitude, "lon": longitude, "format": "jsonv2", "zoom": 18, "addressdetails": 1,
    })
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/reverse?{params}",
        headers={"User-Agent": "PH-Typhoon-Watch/1.0 (personal weather alert portal)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        address = json.loads(response.read()).get("address", {})
    return {
        "city": address.get("city") or address.get("town") or address.get("municipality"),
        "barangay": (
            address.get("village") or address.get("quarter") or address.get("suburb")
            or address.get("neighbourhood")
        ),
    }


def main() -> int:
    existing_places = load_existing_places()
    params = urllib.parse.urlencode({
        "latitude": ",".join(str(item[3]) for item in LOCATIONS),
        "longitude": ",".join(str(item[4]) for item in LOCATIONS),
        "daily": "precipitation_probability_max,precipitation_sum",
        "timezone": "Asia/Manila",
        "forecast_days": 1,
    })
    req = urllib.request.Request(
        f"https://api.open-meteo.com/v1/forecast?{params}",
        headers={"User-Agent": "PH-Typhoon-Watch/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        forecasts = json.loads(response.read())
    if isinstance(forecasts, dict):
        forecasts = [forecasts]

    areas = []
    for location, forecast in zip(LOCATIONS, forecasts):
        city, province, region, latitude, longitude = location
        daily = forecast.get("daily", {})
        probability = float((daily.get("precipitation_probability_max") or [0])[0] or 0)
        rain_mm = float((daily.get("precipitation_sum") or [0])[0] or 0)
        risk = risk_level(probability, rain_mm)
        place = existing_places.get(city, {})
        if risk in {"WATCH", "HIGH"} and not place.get("geocoded"):
            try:
                place = reverse_geocode(latitude, longitude)
                place["geocoded"] = True
                time.sleep(1.1)  # Respect the public geocoder's low-volume usage requirement.
            except Exception:
                place = place or {}
        areas.append({
            "name": city,
            "city": place.get("city") or city,
            "barangay": place.get("barangay"),
            "geocoded": bool(place.get("geocoded")),
            "province": province,
            "region": region,
            "latitude": latitude,
            "longitude": longitude,
            "date": (daily.get("time") or [""])[0],
            "rain_probability": probability,
            "rain_mm": rain_mm,
            "risk": risk,
        })

    payload = {
        "checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "Heavy-rain screening; not confirmed flooding",
        "noah_url": NOAH_URL,
        "areas": areas,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

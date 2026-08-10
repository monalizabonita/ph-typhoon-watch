#!/usr/bin/env python3
"""Fetch active PAGASA General Flood Advisories from the official PANaHON CAP feed."""
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PAGE_URL = "https://panahon.gov.ph/?trg=iframe&req=public-alerts.gfa"
API_URL = "https://panahon.gov.ph/api/v1/cap-alerts"
OUT_PATH = Path(__file__).resolve().parent.parent / "flood_advisories.json"
UA = "PH-Typhoon-Watch/1.0 (personal weather alert portal)"

LUZON_AND_CEBU = {
    "Abra", "Albay", "Apayao", "Aurora", "Bataan", "Batanes", "Batangas", "Benguet",
    "Bulacan", "Cagayan", "Camarines Norte", "Camarines Sur", "Catanduanes", "Cavite",
    "Ifugao", "Ilocos Norte", "Ilocos Sur", "Isabela", "Kalinga", "La Union", "Laguna",
    "Marinduque", "Masbate", "Metro Manila", "Mountain Province", "National Capital Region",
    "NCR", "Nueva Ecija", "Nueva Vizcaya", "Occidental Mindoro", "Oriental Mindoro",
    "Palawan", "Pampanga", "Pangasinan", "Quezon", "Quirino", "Rizal", "Romblon",
    "Sorsogon", "Tarlac", "Zambales", "Cebu",
}


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def fetch_alerts() -> list:
    request = urllib.request.Request(PAGE_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        page = response.read().decode("utf-8", errors="replace")
    token_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    if not token_match:
        raise ValueError("PAGASA CAP token was not found")
    payload = get_json(f"{API_URL}?{urllib.parse.urlencode({'token': token_match.group(1)})}")
    return payload.get("data", {}).get("alert_data", [])


def advisory_areas(record: dict) -> list[str]:
    areas = [item.get("areaDesc") or item.get("province") for item in record.get("provinces", [])]
    if not areas:
        areas = re.findall(r"\*\*([^*]+)\*\*\s*-", record.get("message", ""))
    return sorted({html.unescape(area).strip() for area in areas if area})


def severity(subtype: str) -> str:
    match = re.search(r"\(([^)]+)\)", subtype or "")
    return match.group(1).upper() if match else "ADVISORY"


def main() -> int:
    advisories = []
    for record in fetch_alerts():
        if str(record.get("event", "")).upper() != "FLOOD":
            continue
        areas = advisory_areas(record)
        covered = sorted(set(areas) & LUZON_AND_CEBU)
        if not covered:
            continue
        advisories.append({
            "identifier": record.get("identifier"),
            "severity": severity(record.get("subtype", "")),
            "areas": covered,
            "all_areas": areas,
            "message": record.get("message", ""),
            "instruction": record.get("optional_message", ""),
            "issued_at": record.get("issued_date"),
            "valid_until": record.get("valid_date"),
            "published_by": record.get("published_by", "PAGASA-DOST"),
        })

    payload = {
        "checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_url": PAGE_URL,
        "coverage": "All active PAGASA General Flood Advisories intersecting Luzon or Cebu",
        "advisories": advisories,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

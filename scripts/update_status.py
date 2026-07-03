#!/usr/bin/env python3
"""Fetch PAGASA's tropical cyclone bulletin and write data.json for the static site."""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PAGASA_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone-bulletin-iframe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT_PATH = Path(__file__).resolve().parent.parent / "data.json"

NO_ACTIVE_PHRASE = "no active tropical cyclone"


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_bulletin() -> str:
    req = urllib.request.Request(PAGASA_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_bulletin_text(html: str) -> str:
    match = re.search(r'class="[^"]*article-content[^"]*"(.*)', html, re.DOTALL)
    chunk = match.group(1) if match else html
    chunk = chunk[:4000]
    return strip_tags(chunk)


def main() -> int:
    try:
        html = fetch_bulletin()
    except Exception as exc:  # network hiccups shouldn't break the whole pipeline
        print(f"Failed to fetch PAGASA bulletin: {exc}", file=sys.stderr)
        return 0

    text = extract_bulletin_text(html)
    is_clear = NO_ACTIVE_PHRASE in text.lower()

    if is_clear:
        message = "No Active Tropical Cyclone within the Philippine Area of Responsibility"
    else:
        message = text[:600] if text else "Active tropical cyclone bulletin in effect — see PAGASA for details."

    data = {
        "last_checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pagasa_active": not is_clear,
        "pagasa_message": message,
        "source_url": PAGASA_URL,
    }

    OUT_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

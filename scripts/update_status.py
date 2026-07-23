#!/usr/bin/env python3
"""Fetch PAGASA's tropical cyclone status and write data.json for the static site + alert pipeline.

Uses the same PDF bulletin/advisory-based detection as api/index.py (see that file's docstring
for the full story) rather than text-scraping the tropical-cyclone-bulletin-iframe page — that
page is a JS/map-rendered widget that was found to NOT reliably reflect current status; it can
keep showing "no active tropical cyclone" even with a live, numbered bulletin in effect.

This script can't simply import api/index.py's logic: GitHub Actions runs this file from the repo
root, while Vercel bundles api/ as its own isolated serverless function, so the two run in
different deployment contexts. The detection logic below is intentionally kept in sync with
api/index.py by hand -- if you change the parsing there, mirror it here too.
"""
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfReader

ADVISORY_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone-advisory-iframe"
ADVISORY_PDF_URL = "https://pubfiles.pagasa.dost.gov.ph/tamss/weather/tcadvisory.pdf"
BULLETIN_DISCOVERY_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin"
BULLETIN_LINK_RE = re.compile(
    r"https://pubfiles\.pagasa\.dost\.gov\.ph/tamss/weather/bulletin_[a-z]+\.pdf", re.IGNORECASE
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DOC_STALE_AFTER = timedelta(hours=48)  # bulletins/advisories are typically reissued every 6-12h while active

OUT_PATH = Path(__file__).resolve().parent.parent / "data.json"
HISTORY_PATH = Path(__file__).resolve().parent.parent / "history.json"
HISTORY_MAX_DAYS = 90


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch_pdf_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def parse_tc_document(full_text: str):
    header_match = re.search(
        r"TROPICAL CYCLONE (ADVISORY|BULLETIN) NR\.\s*(\S+)\s+(.*?)\s+Issued at\s+([^\n]+)", full_text
    )
    if not header_match:
        raise ValueError("Could not find advisory/bulletin header in PDF text")

    doc_type, _number, storm_name, issued_at_raw = header_match.groups()
    headline_match = re.search(r"Page 1 of \d+\s*\n\s*(.*?\.)\s*\n", full_text, re.DOTALL)

    issued_at_raw = clean_text(issued_at_raw)
    issued_at = None
    try:
        issued_at = datetime.strptime(issued_at_raw, "%I:%M %p, %d %B %Y").replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:
        pass

    doc = {
        "doc_type": doc_type.title(),
        "storm_name": clean_text(storm_name),
        "headline": clean_text(headline_match.group(1)) if headline_match else None,
    }
    return doc, issued_at


def fetch_and_parse_pdf(pdf_url: str):
    """Returns a parsed doc dict if the PDF exists and is recent enough to still be current, else
    None -- bulletin/advisory PDF URLs are static (PAGASA overwrites them with each new issuance),
    so a stale leftover file from a past, now-finished system is expected once things go quiet."""
    pdf_bytes = fetch_pdf_bytes(pdf_url)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(p.extract_text() for p in reader.pages)
    doc, issued_at = parse_tc_document(full_text)
    if issued_at is not None:
        age = datetime.now(timezone.utc) - issued_at.astimezone(timezone.utc)
        if age > DOC_STALE_AFTER:
            return None
    return doc


def discover_bulletin_pdf_url():
    """The severe-weather-bulletin page links to a static 'latest bulletin' PDF for whichever
    storm is currently active (e.g. bulletin_inday.pdf) -- its filename changes with the storm's
    local name, so it has to be discovered fresh each time rather than hardcoded."""
    req = urllib.request.Request(BULLETIN_DISCOVERY_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    match = BULLETIN_LINK_RE.search(html)
    return match.group(0) if match else None


def fetch_active_document():
    """A Bulletin (system already inside PAR) takes priority over an Advisory (system still
    outside PAR, being watched ahead of a possible PAR entry) since it's the more urgent/current
    product. Returns (doc_or_None, error_or_None)."""
    try:
        bulletin_url = discover_bulletin_pdf_url()
        if bulletin_url:
            doc = fetch_and_parse_pdf(bulletin_url)
            if doc:
                return doc, None
    except Exception:
        pass  # fall through to the advisory

    try:
        doc = fetch_and_parse_pdf(ADVISORY_PDF_URL)
        return doc, None
    except Exception as exc:
        return None, str(exc)


def update_history(manila_date: str, is_active: bool, message: str) -> None:
    try:
        history = json.loads(HISTORY_PATH.read_text())
        if not isinstance(history, list):
            history = []
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    entry = {"date": manila_date, "active": is_active, "message": message}
    history = [h for h in history if h.get("date") != manila_date]
    history.append(entry)
    history.sort(key=lambda h: h["date"])
    history = history[-HISTORY_MAX_DAYS:]

    HISTORY_PATH.write_text(json.dumps(history, indent=2) + "\n")


def main() -> int:
    doc, err = fetch_active_document()

    if err:
        # Couldn't reach PAGASA -- leave the last-known-good data.json in place rather than
        # overwriting it with a false "clear" on a transient network hiccup.
        print(f"Failed to fetch PAGASA status: {err}", file=sys.stderr)
        return 0

    is_active = doc is not None
    if is_active:
        message = doc.get("headline") or f"{doc['doc_type']} in effect for {doc['storm_name']}."
    else:
        message = "No Active Tropical Cyclone within the Philippine Area of Responsibility"

    now_utc = datetime.now(timezone.utc)
    manila_date = now_utc.astimezone(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")

    data = {
        "last_checked_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pagasa_active": is_active,
        "pagasa_message": message,
        "source_url": BULLETIN_DISCOVERY_URL,
        "advisory_url": ADVISORY_URL,
    }

    OUT_PATH.write_text(json.dumps(data, indent=2) + "\n")
    update_history(manila_date, is_active, message)
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

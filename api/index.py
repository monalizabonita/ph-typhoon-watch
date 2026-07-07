"""Live PAGASA tropical cyclone status — fetched fresh on every request (no cron lag).

Note: the 7-day outlook (TC-Threat PDF) is intentionally NOT live-fetched here — that PDF
download was measured to take 150-180s from this environment (the bulletin page fetch is
comparatively fast, well under 10s), which is unsafe for a per-request serverless call. The
outlook instead relies on scripts/update_outlook.py running frequently via cron.

The Tropical Cyclone Advisory PDF (for systems tracked outside the PAR, before they're named
and given a bulletin inside it) IS live-fetched here — it's small and fast (well under 1s).
"""
import io
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

from pypdf import PdfReader

PAGASA_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone-bulletin-iframe"
ADVISORY_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone-advisory-iframe"
ADVISORY_PDF_URL = "https://pubfiles.pagasa.dost.gov.ph/tamss/weather/tcadvisory.pdf"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

NO_ACTIVE_PHRASE = "no active tropical cyclone"
ADVISORY_STALE_AFTER = timedelta(hours=48)  # advisories are typically reissued every 12h while active


def strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_bulletin() -> str:
    req = urllib.request.Request(PAGASA_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_bulletin_text(html: str) -> str:
    match = re.search(r'class="[^"]*article-content[^"]*"(.*)', html, re.DOTALL)
    chunk = match.group(1) if match else html
    chunk = chunk[:4000]
    return strip_tags(chunk)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch_advisory_pdf() -> bytes:
    req = urllib.request.Request(ADVISORY_PDF_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def parse_advisory(full_text: str) -> dict:
    header_match = re.search(r"TROPICAL CYCLONE ADVISORY NR\.\s*(\S+)\s+(.*?)\s+Issued at\s+([^\n]+)", full_text)
    if not header_match:
        raise ValueError("Could not find advisory header in PDF text")

    headline_match = re.search(r"Page 1 of 2\s*\n\s*(.*?\.)\s*\n", full_text, re.DOTALL)
    location_match = re.search(r"Location of Center[^\n]*\n(.*?)\nIntensity", full_text, re.DOTALL)
    intensity_match = re.search(r"Intensity\s*\n(.*?)\nPresent Movement", full_text, re.DOTALL)
    movement_match = re.search(r"Present Movement\s*\n(.*?)\nExtent of Tropical Cyclone Winds", full_text, re.DOTALL)
    outlook_match = re.search(r"GENERAL OUTLOOK FOR THE FORECAST PERIOD\s*(.*?)(?:DOST-PAGASA\s*$|\Z)", full_text, re.DOTALL)

    bullets = []
    if outlook_match:
        bullets = [clean_text(p) for p in re.split(r"•", outlook_match.group(1)) if clean_text(p)]

    issued_at_raw = clean_text(header_match.group(3))
    issued_at = None
    try:
        issued_at = datetime.strptime(issued_at_raw, "%I:%M %p, %d %B %Y").replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:
        pass

    return {
        "advisory_number": header_match.group(1),
        "storm_name": clean_text(header_match.group(2)),
        "issued_at_raw": issued_at_raw,
        "issued_at_utc": issued_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if issued_at else None,
        "headline": clean_text(headline_match.group(1)) if headline_match else None,
        "location": clean_text(location_match.group(1)) if location_match else None,
        "intensity": clean_text(intensity_match.group(1)) if intensity_match else None,
        "movement": clean_text(movement_match.group(1)) if movement_match else None,
        "bullets": bullets,
        "pdf_url": ADVISORY_PDF_URL,
    }, issued_at


def fetch_advisory():
    """Returns a parsed advisory dict if one exists and is recent enough to still be current,
    else None. The PDF URL is static (PAGASA overwrites it with each new advisory), so a stale
    file left over from a past, now-finished system is expected once things go quiet again."""
    pdf_bytes = fetch_advisory_pdf()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(p.extract_text() for p in reader.pages)
    parsed, issued_at = parse_advisory(full_text)
    if issued_at is not None:
        age = datetime.now(timezone.utc) - issued_at.astimezone(timezone.utc)
        if age > ADVISORY_STALE_AFTER:
            return None
    return parsed


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        now_utc = datetime.now(timezone.utc)
        data = {
            "last_checked_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "advisory_url": ADVISORY_URL,
            "live": True,
        }

        try:
            html = fetch_bulletin()
            text = extract_bulletin_text(html)
            is_clear = NO_ACTIVE_PHRASE in text.lower()
            data["pagasa_active"] = not is_clear
            data["pagasa_message"] = (
                "No Active Tropical Cyclone within the Philippine Area of Responsibility" if is_clear
                else (text[:600] if text else "Active tropical cyclone bulletin in effect — see PAGASA for details.")
            )
            data["source_url"] = PAGASA_URL
        except Exception as exc:
            data["status_error"] = f"Could not reach PAGASA status right now: {exc}"

        try:
            data["advisory"] = fetch_advisory()
        except Exception as exc:
            data["advisory_error"] = f"Could not reach PAGASA advisory right now: {exc}"

        status_code = 200 if ("pagasa_active" in data or "advisory" in data) else 502
        self._json(status_code, data)

    def _json(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

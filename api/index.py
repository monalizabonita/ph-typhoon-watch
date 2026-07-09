"""Live PAGASA tropical cyclone status — fetched fresh on every request (no cron lag).

Note: the 7-day outlook (TC-Threat PDF) is intentionally NOT live-fetched here — that PDF
download was measured to take 150-180s from this environment, which is unsafe for a per-request
serverless call. The outlook instead relies on scripts/update_outlook.py running frequently via
cron.

The tropical-cyclone-bulletin-iframe / tropical-cyclone-advisory-iframe pages are JS/map-rendered
widgets that were found to NOT reliably reflect current status via simple text scraping (they
kept showing "no active tropical cyclone" even with a live, numbered bulletin in effect). The
reliable source is PAGASA's own PDF bulletins/advisories, discovered dynamically from the
severe-weather-bulletin page and parsed directly — both are small and fast (well under 1s each).
"""
import io
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

from pypdf import PdfReader

ADVISORY_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone-advisory-iframe"
ADVISORY_PDF_URL = "https://pubfiles.pagasa.dost.gov.ph/tamss/weather/tcadvisory.pdf"
BULLETIN_DISCOVERY_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin"
BULLETIN_LINK_RE = re.compile(
    r"https://pubfiles\.pagasa\.dost\.gov\.ph/tamss/weather/bulletin_[a-z]+\.pdf", re.IGNORECASE
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

DOC_STALE_AFTER = timedelta(hours=48)  # bulletins/advisories are typically reissued every 6-12h while active


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch_pdf_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def parse_tc_document(full_text: str) -> dict:
    """Parses either a TROPICAL CYCLONE ADVISORY or TROPICAL CYCLONE BULLETIN PDF — the two
    share the same overall layout (header, headline, Location/Intensity/Movement, a closing
    outlook section with bullet points), just with different section labels and, in some PDFs,
    a different bullet glyph."""
    header_match = re.search(
        r"TROPICAL CYCLONE (ADVISORY|BULLETIN) NR\.\s*(\S+)\s+(.*?)\s+Issued at\s+([^\n]+)", full_text
    )
    if not header_match:
        raise ValueError("Could not find advisory/bulletin header in PDF text")

    doc_type, number, storm_name, issued_at_raw = header_match.groups()
    headline_match = re.search(r"Page 1 of \d+\s*\n\s*(.*?\.)\s*\n", full_text, re.DOTALL)
    location_match = re.search(r"Location of Center[^\n]*\n(.*?)\nIntensity", full_text, re.DOTALL)
    intensity_match = re.search(r"Intensity\s*\n(.*?)\nPresent Movement", full_text, re.DOTALL)
    movement_match = re.search(r"Present Movement\s*\n(.*?)\nExtent of Tropical Cyclone Winds", full_text, re.DOTALL)
    outlook_match = re.search(
        r"(?:GENERAL OUTLOOK FOR THE FORECAST PERIOD|TRACK AND INTENSITY OUTLOOK)\s*(.*?)\Z", full_text, re.DOTALL
    )

    bullets = []
    if outlook_match:
        bullets = [clean_text(p) for p in re.split(r"[•]", outlook_match.group(1)) if clean_text(p)]

    issued_at_raw = clean_text(issued_at_raw)
    issued_at = None
    try:
        issued_at = datetime.strptime(issued_at_raw, "%I:%M %p, %d %B %Y").replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:
        pass

    return {
        "doc_type": doc_type.title(),
        "advisory_number": number,
        "storm_name": clean_text(storm_name),
        "issued_at_raw": issued_at_raw,
        "issued_at_utc": issued_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if issued_at else None,
        "headline": clean_text(headline_match.group(1)) if headline_match else None,
        "location": clean_text(location_match.group(1)) if location_match else None,
        "intensity": clean_text(intensity_match.group(1)) if intensity_match else None,
        "movement": clean_text(movement_match.group(1)) if movement_match else None,
        "bullets": bullets,
    }, issued_at


def fetch_and_parse_pdf(pdf_url: str):
    """Returns a parsed doc dict if the PDF exists and is recent enough to still be current, else
    None. Bulletin/advisory PDF URLs are static (PAGASA overwrites them with each new issuance),
    so a stale file left over from a past, now-finished system is expected once things go quiet."""
    pdf_bytes = fetch_pdf_bytes(pdf_url)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(p.extract_text() for p in reader.pages)
    parsed, issued_at = parse_tc_document(full_text)
    parsed["pdf_url"] = pdf_url
    if issued_at is not None:
        age = datetime.now(timezone.utc) - issued_at.astimezone(timezone.utc)
        if age > DOC_STALE_AFTER:
            return None
    return parsed


def discover_bulletin_pdf_url():
    """The severe-weather-bulletin page links to a static 'latest bulletin' PDF for whichever
    storm is currently active (e.g. bulletin_inday.pdf) — its filename changes with the storm's
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


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        now_utc = datetime.now(timezone.utc)
        data = {
            "last_checked_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "advisory_url": ADVISORY_URL,
            "live": True,
        }

        doc, err = fetch_active_document()
        if err:
            data["advisory_error"] = f"Could not reach PAGASA right now: {err}"
            data["pagasa_active"] = False
            data["pagasa_message"] = "Could not determine current status — see PAGASA for details."
        elif doc:
            data["advisory"] = doc
            data["pagasa_active"] = True
            data["pagasa_message"] = doc.get("headline") or f"{doc['doc_type']} in effect for {doc['storm_name']}."
        else:
            data["advisory"] = None
            data["pagasa_active"] = False
            data["pagasa_message"] = "No Active Tropical Cyclone within the Philippine Area of Responsibility"

        self._json(200, data)

    def _json(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

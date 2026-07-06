"""Live PAGASA tropical cyclone status — fetched fresh on every request (no cron lag).

Note: the 7-day outlook (TC-Threat PDF) is intentionally NOT live-fetched here — that PDF
download was measured to take 150-180s from this environment (the bulletin page fetch is
comparatively fast, well under 10s), which is unsafe for a per-request serverless call. The
outlook instead relies on scripts/update_outlook.py running frequently via cron.
"""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

PAGASA_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone-bulletin-iframe"
ADVISORY_URL = "https://www.pagasa.dost.gov.ph/tropical-cyclone-advisory-iframe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

NO_ACTIVE_PHRASE = "no active tropical cyclone"


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


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        now_utc = datetime.now(timezone.utc)
        try:
            html = fetch_bulletin()
            text = extract_bulletin_text(html)
            is_clear = NO_ACTIVE_PHRASE in text.lower()
            if is_clear:
                message = "No Active Tropical Cyclone within the Philippine Area of Responsibility"
            else:
                message = text[:600] if text else "Active tropical cyclone bulletin in effect — see PAGASA for details."

            data = {
                "last_checked_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pagasa_active": not is_clear,
                "pagasa_message": message,
                "source_url": PAGASA_URL,
                "advisory_url": ADVISORY_URL,
                "live": True,
            }
            self._json(200, data)
        except Exception as exc:
            self._json(502, {"error": f"Could not reach PAGASA right now: {exc}", "advisory_url": ADVISORY_URL})

    def _json(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

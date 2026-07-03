#!/usr/bin/env python3
"""Fetch PAGASA's TC-Threat Potential (S2S) PDF and extract the week-1/week-2 outlook text."""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

PDF_URL = "https://pubfiles.pagasa.dost.gov.ph/pagasaweb/files/climate/tcthreat/TC_Threat_and_S2S_Forecast.pdf"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT_PATH = Path(__file__).resolve().parent.parent / "outlook.json"
PDF_TMP = Path("/tmp/tc_threat.pdf")


def fetch_pdf() -> bytes:
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_outlook(text: str) -> dict:
    issued_match = re.search(r"Date Issued:\s*([^\n]+)", text)
    week1_match = re.search(r"Week-1\s*\(([^)]+)\)(.*?)Week-2", text, re.DOTALL)
    week2_match = re.search(r"Week-2\s*\(([^)]+)\)(.*?)Therefore,", text, re.DOTALL)
    conclusion_match = re.search(r"Therefore,(.*?)(?:However,|Note:)", text, re.DOTALL)

    if not (issued_match and week1_match):
        raise ValueError("Could not find expected sections in PDF text")

    result = {
        "date_issued": clean(issued_match.group(1)),
        "week1_range": clean(week1_match.group(1)),
        "week1_summary": clean(week1_match.group(2)),
    }
    if week2_match:
        result["week2_range"] = clean(week2_match.group(1))
        result["week2_summary"] = clean(week2_match.group(2))
    if conclusion_match:
        result["conclusion"] = clean("Therefore," + conclusion_match.group(1))
    return result


def main() -> int:
    try:
        pdf_bytes = fetch_pdf()
        PDF_TMP.write_bytes(pdf_bytes)
        reader = PdfReader(str(PDF_TMP))
        text = reader.pages[0].extract_text()
        parsed = parse_outlook(text)
    except Exception as exc:
        print(f"Failed to fetch/parse TC-Threat outlook: {exc}", file=sys.stderr)
        return 0  # keep previous outlook.json rather than failing the whole pipeline

    parsed["last_checked_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parsed["source_url"] = PDF_URL

    OUT_PATH.write_text(json.dumps(parsed, indent=2) + "\n")
    print(json.dumps(parsed, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

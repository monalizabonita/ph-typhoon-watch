#!/usr/bin/env python3
"""Render all active PAGASA flood advisories as one readable PNG report."""
import json
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "flood_advisories.json"
OUT_PATH = ROOT / "flood-alert-report.png"
WIDTH = 1400
MARGIN = 64
GAP = 28
COL_GAP = 28
COL_WIDTH = (WIDTH - MARGIN * 2 - COL_GAP) // 2

COLORS = {
    "bg": "#071522", "panel": "#102638", "text": "#F5FAFF", "muted": "#AFC4D5",
    "line": "#29465C", "EXTREME": "#FF5C68", "HIGH": "#FF9F43",
    "MODERATE": "#FFD166", "WATCH": "#59C3FF", "ADVISORY": "#8FD3C7",
}


def font(size: int, bold: bool = False):
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


TITLE = font(48, True)
SUBTITLE = font(24)
CARD_TITLE = font(29, True)
LABEL = font(19, True)
BODY = font(23)
SMALL = font(19)


def clean(value: str) -> str:
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value or "")
    value = re.sub(r"(?m)^\s*\+\s*", "", value)
    return re.sub(r"\s+", " ", value).strip()


def wrap(draw, text: str, text_font, max_width: int) -> list[str]:
    words = clean(text).split()
    if not words:
        return []
    lines, current = [], words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=text_font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def section_lines(draw, label: str, value: str, width: int):
    return (label, wrap(draw, value, BODY, width))


def advisory_parts(message: str) -> tuple[str, str]:
    message = clean(message)
    marker = "WATERCOURSES LIKELY TO BE AFFECTED"
    if marker not in message:
        return message, ""
    outlook, waterways = message.split(marker, 1)
    return outlook.strip(" :"), waterways.strip(" :")


def chip_rows(draw, areas: list[str], width: int) -> list[list[tuple[str, int]]]:
    rows, row, used = [], [], 0
    for area in areas:
        chip_width = draw.textbbox((0, 0), area, font=SMALL)[2] + 32
        if row and used + 10 + chip_width > width:
            rows.append(row)
            row, used = [], 0
        row.append((area, chip_width))
        used += chip_width + (10 if len(row) > 1 else 0)
    if row:
        rows.append(row)
    return rows


def card_height(draw, item: dict) -> int:
    inner = COL_WIDTH - 64
    outlook, waterways = advisory_parts(item.get("message", ""))
    area_rows = chip_rows(draw, item.get("areas", []), inner)
    sections = [
        section_lines(draw, "12-HOUR WEATHER OUTLOOK", outlook, inner),
        section_lines(draw, "RIVERS & STREAMS AT RISK", waterways, inner),
        section_lines(draw, "WHAT TO DO", item.get("instruction", ""), inner),
    ]
    height = 118 + len(area_rows) * 43
    for _, lines in sections:
        if lines:
            height += 29 + len(lines) * 31 + 12
    height += 130
    return height


def draw_card(draw, xy, item: dict, height: int):
    x, y = xy
    severity = item.get("severity", "ADVISORY")
    accent = COLORS.get(severity, COLORS["ADVISORY"])
    draw.rounded_rectangle((x, y, x + COL_WIDTH, y + height), 20, fill=COLORS["panel"])
    draw.rounded_rectangle((x, y, x + 12, y + height), 6, fill=accent)
    draw.text((x + 32, y + 25), severity, font=CARD_TITLE, fill=accent)
    draw.text((x + COL_WIDTH - 32, y + 33), item.get("published_by", "PAGASA-DOST"),
              font=SMALL, fill=COLORS["muted"], anchor="ra")
    cursor = y + 80
    inner_x, inner_width = x + 32, COL_WIDTH - 64
    draw.text((inner_x, cursor), "AFFECTED AREAS", font=LABEL, fill=accent)
    cursor += 30
    for row in chip_rows(draw, item.get("areas", []), inner_width):
        chip_x = inner_x
        for area, chip_width in row:
            draw.rounded_rectangle((chip_x, cursor, chip_x + chip_width, cursor + 32), 14,
                                   fill="#1B3A50", outline=accent, width=1)
            draw.text((chip_x + 16, cursor + 6), area, font=SMALL, fill=COLORS["text"])
            chip_x += chip_width + 10
        cursor += 43
    cursor += 7
    outlook, waterways = advisory_parts(item.get("message", ""))
    for label, lines in [
        section_lines(draw, "12-HOUR WEATHER OUTLOOK", outlook, inner_width),
        section_lines(draw, "RIVERS & STREAMS AT RISK", waterways, inner_width),
        section_lines(draw, "WHAT TO DO", item.get("instruction", ""), inner_width),
    ]:
        if not lines:
            continue
        draw.text((inner_x, cursor), label, font=LABEL, fill=accent)
        cursor += 28
        for line in lines:
            draw.text((inner_x, cursor), line, font=BODY, fill=COLORS["text"])
            cursor += 31
        cursor += 12
    draw.line((inner_x, y + height - 61, x + COL_WIDTH - 32, y + height - 61), fill=COLORS["line"])
    issued = item.get("issued_at") or "Not provided"
    valid = item.get("valid_until") or "Not provided"
    draw.text((inner_x, y + height - 45), f"Issued: {issued}  |  Valid until: {valid}",
              font=SMALL, fill=COLORS["muted"])


def main() -> int:
    snapshot = json.loads(DATA_PATH.read_text())
    advisories = sorted(
        snapshot.get("advisories", []),
        key=lambda item: ({"EXTREME": 0, "HIGH": 1, "MODERATE": 2}.get(item.get("severity"), 3),
                          item.get("areas", [])),
    )
    scratch = Image.new("RGB", (WIDTH, 100), COLORS["bg"])
    measure = ImageDraw.Draw(scratch)
    heights = [card_height(measure, item) for item in advisories]
    columns = [[], []]
    totals = [0, 0]
    for item, height in zip(advisories, heights):
        column = 0 if totals[0] <= totals[1] else 1
        columns[column].append((item, height))
        totals[column] += height + GAP
    header_height = 445
    footer_height = 115
    height = header_height + max(totals or [0]) + footer_height
    image = Image.new("RGB", (WIDTH, height), COLORS["bg"])
    draw = ImageDraw.Draw(image)

    draw.text((MARGIN, 48), "PAGASA FLOOD ALERT REPORT", font=TITLE, fill=COLORS["text"])
    checked = snapshot.get("checked_at_utc", "")
    try:
        checked = datetime.fromisoformat(checked.replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        pass
    draw.text((MARGIN, 112), "OFFICIAL GENERAL FLOOD ADVISORIES • LUZON + CEBU",
              font=SUBTITLE, fill=COLORS["muted"])
    draw.text((MARGIN, 150), f"Generated {checked}", font=SMALL, fill=COLORS["muted"])
    counts = {}
    for item in advisories:
        counts[item.get("severity", "ADVISORY")] = counts.get(item.get("severity", "ADVISORY"), 0) + 1
    unique_areas = sorted({area for item in advisories for area in item.get("areas", [])})
    stats = [
        (str(len(advisories)), "ACTIVE ADVISORIES", COLORS["WATCH"]),
        (str(counts.get("EXTREME", 0)), "EXTREME", COLORS["EXTREME"]),
        (str(len(unique_areas)), "AFFECTED AREAS", COLORS["MODERATE"]),
    ]
    stat_y, stat_gap = 205, 18
    stat_width = (WIDTH - MARGIN * 2 - stat_gap * 2) // 3
    for index, (value, label, accent) in enumerate(stats):
        x = MARGIN + index * (stat_width + stat_gap)
        draw.rounded_rectangle((x, stat_y, x + stat_width, stat_y + 104), 18, fill=COLORS["panel"])
        draw.ellipse((x + 24, stat_y + 24, x + 78, stat_y + 78), fill=accent)
        draw.text((x + 51, stat_y + 51), value, font=CARD_TITLE, fill="#071522", anchor="mm")
        draw.text((x + 98, stat_y + 39), label, font=LABEL, fill=COLORS["text"])
        draw.text((x + 98, stat_y + 66), "Current PAGASA feed", font=SMALL, fill=COLORS["muted"])

    callout_y = 327
    draw.rounded_rectangle((MARGIN, callout_y, WIDTH - MARGIN, callout_y + 86), 18,
                           fill="#17364A", outline=COLORS["WATCH"], width=2)
    draw.ellipse((MARGIN + 22, callout_y + 20, MARGIN + 68, callout_y + 66), fill=COLORS["WATCH"])
    draw.text((MARGIN + 45, callout_y + 43), "!", font=CARD_TITLE, fill="#071522", anchor="mm")
    draw.text((MARGIN + 88, callout_y + 18), "METRO MANILA SPOTLIGHT", font=LABEL, fill=COLORS["WATCH"])
    draw.text((MARGIN + 88, callout_y + 47),
              "All NCR rivers and streams are covered — this includes Marikina City.",
              font=BODY, fill=COLORS["text"])

    for col_index, cards in enumerate(columns):
        x = MARGIN + col_index * (COL_WIDTH + COL_GAP)
        y = header_height
        for item, card_h in cards:
            draw_card(draw, (x, y), item, card_h)
            y += card_h + GAP

    footer_y = height - footer_height + 20
    draw.line((MARGIN, footer_y, WIDTH - MARGIN, footer_y), fill=COLORS["line"], width=2)
    draw.text((MARGIN, footer_y + 22),
              "Official source: PAGASA PANaHON General Flood Advisories • Follow local DRRMO instructions.",
              font=SMALL, fill=COLORS["muted"])
    draw.text((MARGIN, footer_y + 52), snapshot.get("source_url", "https://panahon.gov.ph/"),
              font=SMALL, fill=COLORS["WATCH"])
    image.save(OUT_PATH, "PNG", optimize=True)
    print(f"Created {OUT_PATH.name} ({WIDTH}x{height}) with {len(advisories)} advisories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

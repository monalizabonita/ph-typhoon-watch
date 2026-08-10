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
SUMMARY_PATH = ROOT / "flood-alert-summary.png"
PAGE_PREFIX = "flood-alert-advisory-"
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


def render_chat_summary(snapshot: dict, advisories: list[dict], counts: dict, unique_areas: list[str]):
    width, height = 900, 520
    image = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    draw.text((42, 38), "PAGASA FLOOD ALERT", font=font(43, True), fill=COLORS["text"])
    draw.text((42, 94), "OFFICIAL INFOGRAPHIC • LUZON + CEBU", font=font(20, True), fill=COLORS["muted"])
    stat_width = 254
    for index, (value, label, accent) in enumerate([
        (len(advisories), "ACTIVE", COLORS["WATCH"]),
        (counts.get("EXTREME", 0), "EXTREME", COLORS["EXTREME"]),
        (len(unique_areas), "AREAS", COLORS["MODERATE"]),
    ]):
        x = 42 + index * 272
        draw.rounded_rectangle((x, 145, x + stat_width, 260), 20, fill=COLORS["panel"])
        draw.text((x + 24, 161), str(value), font=font(50, True), fill=accent)
        draw.text((x + 102, 184), label, font=font(22, True), fill=COLORS["text"])
    draw.rounded_rectangle((42, 292, 858, 398), 20, fill="#17364A", outline=COLORS["WATCH"], width=3)
    draw.text((70, 314), "METRO MANILA • MARIKINA", font=font(23, True), fill=COLORS["WATCH"])
    draw.text((70, 351), "All NCR rivers and streams are covered by the advisory.",
              font=font(25), fill=COLORS["text"])
    draw.text((42, 438), "Swipe/scroll down: each advisory is shown in full below.",
              font=font(22), fill=COLORS["muted"])
    image.save(SUMMARY_PATH, "PNG", optimize=True)


def render_chat_advisory(item: dict, index: int, total: int):
    width, pad, inner = 900, 46, 808
    title_font, label_font, body_font, small_font = (
        font(40, True), font(22, True), font(29), font(21)
    )
    scratch = Image.new("RGB", (width, 100), COLORS["bg"])
    measure = ImageDraw.Draw(scratch)
    outlook, waterways = advisory_parts(item.get("message", ""))
    sections = [
        ("12-HOUR WEATHER OUTLOOK", wrap(measure, outlook, body_font, inner)),
        ("RIVERS & STREAMS AT RISK", wrap(measure, waterways, body_font, inner)),
        ("WHAT TO DO", wrap(measure, item.get("instruction", ""), body_font, inner)),
    ]
    area_rows = chip_rows(measure, item.get("areas", []), inner)
    height = 245 + len(area_rows) * 48
    height += sum(42 + len(lines) * 39 + 18 for _, lines in sections if lines)
    height += 120
    image = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    severity = item.get("severity", "ADVISORY")
    accent = COLORS.get(severity, COLORS["ADVISORY"])
    draw.rectangle((0, 0, 16, height), fill=accent)
    draw.text((pad, 35), severity, font=title_font, fill=accent)
    draw.text((width - pad, 48), f"ADVISORY {index}/{total}", font=small_font,
              fill=COLORS["muted"], anchor="ra")
    draw.text((pad, 102), "AFFECTED AREAS", font=label_font, fill=accent)
    cursor = 143
    for row in area_rows:
        chip_x = pad
        for area, _ in row:
            chip_width = draw.textbbox((0, 0), area, font=small_font)[2] + 36
            draw.rounded_rectangle((chip_x, cursor, chip_x + chip_width, cursor + 38), 17,
                                   fill="#1B3A50", outline=accent, width=2)
            draw.text((chip_x + 18, cursor + 8), area, font=small_font, fill=COLORS["text"])
            chip_x += chip_width + 12
        cursor += 48
    cursor += 18
    for label, lines in sections:
        if not lines:
            continue
        draw.text((pad, cursor), label, font=label_font, fill=accent)
        cursor += 40
        for line in lines:
            draw.text((pad, cursor), line, font=body_font, fill=COLORS["text"])
            cursor += 39
        cursor += 18
    draw.line((pad, height - 100, width - pad, height - 100), fill=COLORS["line"], width=2)
    draw.text((pad, height - 78), f"ISSUED  {item.get('issued_at') or 'Not provided'}",
              font=small_font, fill=COLORS["muted"])
    draw.text((pad, height - 47), f"VALID UNTIL  {item.get('valid_until') or 'Not provided'}  •  PAGASA-DOST",
              font=small_font, fill=COLORS["muted"])
    image.save(ROOT / f"{PAGE_PREFIX}{index}.png", "PNG", optimize=True)


def render_large_inline_card(item: dict, index: int, total: int):
    """Create a short, large-type panel that stays readable at Google Chat card width."""
    width, height, pad = 900, 660, 48
    image = Image.new("RGB", (width, height), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    severity = item.get("severity", "ADVISORY")
    accent = COLORS.get(severity, COLORS["ADVISORY"])
    draw.rectangle((0, 0, width, 18), fill=accent)
    draw.text((pad, 48), severity, font=font(48, True), fill=accent)
    draw.text((width - pad, 65), f"PAGASA • {index} OF {total}", font=font(23, True),
              fill=COLORS["muted"], anchor="ra")

    draw.text((pad, 126), "AFFECTED AREAS", font=font(23, True), fill=accent)
    area_lines = wrap(draw, ", ".join(item.get("areas", [])), font(34, True), width - pad * 2)
    cursor = 166
    for line in area_lines[:3]:
        draw.text((pad, cursor), line, font=font(34, True), fill=COLORS["text"])
        cursor += 43

    outlook, _ = advisory_parts(item.get("message", ""))
    cursor += 16
    draw.text((pad, cursor), "12-HOUR OUTLOOK", font=font(23, True), fill=accent)
    cursor += 39
    for line in wrap(draw, outlook, font(28), width - pad * 2)[:3]:
        draw.text((pad, cursor), line, font=font(28), fill=COLORS["text"])
        cursor += 37

    hazard_y = 455
    draw.rounded_rectangle((pad, hazard_y, width - pad, hazard_y + 92), 18,
                           fill="#19384E", outline=accent, width=2)
    draw.text((pad + 24, hazard_y + 18), "FLOODING RISK", font=font(22, True), fill=accent)
    draw.text((pad + 24, hazard_y + 51), "Rivers, streams and low-lying areas",
              font=font(29, True), fill=COLORS["text"])
    draw.text((pad, 580), f"VALID UNTIL  {item.get('valid_until') or 'Not provided'}",
              font=font(23, True), fill=COLORS["muted"])
    image.save(ROOT / f"{PAGE_PREFIX}{index}.png", "PNG", optimize=True)


def render_reference_infographic(snapshot: dict, advisories: list[dict]):
    """Render a compact official-advisory poster sized for inline Google Chat display."""
    width, height = 1200, 1590
    image = Image.new("RGB", (width, height), "#E8E5DC")
    draw = ImageDraw.Draw(image)
    navy, blue, ink, cream = "#09243A", "#1679B8", "#14202A", "#F5F1E7"
    red, orange, yellow = "#E23D3D", "#F28C28", "#F2CF3A"

    # Branded advisory header and warning legend.
    draw.rectangle((0, 0, width, 180), fill=navy)
    draw.rectangle((0, 0, width, 24), fill=blue)
    draw.text((48, 42), "WEATHER ADVISORY", font=font(67, True), fill="white")
    draw.text((52, 126), "PAGASA GENERAL FLOOD ADVISORY • LUZON + CEBU", font=font(23, True), fill="#B9D7E9")
    legend_y = 180
    legend = [(yellow, "MODERATE"), (orange, "HIGH"), (red, "EXTREME")]
    segment = width // 3
    for index, (color, label) in enumerate(legend):
        x = index * segment
        draw.rectangle((x, legend_y, x + segment, legend_y + 48), fill=color)
        draw.text((x + segment // 2, legend_y + 24), f"●  {label} FLOOD ADVISORY",
                  font=font(20, True), fill=navy, anchor="mm")

    draw.text((width // 2, 267), "ENHANCED SOUTHWEST MONSOON (HABAGAT)",
              font=font(34, True), fill=navy, anchor="mm")
    draw.text((width // 2, 311), f"{len(advisories)} active advisories • Official PAGASA information",
              font=font(24), fill=ink, anchor="mm")
    checked = snapshot.get("checked_at_utc", "").replace("T", " ").replace("Z", " UTC")
    draw.text((width - 49, 329), f"Updated: {checked}", font=font(16), fill="#52616B", anchor="ra")

    # One concise row per official advisory, preserving every affected area and validity window.
    table_x, table_y, table_w = 48, 355, 1104
    level_w, hazard_w = 210, 0
    area_w = table_w - level_w - hazard_w
    header_h = 54
    draw.rectangle((table_x, table_y, table_x + table_w, table_y + header_h), fill=blue)
    for x, label in [(table_x + level_w // 2, "WARNING LEVEL"),
                     (table_x + level_w + area_w // 2, "AFFECTED AREAS / VALIDITY")]:
        draw.text((x, table_y + 27), label, font=font(19, True), fill="white", anchor="mm")

    row_font, meta_font = font(29, True), font(20)
    row_specs = []
    for item in advisories:
        area_text = ", ".join(item.get("areas", []))
        area_lines = wrap(draw, area_text, row_font, area_w - 34)
        row_h = max(92, 24 + len(area_lines) * 31 + 28)
        row_specs.append((item, area_lines, row_h))
    available = 755
    total_rows = sum(row[2] for row in row_specs)
    if total_rows > available:
        scale = available / total_rows
        row_specs = [(item, lines, max(82, int(row_h * scale))) for item, lines, row_h in row_specs]

    cursor = table_y + header_h
    for row_index, (item, area_lines, row_h) in enumerate(row_specs):
        severity = item.get("severity", "ADVISORY")
        color = {"EXTREME": red, "HIGH": orange, "MODERATE": yellow}.get(severity, "#65B7D8")
        fill = cream if row_index % 2 == 0 else "#DEDCD4"
        draw.rectangle((table_x, cursor, table_x + table_w, cursor + row_h), fill=fill, outline="#9BA4AA", width=2)
        draw.rectangle((table_x, cursor, table_x + level_w, cursor + row_h), fill=color)
        draw.text((table_x + level_w // 2, cursor + row_h // 2 - 12), severity,
                  font=font(24, True), fill=navy, anchor="mm")
        draw.text((table_x + level_w // 2, cursor + row_h // 2 + 19), "FLOOD ADVISORY",
                  font=font(15, True), fill=navy, anchor="mm")
        text_y = cursor + 13
        for line in area_lines:
            draw.text((table_x + level_w + 17, text_y), line, font=row_font, fill=ink)
            text_y += 31
        valid = item.get("valid_until") or "Not provided"
        draw.text((table_x + level_w + 17, cursor + row_h - 25), f"Valid until: {valid}",
                  font=meta_font, fill="#52616B")
        cursor += row_h

    # Metro Manila callout and concise safety strip, following the reference poster.
    safety_y = cursor + 24
    draw.rounded_rectangle((48, safety_y, 1152, safety_y + 72), 15, fill="#D9EDF7", outline=blue, width=3)
    draw.text((72, safety_y + 18), "METRO MANILA:", font=font(22, True), fill=blue)
    draw.text((276, safety_y + 18), "All NCR rivers and streams are covered, including Marikina City.",
              font=font(22), fill=ink)

    reminder_y = safety_y + 96
    draw.rounded_rectangle((48, reminder_y, 1152, reminder_y + 64), 15, fill="#F8D7DA", outline=red, width=3)
    draw.text((72, reminder_y + 17), "PRIMARY HAZARD:", font=font(23, True), fill=red)
    draw.text((330, reminder_y + 17), "Flooding in rivers, streams and low-lying areas",
              font=font(23, True), fill=ink)
    reminder_y += 89
    draw.text((48, reminder_y), "SAFETY REMINDERS", font=font(27, True), fill=navy)
    reminders = [
        "Avoid low-lying and flood-prone areas, especially riverbanks and creeks.",
        "Do not cross flooded roads; even shallow floodwater can be dangerous.",
        "Prepare emergency supplies and follow evacuation instructions from your local DRRMO.",
        "Monitor PAGASA, NDRRMC, and local government channels for real-time updates.",
    ]
    for index, reminder in enumerate(reminders):
        y = reminder_y + 45 + index * 37
        draw.ellipse((54, y + 7, 66, y + 19), fill=red if index < 2 else blue)
        draw.text((82, y), reminder, font=font(22), fill=ink)

    draw.rectangle((0, height - 72, width, height), fill=navy)
    draw.text((42, height - 51), "SOURCE: PAGASA PANaHON • Generated automatically from active official advisories",
              font=font(18, True), fill="white")
    draw.text((42, height - 27), snapshot.get("source_url", "https://panahon.gov.ph/"),
              font=font(16), fill="#79C7F2")
    image.save(OUT_PATH, "PNG", optimize=True)


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
    render_reference_infographic(snapshot, advisories)
    print(f"Created compact weather-advisory infographic with {len(advisories)} official advisories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

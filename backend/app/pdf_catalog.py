"""Extract the fixed Fall 2026 offerings PDF into normalized course section data."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
PDF_PATH = DATA_DIR / "fall_2026_course_offerings.pdf"
JSON_PATH = DATA_DIR / "fall_2026_sections.json"
TIME_RE = re.compile(r"(\d{1,2}:\d{2}:\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}:\s*[AP]M)", re.I)


def minutes(value: str) -> int:
    parsed = re.fullmatch(r"\s*(\d{1,2}):(\d{2}):\s*([AP]M)\s*", value, re.I)
    if not parsed:
        raise ValueError(f"Unsupported time format: {value}")
    hour, minute, suffix = int(parsed[1]), int(parsed[2]), parsed[3].upper()
    if not 1 <= hour <= 12 or minute > 59:
        raise ValueError(f"Invalid time: {value}")
    hour = hour % 12 + (12 if suffix == "PM" else 0)
    return hour * 60 + minute


def parse_catalog(pdf_path: Path = PDF_PATH) -> tuple[list[dict], dict]:
    document = pymupdf.open(pdf_path)
    records: list[dict] = []
    malformed: list[dict] = []
    pages_with_tables = 0
    for page_no, page in enumerate(document, 1):
        tables = page.find_tables().tables
        if not tables:
            continue
        pages_with_tables += 1
        for row in tables[0].extract()[1:]:
            values = [(cell or "").replace("\n", " ").strip() for cell in row]
            if not any(values):
                continue
            if len(values) != 14 or not values[2]:
                malformed.append({"page": page_no, "row": values})
                continue
            serial, program, code, title, raw_section, room1, room2, day1, day2, time1, time2, faculty, initial, credit = values
            section = raw_section
            section_note = ""
            if "(" in section:
                section, section_note = section.split("(", 1)
                section = section.strip()
                section_note = section_note.rstrip(") ")
            # In several rows Excel lets the title's final character overflow into
            # the section cell. Rejoin lowercase overflow while keeping the raw cell.
            if section[:1].islower():
                title += section[0]
                section = section[1:]
            title_fixes = {
                ("BSCSE", "CSE 1112"): "Structured Programming Language Laboratory",
                ("BSCSE", "CSE 2118"): "Advanced Object Oriented Programming Laboratory",
                ("BSCSE", "CSE 2216"): "Data Structure and Algorithms I Laboratory",
                ("BSCSE", "CSE 2218"): "Data Structure and Algorithms II Laboratory",
                ("BSCSE", "CSE 3522"): "Database Management Systems Laboratory",
                ("BSDS", "CSE 2216"): "Data Structure and Algorithms I Laboratory",
                ("BSDS", "CSE 2218"): "Data Structure and Algorithms II Laboratory",
                ("BSDS", "CSE 3522"): "Database Management Systems Laboratory",
                ("BSCSE", "CSE 4326"): "Microprocessors and Microcontrollers Laboratory",
                ("BSCSE", "CSE 4399"): "Special Topics - Embedded Machine Learning",
                ("BSCSE", "SOC 2101"): "Society, Environment and Engineering Ethics",
                ("BSDS", "DS 1115"): "Object Oriented Programming for Data Science",
            }
            title = title_fixes.get((program, code), title)
            raw_credit = credit
            credit_match = re.search(r"(\d+)\s*$", raw_credit)
            normalized_credit = int(credit_match.group(1)) if credit_match else None
            if credit_match:
                overflow = raw_credit[:credit_match.start()].strip()
                if overflow:
                    initial = initial + overflow
            meetings = []
            for day, slot, room in ((day1, time1, room1), (day2, time2, room2)):
                match = TIME_RE.search(slot)
                if day and match:
                    start, end = minutes(match[1]), minutes(match[2])
                    if start >= end:
                        malformed.append({"page": page_no, "serial": serial, "error": "non-positive meeting duration", "time": slot})
                        continue
                    meetings.append({"day": day.title(), "start": start, "end": end, "room": room})
            records.append({
                "source_serial": int(serial) if serial.isdigit() else serial,
                "program": program,
                "course_code": code,
                "course_name": title,
                "section": section,
                "section_note": section_note,
                "faculty": faculty or "TBA",
                "faculty_initial": initial or "TBA",
                "credits": normalized_credit,
                "meetings": meetings,
                "source_page": page_no,
                "source_fields": {"serial": serial, "program": program, "course_code": code, "title": values[3], "section": raw_section,
                                  "room1": room1, "room2": room2, "day1": day1, "day2": day2, "time1": time1, "time2": time2,
                                  "faculty_name": faculty, "faculty_initial": values[12], "credit": raw_credit},
            })
    report = {"pdf": pdf_path.name, "pages": len(document), "pages_with_tables": pages_with_tables, "records": len(records), "unique_courses": len({r['course_code'] for r in records}), "programs": sorted({r['program'] for r in records}), "malformed_rows": malformed}
    return records, report


def main() -> None:
    records, report = parse_catalog()
    JSON_PATH.write_text(json.dumps({"term": "Fall 2026", "source": report["pdf"], "extraction_report": report, "sections": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "malformed_rows"}, indent=2))
    print("malformed sample:", json.dumps(report["malformed_rows"][:5], ensure_ascii=False))


if __name__ == "__main__":
    main()

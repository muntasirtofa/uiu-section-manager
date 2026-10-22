from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import JSON, DateTime, Integer, String, create_engine, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from urllib.parse import urlsplit

from .pdf_catalog import DATA_DIR

load_dotenv(DATA_DIR.parent.parent / ".env", override=False)

def database_url_from_environment() -> URL:
    raw_url = os.getenv("DATABASE_URL", "sqlite:///./uiu_fall2026.db").strip()
    if not raw_url:
        raise RuntimeError("DATABASE_URL is empty. Set it to a valid SQLAlchemy connection URL.")
    try:
        parsed = make_url(raw_url)
    except Exception:
        raise RuntimeError("DATABASE_URL is not a valid SQLAlchemy connection URL.") from None
    if parsed.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.drivername.startswith("postgresql+") and parsed.drivername != "postgresql+psycopg":
        raise RuntimeError("PostgreSQL requires the installed psycopg 3 driver (postgresql+psycopg).")
    return parsed


DATABASE_URL = database_url_from_environment()
try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if DATABASE_URL.get_backend_name() == "sqlite" else {},
    )
except Exception:
    raise RuntimeError("Could not configure the database engine. Check DATABASE_URL and installed database drivers.") from None


class Base(DeclarativeBase):
    pass


class SectionRecord(Base):
    __tablename__ = "sections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_serial: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    source_page: Mapped[int] = mapped_column(Integer)
    program: Mapped[str] = mapped_column(String(30), index=True)
    course_code: Mapped[str] = mapped_column(String(30), index=True)
    course_name: Mapped[str] = mapped_column(String(250), index=True)
    section: Mapped[str] = mapped_column(String(40), index=True)
    section_note: Mapped[str] = mapped_column(String(100), default="")
    faculty: Mapped[str] = mapped_column(String(200), index=True)
    faculty_initial: Mapped[str] = mapped_column(String(50))
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meetings: Mapped[list] = mapped_column(JSON)
    source_fields: Mapped[dict] = mapped_column(JSON)


class RoutineRecord(Base):
    __tablename__ = "routines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    section_ids: Mapped[list] = mapped_column(JSON)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)


def initialize_catalog() -> None:
    """Create missing catalog rows without replacing records or saved routines."""
    catalog = DATA_DIR / "fall_2026_sections.json"
    if not catalog.exists():
        raise RuntimeError(f"Bundled Fall 2026 catalog missing: {catalog}")
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    records = payload.get("sections")
    if not isinstance(records, list):
        raise RuntimeError("Bundled Fall 2026 catalog has an invalid format: expected a sections list.")
    if not records:
        return
    table = SectionRecord.__table__
    if engine.dialect.name == "postgresql":
        statement = postgresql_insert(table).values(records).on_conflict_do_nothing(index_elements=[table.c.source_serial])
    elif engine.dialect.name == "sqlite":
        statement = sqlite_insert(table).values(records).on_conflict_do_nothing(index_elements=[table.c.source_serial])
    else:
        with Session(engine) as db:
            for data in records:
                if db.scalar(select(SectionRecord.id).where(SectionRecord.source_serial == data["source_serial"])) is None:
                    db.add(SectionRecord(**data))
            db.commit()
        return
    with engine.begin() as connection:
        for start in range(0, len(records), 100):
            chunk = records[start:start + 100]
            if engine.dialect.name == "postgresql":
                chunk_statement = postgresql_insert(table).values(chunk).on_conflict_do_nothing(index_elements=[table.c.source_serial])
            else:
                chunk_statement = sqlite_insert(table).values(chunk).on_conflict_do_nothing(index_elements=[table.c.source_serial])
            connection.execute(chunk_statement)


try:
    Base.metadata.create_all(engine)
    initialize_catalog()
except SQLAlchemyError:
    raise RuntimeError("Database initialization failed. Verify DATABASE_URL, database availability, and schema permissions.") from None

app = FastAPI(title="UIU Section Manager API", version="2.0.0", description="Fall 2026 UIU course catalog, schedule selection, conflict checking, routine planning, and exports.")


def cors_origins_from_environment() -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = []
    for value in configured.split(","):
        origin = value.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if origin == "*" or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError("CORS_ORIGINS must contain comma-separated exact http(s) origins without paths or wildcards.")
        if origin not in origins:
            origins.append(origin)
    if not origins:
        raise RuntimeError("CORS_ORIGINS must include at least one exact frontend origin.")
    return origins


app.add_middleware(CORSMiddleware, allow_origins=cors_origins_from_environment(), allow_methods=["*"], allow_headers=["*"])


class Meeting(BaseModel):
    day: str
    start: int = Field(ge=0, le=1440)
    end: int = Field(ge=1, le=1440)
    room: str = ""

    def valid(self) -> bool:
        return self.start < self.end


class RoutineIn(BaseModel):
    name: str = "My Fall 2026 routine"
    section_ids: list[int]
    preferences: dict[str, list[str]] = {}


def row_dict(section: SectionRecord) -> dict[str, Any]:
    return {"id": section.id, "source_serial": section.source_serial, "source_page": section.source_page,
            "program": section.program, "course_code": section.course_code, "course_name": section.course_name,
            "section": section.section, "section_note": section.section_note, "faculty": section.faculty, "faculty_initial": section.faculty_initial,
            "credits": section.credits, "meetings": section.meetings, "source_fields": section.source_fields}


def conflicts(sections: list[dict]) -> list[dict]:
    found = []
    for index, first in enumerate(sections):
        for second in sections[index + 1:]:
            for a in first["meetings"]:
                for b in second["meetings"]:
                    if a["day"].casefold() == b["day"].casefold() and max(a["start"], b["start"]) < min(a["end"], b["end"]):
                        found.append({"first": f"{first['course_code']} {first['section']}", "second": f"{second['course_code']} {second['section']}",
                                      "day": a["day"], "start": max(a["start"], b["start"]), "end": min(a["end"], b["end"])})
    return found


def read_sections(section_ids: list[int]) -> list[dict]:
    with Session(engine) as db:
        sections = [db.get(SectionRecord, section_id) for section_id in section_ids]
        if any(section is None for section in sections):
            raise HTTPException(404, "One or more course sections were not found in the Fall 2026 catalog.")
        return [row_dict(section) for section in sections if section is not None]


@app.get("/api/health")
def health():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except SQLAlchemyError:
        raise HTTPException(503, "Database connection is unavailable. Check the backend database configuration.") from None
    return {"status": "ok", "database": "connected", "term": "Fall 2026"}


@app.get("/api/overview")
def overview():
    with Session(engine) as db:
        sections = db.scalars(select(SectionRecord)).all()
        courses = {(s.program, s.course_code) for s in sections}
        faculty = {s.faculty for s in sections if s.faculty and s.faculty != "TBA"}
        return {"term": "Fall 2026", "sections": len(sections), "courses": len(courses), "programs": len({s.program for s in sections}),
                "faculty": len(faculty), "source": "Class Routine with faculty assign Fall 2026.pdf"}


@app.get("/api/source/pdf")
def source_pdf():
    path = DATA_DIR / "fall_2026_course_offerings.pdf"
    if not path.exists():
        raise HTTPException(404, "Bundled Fall 2026 PDF is missing.")
    return FileResponse(path, media_type="application/pdf", filename="UIU Fall 2026 Course Offerings.pdf")


@app.get("/api/sections")
def list_sections(program: str | None = None, search: str | None = None, course_code: str | None = None, faculty: str | None = None, limit: int = 100, offset: int = 0):
    with Session(engine) as db:
        query = select(SectionRecord)
        if program:
            query = query.where(SectionRecord.program == program.upper())
        if course_code:
            query = query.where(SectionRecord.course_code == course_code.upper())
        if faculty:
            query = query.where(SectionRecord.faculty.ilike(f"%{faculty}%"))
        if search:
            term = f"%{search}%"
            query = query.where((SectionRecord.course_code.ilike(term)) | (SectionRecord.course_name.ilike(term)) | (SectionRecord.faculty.ilike(term)) | (SectionRecord.section.ilike(term)))
        query = query.order_by(SectionRecord.program, SectionRecord.course_code, SectionRecord.section).offset(max(offset, 0)).limit(min(max(limit, 1), 500))
        rows = [row_dict(section) for section in db.scalars(query).all()]
        return {"items": rows, "limit": limit, "offset": offset, "returned": len(rows)}


@app.get("/api/courses")
def list_courses(program: str | None = None, search: str | None = None, unique: bool = False):
    with Session(engine) as db:
        sections = db.scalars(select(SectionRecord).order_by(SectionRecord.program, SectionRecord.course_code, SectionRecord.section)).all()
    grouped: dict[tuple[str, str] | str, dict] = {}
    for section in sections:
        key = section.course_code if unique else (section.program, section.course_code)
        if program and section.program != program.upper():
            continue
        if search and search.casefold() not in f"{section.course_code} {section.course_name}".casefold():
            continue
        course = grouped.setdefault(key, {"program": section.program, "programs": set(), "course_code": section.course_code, "course_name": section.course_name, "course_names": set(), "sections": 0, "credits": set(), "faculty": set()})
        course["sections"] += 1
        course["programs"].add(section.program)
        course["course_names"].add(section.course_name)
        if section.credits is not None:
            course["credits"].add(section.credits)
        if section.faculty and section.faculty != "TBA":
            course["faculty"].add(section.faculty)
    if unique:
        return [{**course, "programs": sorted(course["programs"]), "course_names": sorted(course["course_names"]), "credits": sorted(course["credits"]), "faculty": sorted(course["faculty"])} for course in grouped.values()]
    return [{"program": course["program"], "course_code": course["course_code"], "course_name": course["course_name"], "sections": course["sections"], "credits": min(course["credits"]) if course["credits"] else None, "faculty": sorted(course["faculty"])} for course in grouped.values()]


@app.get("/api/faculty")
def list_faculty(search: str | None = None):
    with Session(engine) as db:
        sections = db.scalars(select(SectionRecord)).all()
    grouped: dict[str, dict] = {}
    for section in sections:
        if not section.faculty or section.faculty == "TBA" or (search and search.casefold() not in section.faculty.casefold()):
            continue
        faculty = grouped.setdefault(section.faculty, {"name": section.faculty, "initials": set(), "courses": set(), "sections": 0})
        if section.faculty_initial:
            faculty["initials"].add(section.faculty_initial)
        faculty["courses"].add(section.course_code)
        faculty["sections"] += 1
    return [{"name": row["name"], "initials": sorted(row["initials"]), "courses": sorted(row["courses"]), "sections": row["sections"]} for row in sorted(grouped.values(), key=lambda item: item["name"].casefold())]


@app.post("/api/conflicts")
def check_conflicts(section_ids: list[int]):
    return {"conflicts": conflicts(read_sections(section_ids))}


@app.post("/api/routines/generate")
def generate_routines(payload: dict):
    course_selections = payload.get("course_selections") or [{"course_code": code} for code in payload.get("course_codes", [])]
    course_selections = list({(item.get("program", "").upper(), item["course_code"].upper()): {"program": item.get("program", "").upper(), "course_code": item["course_code"].upper()} for item in course_selections}.values())
    course_codes = [item["course_code"] for item in course_selections]
    if not course_codes:
        raise HTTPException(422, "Choose at least one course.")
    if len(course_codes) > 8:
        raise HTTPException(422, "Choose up to eight courses per routine.")
    preferences: dict[str, list[str]] = payload.get("faculty_preferences", {})
    gap_order = "longest" if payload.get("gap_order") == "longest" else "shortest"
    requested_class_count = payload.get("class_count")
    if requested_class_count not in (None, "", 1, 2, 3, 4, "1", "2", "3", "4"):
        raise HTTPException(422, "Classes per day must be between 1 and 4.")
    requested_class_count = int(requested_class_count) if requested_class_count not in (None, "") else None
    monday_preference = payload.get("monday_preference")
    if monday_preference not in ("avoid", "require", "any"):
        # Backwards compatibility: the old checkbox meant “require Monday”.
        monday_preference = "require" if payload.get("require_monday") else "avoid"
    limit = min(max(int(payload.get("limit", 5)), 1), 20)
    with Session(engine) as db:
        options: list[list[dict]] = []
        missing = []
        for item in course_selections:
            code = item["course_code"]
            query = select(SectionRecord).where(SectionRecord.course_code == code)
            if item["program"]:
                query = query.where(SectionRecord.program == item["program"])
            rows = db.scalars(query.order_by(SectionRecord.section)).all()
            if not rows:
                missing.append(code)
            else:
                sections = [row_dict(s) for s in rows]
                ranks = preferences.get(f"{item['program']}:{code}", preferences.get(code, []))
                if ranks:
                    priority = {name: index for index, name in enumerate(ranks)}
                    sections.sort(key=lambda section: (priority.get(section["faculty"], len(ranks)), section["section"]))
                options.append(sections)
    if missing:
        raise HTTPException(404, {"message": "Course codes not found in this catalog.", "courses": missing})
    # Process courses with fewer sections first to prune conflicts early.
    options.sort(key=len)
    results: list[dict] = []
    candidate_limit = max(limit * 500, 3000)
    examined = 0

    def idle_gap_minutes(sections: list[dict]) -> int:
        meetings_by_day: dict[str, list[tuple[int, int]]] = {}
        for section in sections:
            for meeting in section["meetings"]:
                meetings_by_day.setdefault(meeting["day"], []).append((meeting["start"], meeting["end"]))
        total = 0
        for meetings in meetings_by_day.values():
            meetings.sort()
            previous_end = None
            for start, end in meetings:
                if previous_end is not None and start > previous_end:
                    total += start - previous_end
                previous_end = max(previous_end or end, end)
        return total

    def faculty_priority(section: dict) -> int:
        ranks = preferences.get(f"{section['program']}:{section['course_code']}", preferences.get(section["course_code"], []))
        return ranks.index(section["faculty"]) if section["faculty"] in ranks else len(ranks)

    def search(index: int, chosen: list[dict]) -> None:
        nonlocal examined
        if len(results) >= candidate_limit or examined >= candidate_limit * 10:
            return
        if index == len(options):
            examined += 1
            sections = chosen.copy()
            has_monday = any(meeting["day"].strip().lower().startswith("mon") for section in sections for meeting in section["meetings"])
            if monday_preference == "require" and not has_monday:
                return
            if monday_preference == "avoid" and has_monday:
                return
            preference_scores = []
            for section in sections:
                ranks = preferences.get(f"{section['program']}:{section['course_code']}", preferences.get(section["course_code"], []))
                if ranks:
                    preference_scores.append((len(ranks) - ranks.index(section["faculty"])) / len(ranks) if section["faculty"] in ranks else 0)
            active_days = len({meeting["day"] for section in sections for meeting in section["meetings"]})
            classes_by_day: dict[str, set[int]] = {}
            for section in sections:
                for meeting in section["meetings"]:
                    classes_by_day.setdefault(meeting["day"], set()).add(section["id"])
            daily_class_count = max((len(day_sections) for day_sections in classes_by_day.values()), default=0)
            if requested_class_count is not None and daily_class_count != requested_class_count:
                return
            priority_score = (sum(preference_scores) / len(preference_scores)) if preference_scores else 1.0
            gaps = idle_gap_minutes(sections)
            gap_score = max(0, 1 - gaps / 1000)
            score = round(priority_score * 70 + gap_score * 30)
            results.append({"sections": sections, "section_ids": [s["id"] for s in sections], "conflicts": [], "score": score, "priority_score": priority_score, "idle_gap_minutes": gaps, "active_days": active_days, "classes_per_day": daily_class_count})
            return
        viable = [candidate for candidate in options[index] if not conflicts([*chosen, candidate])]
        viable.sort(key=lambda candidate: (faculty_priority(candidate), idle_gap_minutes([*chosen, candidate]), candidate["section"]))
        for candidate in viable:
            search(index + 1, [*chosen, candidate])

    search(0, [])
    results.sort(key=lambda item: (-item["score"], -item["priority_score"], item["idle_gap_minutes"] if gap_order == "shortest" else -item["idle_gap_minutes"], item["active_days"], item["section_ids"]))
    if not results:
        if monday_preference == "require" and requested_class_count is not None:
            message = f"No conflict-free routine matches both Monday classes and exactly {requested_class_count} classes on the busiest day. Change one of those choices and try again."
        elif monday_preference == "require":
            message = "No conflict-free routine can schedule any selected course on Monday. Choose different courses or turn off the Monday requirement."
        elif monday_preference == "avoid" and requested_class_count is not None:
            message = f"No conflict-free routine matches exactly {requested_class_count} classes on the busiest day without Monday classes. Change one of those choices and try again."
        elif monday_preference == "avoid":
            message = "No conflict-free routine is available without Monday classes. Choose different courses or allow Monday classes."
        elif requested_class_count is not None:
            message = "No routine matches that classes-per-day choice. Try a different count."
        else:
            message = "No conflict-free combination exists for the selected courses."
        raise HTTPException(422, {"message": message, "courses": course_codes})
    return {"routines": results[:limit], "count": min(len(results), limit), "courses": course_codes}


@app.post("/api/routines")
def save_routine(payload: RoutineIn):
    sections = read_sections(payload.section_ids)
    collisions = conflicts(sections)
    if collisions:
        raise HTTPException(422, {"message": "This routine has timetable conflicts.", "conflicts": collisions})
    with Session(engine) as db:
        record = RoutineRecord(name=payload.name, section_ids=payload.section_ids, preferences=payload.preferences)
        db.add(record); db.commit(); db.refresh(record)
        return {"id": record.id, "name": record.name, "section_ids": record.section_ids, "preferences": record.preferences}


@app.get("/api/routines")
def list_routines():
    with Session(engine) as db:
        routines = db.scalars(select(RoutineRecord).order_by(RoutineRecord.id.desc())).all()
        return [{"id": row.id, "name": row.name, "section_ids": row.section_ids, "preferences": row.preferences} for row in routines]


@app.get("/api/routines/{routine_id}")
def get_routine(routine_id: int):
    with Session(engine) as db:
        routine = db.get(RoutineRecord, routine_id)
        if not routine:
            raise HTTPException(404, "Saved routine not found.")
        return {"id": routine.id, "name": routine.name, "sections": read_sections(routine.section_ids), "preferences": routine.preferences}


@app.delete("/api/routines/{routine_id}")
def delete_routine(routine_id: int):
    with Session(engine) as db:
        routine = db.get(RoutineRecord, routine_id)
        if not routine:
            raise HTTPException(404, "Saved routine not found.")
        db.delete(routine); db.commit()
        return {"deleted": True}


def build_routine_pdf(name: str, sections: list[dict]) -> io.BytesIO:
    output = io.BytesIO(); pdf = canvas.Canvas(output, pagesize=letter)
    pdf.setTitle(name); pdf.setFont("Helvetica-Bold", 18); pdf.drawString(50, 750, name)
    pdf.setFont("Helvetica", 10); pdf.drawString(50, 730, "UIU Section Manager · Fall 2026")
    y = 690
    for section in sections:
        title = f"{section['course_code']} · {section['course_name']} · Section {section['section']}"
        pdf.setFont("Helvetica-Bold", 11); pdf.drawString(50, y, title[:100]); y -= 16
        pdf.setFont("Helvetica", 9); pdf.drawString(60, y, f"{section['program']} · {section['credits'] or '?'} credits · {section['faculty']} ({section['faculty_initial']})"); y -= 14
        for meeting in section["meetings"]:
            start = f"{meeting['start']//60:02d}:{meeting['start']%60:02d}"; end = f"{meeting['end']//60:02d}:{meeting['end']%60:02d}"
            pdf.drawString(60, y, f"{meeting['day']} {start}–{end} · {meeting.get('room') or 'Room not listed'}"); y -= 13
        y -= 7
        if y < 70:
            pdf.showPage(); y = 750
    pdf.save(); output.seek(0); return output


@app.get("/api/routines/{routine_id}/export.pdf")
def export_routine_pdf(routine_id: int):
    routine = get_routine(routine_id)
    output = build_routine_pdf(routine["name"], routine["sections"])
    return StreamingResponse(output, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=routine-{routine_id}.pdf"})


@app.get("/api/routines/{routine_id}/export.png")
def export_routine_png(routine_id: int):
    routine = get_routine(routine_id)
    sections = routine["sections"]
    days = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]
    left, top, label_width, col_width, hour_height = 90, 110, 76, 180, 74
    image = Image.new("RGB", (left + label_width + col_width * len(days) + 50, top + hour_height * 10 + 55), "#eef5fc")
    draw = ImageDraw.Draw(image)
    regular = ImageFont.load_default(); bold = ImageFont.load_default()
    draw.text((left, 28), routine["name"], fill="#1e334b", font=bold)
    draw.text((left, 54), "UIU · Fall 2026", fill="#667c94", font=regular)
    for index, day in enumerate(days):
        x = left + label_width + index * col_width
        draw.text((x + 8, top - 27), day, fill="#328fc9", font=bold)
        draw.line((x, top, x, top + 9 * hour_height), fill="#dce7f1", width=1)
    for hour in range(8, 17):
        y = top + (hour - 8) * hour_height
        draw.text((left, y + 4), f"{hour%12 or 12}:00 {'AM' if hour < 12 else 'PM'}", fill="#667c94", font=regular)
        draw.line((left + label_width, y, left + label_width + len(days) * col_width, y), fill="#dce7f1", width=1)
    colors = [(216, 239, 255), (231, 224, 255), (218, 244, 227), (255, 237, 205)]
    for section in sections:
        color = colors[(section["source_serial"] or 0) % len(colors)]
        for meeting in section["meetings"]:
            if meeting["day"] not in days:
                continue
            day_index = days.index(meeting["day"])
            x = left + label_width + day_index * col_width + 4
            y = top + ((meeting["start"] - 480) / 60) * hour_height + 3
            bottom = top + ((meeting["end"] - 480) / 60) * hour_height - 3
            if bottom <= top or y >= top + 9 * hour_height:
                continue
            y = max(y, top); bottom = min(bottom, top + 9 * hour_height)
            draw.rounded_rectangle((x, y, x + col_width - 8, bottom), radius=8, fill=color, outline=(96, 175, 220), width=2)
            draw.text((x + 6, y + 6), f"{section['course_code']} {section['section']}", fill="#1e4c68", font=bold)
            if bottom - y > 32:
                draw.text((x + 6, y + 22), section["faculty"][:24], fill="#45677c", font=regular)
            if bottom - y > 48:
                draw.text((x + 6, y + 36), meeting.get("room", "")[:20], fill="#45677c", font=regular)
    output = io.BytesIO(); image.save(output, format="PNG", optimize=True); output.seek(0)
    return StreamingResponse(output, media_type="image/png", headers={"Content-Disposition": f"attachment; filename=routine-{routine_id}.png"})

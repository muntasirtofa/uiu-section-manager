# UIU Section Manager · Fall 2026

UIU Section Manager is preloaded from the supplied **Class Routine with faculty assign Fall 2026.pdf**. Students do not upload schedules. The bundled source PDF and its extracted catalog power section browsing, course and faculty directories, conflict-aware routine generation, saved plans, and PDF/PNG exports.

## Built-in schedule data

The 54-page PDF is stored at `backend/data/fall_2026_course_offerings.pdf`. The checked-in normalized extract is `backend/data/fall_2026_sections.json`; it contains 791 rows across BSCSE and BSDS, preserving 101 course codes, section labels, meeting days and times, rooms, faculty and faculty-initial fields, credits, PDF row/page references, and the source table cells. The API seeds `uiu_fall2026.db` from this extract when it starts and synchronizes bundled records on subsequent starts. Saved routines remain in that local database.

The PDF has dense Excel-style tables; the extractor reconstructs a few visibly clipped lab course titles and numeric credit cells where the adjacent table cell contains their overflow. Every extracted source cell remains available as `source_fields` for auditing. Faculty entries marked TBA remain TBA, as in the source.

## Start locally

Requirements: Node.js 20+ and Python 3.11+.

```powershell
npm install
npm run dev
```

In another terminal:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
py -3.14 -m pip install -r backend/requirements.txt
py -3.14 -m uvicorn app.main:app --app-dir backend --reload
```

Open `http://localhost:5173`. Interactive API documentation is at `http://localhost:8000/docs`.

## Database configuration

SQLite is the default and uses `uiu_fall2026.db` in the current working directory. To use PostgreSQL, install the listed `psycopg` driver and set `DATABASE_URL`, for example:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://uiu:password@localhost:5432/uiu_sections'
$env:CORS_ORIGINS = 'http://localhost:5173'
```

The configured database is initialized with the bundled catalog when empty; catalog entries are refreshed from the checked-in extract at app startup. Do not place credentials in source control.

## Features

- Filter the Fall 2026 section catalog by program, course, faculty, or section.
- Browse course offerings and faculty assignments.
- Select up to eight courses and prefer an instructor for any selected course.
- Generate multiple alternatives that include one section per requested course and reject overlapping meetings.
- Save, reopen, delete, and export routines as PDF or PNG.
- Open the bundled original PDF directly from the app.
- Switch between persistent light and dark themes.

## Rebuild the extract

The user-provided source PDF is bundled with the project; the extraction script never asks a student to upload a file.

```powershell
py -3.14 -m backend.app.pdf_catalog
```

## Verify

```powershell
py -3.14 -m pytest backend/tests
npm test
npm run build
```

## Deployment and remaining work

Build the frontend with `npm run build`, serve `dist/`, and deploy FastAPI with PostgreSQL configured via `DATABASE_URL` and the frontend origin listed in `CORS_ORIGINS`. Use HTTPS and managed secrets in production.

The current backend creates tables directly with SQLAlchemy; Alembic migrations and authentication are not included. The PDF contains some table cells whose original text is clipped/overlapped in the PDF itself; original extracted cells are retained so those records can be corrected if UIU provides a cleaner source. OCR is not needed for this text-based catalog. Schedule results are based only on the meeting data present in this specific Fall 2026 PDF.

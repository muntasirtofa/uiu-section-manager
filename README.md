# UIU Section Manager — Fall 2026

UIU Section Manager is a React/Vite application with a FastAPI backend. It uses the bundled Fall 2026 section catalog and PDF for browsing, faculty/course lookup, conflict-aware schedule generation, saved routines, and PDF/PNG exports. Students do not upload a schedule.

## Bundled catalog

The original PDF is `backend/data/fall_2026_course_offerings.pdf`. Its normalized extract is `backend/data/fall_2026_sections.json`, with 791 section rows across BSCSE and BSDS. The source files are resolved relative to the backend package, so they remain available when Render runs the service from `backend/`.

At backend startup, SQLAlchemy creates missing tables and inserts catalog rows whose source serial is not already present. Existing section rows and saved routines are not replaced or deleted. PostgreSQL is the recommended production database; SQLite remains the local default. Database schema changes are not migrated automatically, so use a migration tool such as Alembic before deploying future model changes that alter existing tables.

## Run locally

Requirements: Node.js 20+ and Python 3.11+.

From the repository root, create the local environment file and install the frontend dependencies:

```powershell
Copy-Item .env.example .env
npm install
npm run dev
```

In another PowerShell terminal, install and run the backend:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000
```

Open <http://localhost:5173>. API documentation is at <http://localhost:8000/docs> and the database-aware health check is <http://localhost:8000/api/health>.

The root `.env` is read by Vite and by the backend. `.env.example` contains local-only defaults and is safe to copy. It is not committed with credentials. SQLite files are created relative to the backend process working directory and are ignored by Git. For a stable local SQLite location, run the backend from the repository root as shown above.

### Local environment variables

```dotenv
DATABASE_URL=sqlite:///./uiu_fall2026.db
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
VITE_API_URL=http://localhost:8000
```

`VITE_API_URL` is used for all browser-to-backend requests. If you change it, restart the Vite dev server. The backend defaults to SQLite when `DATABASE_URL` is not set.

## Production deployment

The repository includes `render.yaml` for the FastAPI service and `vercel.json` for Vite's static build and client-side routes. No production URL or secret is embedded in source.

### 1. Create persistent PostgreSQL

Create a managed PostgreSQL database in Render (or another provider) before deploying the backend. Copy the provider's connection URL from its dashboard. Keep it private. Render's PostgreSQL URL may start with `postgres://` or `postgresql://`; the backend converts compatible PostgreSQL URLs to the installed Psycopg 3 dialect while preserving encoded credentials and query parameters.

For a local PostgreSQL instance, a SQLAlchemy URL can look like this (replace all placeholders; do not commit it):

```text
postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME
```

If a username or password contains reserved URL characters, percent-encode those values. The URL parser preserves the encoded credentials and provider query options.

### 2. Deploy the backend to Render

1. In Render, create a Blueprint from this GitHub repository, or create a Web Service manually.
2. For a manual service, set **Root Directory** to `backend`, **Build Command** to `pip install -r requirements.txt`, and **Start Command** to `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Add these backend environment variables in the Render service settings:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | The private PostgreSQL connection URL supplied by your database provider. |
   | `CORS_ORIGINS` | The exact Vercel frontend origin, for example `https://your-project.vercel.app` (no trailing slash). |

   `render.yaml` declares both variables as secrets/values to enter in the dashboard. Render supplies `$PORT`; the start command binds to `0.0.0.0` and uses that value.
4. Deploy. The first start creates the current tables and seeds only missing Fall 2026 catalog rows. Save the public backend URL shown by Render, for example `https://your-service.onrender.com`.
5. Verify `https://your-service.onrender.com/api/health`. It should return `status: ok` and `database: connected`. Also check `/docs` and `/api/overview`.

Do not configure a SQLite file for the public service. Render's service filesystem is not a substitute for a managed persistent database. Saved routines persist in PostgreSQL across ordinary restarts and redeploys.

### 3. Deploy the frontend to Vercel

1. Import the repository into Vercel. Keep **Root Directory** at the repository root.
2. Use framework **Vite**, build command `npm run build`, and output directory `dist`. `vercel.json` supplies these settings and a rewrite for React Router pages such as `/generator` and `/courses/...`.
3. In Vercel project settings, add this environment variable for the deployment environments you use:

   | Variable | Value |
   | --- | --- |
   | `VITE_API_URL` | The Render backend's public HTTPS origin, such as `https://your-service.onrender.com` (no `/api` suffix and no trailing slash). |

4. Deploy the frontend. Copy its exact origin (scheme and hostname, without a path or trailing slash) into Render's `CORS_ORIGINS` setting. If you use a Vercel preview domain, add each preview origin you want to authorize as another comma-separated origin.
5. Redeploy the Render backend after changing `CORS_ORIGINS`, then redeploy Vercel after changing `VITE_API_URL`.

Vite embeds `VITE_API_URL` into the JavaScript bundle at build time. Updating that setting in Vercel requires a new Vercel deployment before the browser uses the new backend URL.

## Verify changes locally

From the repository root:

```powershell
py -3 -m pytest backend/tests
npm test
npm run build
```

The tests use the configured database and may create a temporary export-test routine, which they delete afterward. Do not point test runs at a production database.

## Troubleshooting

- **Browser reports a CORS error:** Set Render `CORS_ORIGINS` to the exact Vercel origin, including `https://` and excluding a path or trailing slash. Multiple origins are comma-separated. Redeploy the backend after changing it.
- **Database connection or startup failure:** Confirm Render `DATABASE_URL` is set to the provider's reachable PostgreSQL URL, the database is available to the web service, and the account can create/use tables. The API returns a generic database health error and does not include credentials in its response.
- **Frontend says the backend cannot be reached or gets 404s:** Check Vercel `VITE_API_URL` is the Render service origin only (no `/api` suffix), then redeploy Vercel. Visit the backend `/api/health` URL directly.
- **`/generator` or another nested page returns 404 on refresh:** Ensure the Vercel deployment includes this repository's `vercel.json` rewrite and was redeployed.
- **SQLite appears to lose data locally:** SQLite uses a file, so run the backend consistently from the repository root or use an absolute SQLite path. Production must use PostgreSQL.
- **Existing local routines do not appear in the new production database:** Local SQLite and the production PostgreSQL database are separate stores. This deployment setup preserves records already in the selected PostgreSQL database; it does not automatically copy a local SQLite database into it. Export or migrate records deliberately before switching users.

## Features

- Browse and filter section records by program, course, instructor, or section.
- Browse unique courses and their faculty/section assignments.
- Select up to eight courses, rank instructors, and generate conflict-free schedule alternatives.
- Compare faculty preference matches and idle time, with class-count and Monday filters.
- Save, reopen, delete/undo-delete, and export routines as PDF or PNG.
- Open the bundled original PDF and switch between light and dark themes.

## Rebuild the normalized catalog

The source PDF is bundled with the repository; students are not asked to upload it.

```powershell
py -3 -m backend.app.pdf_catalog
```

This command rewrites the checked-in JSON extract. Review the diff before committing a refreshed catalog.

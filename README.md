# UIU Section Manager — Fall 2026

UIU Section Manager is a static React, TypeScript, and Vite app. It reads the bundled Fall 2026 catalog in the browser, generates conflict-free routines, and stores saved plans only in the current browser. It does not need a running API server or an external database.

## Run locally

Requirements: Node.js 20+ and npm.

```powershell
npm install
npm run dev
```

Open <http://localhost:5173>. The catalog loads from `public/data/fall_2026_sections.json`; the source PDF is available at `/data/fall_2026_course_offerings.pdf`. The checked-in source copies remain in `backend/data/` for catalog provenance and optional extraction workflows.

No environment variables are needed. `.env.example` is retained as a reminder that the frontend has no secrets or runtime API configuration.

## Deploy on Vercel Hobby

1. Push this repository to GitHub.
2. In Vercel, choose **Add New → Project** and import `muntasirtofa/uiu-section-manager`.
3. Set the repository root as the **Root Directory**. Select **Vite** (or allow Vercel to detect it).
4. Use build command `npm run build` and output directory `dist`. The repository's `vercel.json` configures these values and sends app routes back to `index.html` so refreshes on pages such as `/generator` work.
5. Leave environment variables empty; the app does not use `VITE_API_URL`, database credentials, or API secrets.
6. Select **Deploy**. Vercel will build and host the static site. Future pushes to the connected production branch deploy automatically.

To update the public deployment after making changes, commit and push from the repository root:

```powershell
git add .
git commit -m "Prepare UIU Section Manager for Vercel-only deployment"
git push origin main
```

Use your actual working branch instead of `main` if it differs. Vercel creates a deployment from the connected branch; you can also open the project in Vercel and choose **Redeploy** on the latest deployment.

## Browser data and privacy

The bundled JSON catalog contains 791 Fall 2026 section rows across BSCSE and BSDS, including faculty, rooms, credits, times, and source metadata. It powers course and section browsing, course/faculty search, schedule generation, priority scoring, idle-gap ordering, Monday and daily class-count filters, and conflict detection. PDF and PNG routine exports are created locally in the browser.

Saved routines and theme preference use browser localStorage. They belong to the current browser/device and are not synchronized with other users or devices. Clearing browser site data removes local routines. There is no account or server-side save feature.

## Checks

```powershell
npm test
npm run build
```

## Troubleshooting

- **The catalog cannot load:** confirm the deployment contains `public/data/fall_2026_sections.json`, then redeploy. The app displays a catalog error if that bundled file is missing or invalid.
- **A nested route returns 404 after refresh:** confirm `vercel.json` is at the repository root and redeploy.
- **A routine disappeared:** local routines are tied to the browser profile and device where they were saved. Check that the browser's site data was not cleared and that you are using the same profile.
- **PDF or PNG export does not download:** allow downloads for the site and use a current browser. PNG export uses the browser canvas API.

## Refreshing the catalog

The original PDF and normalized JSON are preserved under `backend/data/`. `backend/app/pdf_catalog.py` is the extractor used to normalize the source PDF. If the official source changes, review the extraction diff and copy the approved JSON and PDF into `public/data/` before committing so the deployed frontend receives the updated records.

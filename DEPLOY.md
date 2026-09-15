# Deployment

Two independently deployable pieces:

- **`web/`** — Next.js + TypeScript frontend. Deploys natively to **Vercel** or
  **Netlify** (both are built for this).
- **`src/jobengine/`** — FastAPI backend + Postgres. Needs a host with a
  persistent process and a real database — Vercel/Netlify's serverless
  functions have no persistent filesystem and can't hold a long-lived
  connection pool, so the backend goes elsewhere (Railway, Render, Fly.io, or
  any VM). This is a deliberate split, not a limitation to work around.

## 1. Database — Supabase or Neon (free tier)

Either works; both hand you back a standard Postgres connection string.

1. Create a project at supabase.com or neon.tech.
2. Copy the connection string (Session/Transaction pooler URL for Supabase,
   the default one for Neon).
3. Convert it to the SQLAlchemy form JobEngine expects:
   `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME`
   (same string, just add `+psycopg` after `postgresql`).

## 2. Backend — Railway / Render / Fly.io

Set the `DATABASE_URL` environment variable to the string from step 1, then:

```bash
pip install -e ".[postgres]"
jobengine fetch
jobengine build          # one-time; re-run on a schedule to refresh listings
jobengine serve --host 0.0.0.0 --port $PORT
```

Environment variables the backend reads (see `config.py` / `db.py`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (SQLAlchemy form above). Unset → falls back to a local SQLite file. |
| `JOBENGINE_CORS_ORIGINS` | Comma-separated allowed origins for the frontend. Unset → `*` (fine for a demo, tighten for anything public). |
| `JOBENGINE_RESUME` | Path to `resume.json`, only needed for `jobengine tailor`. |

Set `JOBENGINE_CORS_ORIGINS` to your Vercel/Netlify URL once deployed, e.g.
`https://your-app.vercel.app`.

Refreshing data on a schedule: the existing `.github/workflows/refresh-data.yml`
can be pointed at the deployed backend instead of committing `data/` back to
the repo — call `jobengine fetch && jobengine build` from a scheduled job
(GitHub Actions, Railway cron, etc.) with `DATABASE_URL` set as a secret.

## 3. Frontend — Vercel or Netlify

Both platforms auto-detect Next.js. Point either at the `web/` subdirectory:

**Vercel**
```bash
cd web
vercel                          # first deploy, follow the prompts
vercel env add NEXT_PUBLIC_API_URL production   # paste your backend's public URL
vercel env add NEXT_PUBLIC_SITE_URL production  # paste THIS site's own URL, e.g. https://roleradar.vercel.app
vercel --prod
```
Or via the dashboard: New Project → import the repo → set **Root Directory**
to `web` → add `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_SITE_URL` under
Environment Variables.

**Netlify**
```bash
cd web
netlify init
netlify env:set NEXT_PUBLIC_API_URL https://your-backend-host
netlify env:set NEXT_PUBLIC_SITE_URL https://your-site-host
netlify deploy --prod
```
Or via the dashboard: New site from Git → **Base directory** `web` → Netlify
auto-detects the Next.js build → add `NEXT_PUBLIC_API_URL` and
`NEXT_PUBLIC_SITE_URL` under Site settings → Environment variables.

`NEXT_PUBLIC_SITE_URL` is not optional in the way it might look. It backs
`metadataBase` (`app/layout.tsx`), which every social-preview image and the
sitemap/robots files resolve against — unset, they fall back to
`http://localhost:3000` and a shared link's preview image silently fails to
load for anyone who isn't you.

## Local dev (no cloud accounts needed)

```bash
docker run -d --name jobengine-pg -e POSTGRES_USER=jobengine \
  -e POSTGRES_PASSWORD=jobengine -e POSTGRES_DB=jobengine \
  -p 55432:5432 postgres:16-alpine

export DATABASE_URL="postgresql+psycopg://jobengine:jobengine@localhost:55432/jobengine"
jobengine fetch && jobengine build
jobengine serve --port 8765        # backend, http://127.0.0.1:8765/docs for OpenAPI

cd web && npm install && npm run dev   # frontend, http://localhost:3000
```

Unset `DATABASE_URL` to fall back to the original zero-setup SQLite file —
every module in `src/jobengine/` works identically on either backend.

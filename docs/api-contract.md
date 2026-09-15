# API contract

## Spring Boot online API (`/api/v1`)

- `GET /jobs` — cached search with location, sponsorship tier, company,
  seniority, and skill filters.
- `GET /jobs/tiers` — active counts by sponsorship tier.
- `GET /jobs/stats` — corpus and deduplication statistics.
- `GET /jobs/dedup-conflicts` — canonical-URL clusters for dedup review.
- `POST /jobs/match` — explainable profile-to-job lexical score with evidence.
- `GET|POST /applications` — user-scoped tracker list/create.
- `POST /applications/{appId}/status` — transactional status transition.
- `DELETE /applications/{appId}` — user-scoped deletion.
- `GET /openapi.json` and `GET /docs` — generated OpenAPI and Swagger UI.

Search accepts an optional `X-API-Key`; tracker routes additionally require the
Bearer JWT issued by the Python authentication service.

Base URL (local): `http://127.0.0.1:8765`

The machine-readable contract is [`openapi.json`](openapi.json), exported from
the running application. It is generated from the same Pydantic models that
validate requests at runtime, so it cannot drift from the implementation. A
live, browsable version is served at `/docs` whenever the API is running.

Regenerate it after changing any route:

```bash
python -c "import json;from jobengine.api import app;json.dump(app.openapi(),open('docs/openapi.json','w'),indent=2)"
```

## Conventions

**Authentication.** `Authorization: Bearer <token>`, obtained from
`/api/auth/register` or `/api/auth/login`. Tokens are HS256 JWTs signed with
`JOBENGINE_SECRET_KEY`.

**Errors.** Every error response is `{"detail": "<human-readable message>"}`.
Validation failures (422) use FastAPI's structured detail array instead.

| Status | Meaning |
|---|---|
| 400 | Malformed request the schema accepted but the domain rejected (unknown status, invalid source) |
| 401 | Missing, malformed, or expired token; wrong credentials |
| 404 | Resource doesn't exist, **or exists but belongs to another user** — deliberately indistinguishable, so the API can't be used to enumerate other users' application ids |
| 422 | Request body failed schema validation |
| 503 | Database unreachable, pipeline data missing, or connection pool exhausted (sent with `Retry-After`) |

**Every response** carries `X-Response-Time-ms`, the server-side handling time
in milliseconds.

**Ownership.** Every `/api/applications` route is scoped to the authenticated
caller. There is no way to read or modify another user's rows.

## Endpoints

### Operations

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | No | Liveness + readiness. Executes `SELECT 1`, so it fails when the database is unreachable rather than reporting a healthy-but-useless process. |
| `GET` | `/api/analytics/summary?hours=24` | Yes | Traffic, latency percentiles, error rate, active users. |

```jsonc
// GET /api/health → 200
{ "status": "ok", "version": "0.4.0", "backend": "postgresql" }
```

```jsonc
// GET /api/analytics/summary?hours=24 → 200
{
  "window_hours": 24,
  "requests": 1482,
  "registered_users": 12,
  "active_users": 7,
  "error_rate": 0.0,           // 5xx only
  "client_error_rate": 0.021,  // 4xx, reported separately on purpose
  "throughput_rps": 0.0172,
  "latency_ms": { "p50": 11, "p95": 48, "p99": 132, "max": 410 },
  "by_route": [
    { "route": "/api/jobs", "requests": 900, "p50_ms": 14, "p95_ms": 52, "errors": 0 }
  ]
}
```

*(Shape is real; the values above are illustrative placeholders — no traffic has
been recorded yet. See [known-limitations.md](known-limitations.md).)*

### Auth

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/auth/register` | `{email, password}` | `201 {token, email}` |
| `POST` | `/api/auth/login` | `{email, password}` | `200 {token, email}` |
| `GET` | `/api/auth/me` | — | `200 {token: "", email}` |

Emails are lowercased on write. Passwords must be at least 8 characters and are
stored as bcrypt hashes. `/api/auth/me` returns an empty `token` field
deliberately — it confirms who you are without minting a new credential.

### Jobs — read-only, public

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/jobs` | Filter and rank listings |
| `GET` | `/api/jobs/summary` | Counts by sponsorship tier |
| `POST` | `/api/jobs/semantic-search` | Vector similarity search (Postgres only) |

`GET /api/jobs` query parameters:

| Param | Type | Default | Notes |
|---|---|---|---|
| `grad` | `intern` \| `newgrad` | all | |
| `tier` | comma-separated | all | e.g. `very_high,high` (see tier values below) |
| `location` | comma-separated | all | Substring match |
| `max` | int | 200 | **Not clamped server-side** — a known limitation |
| `agencies` | bool | `false` | Include staffing agencies |

Returns `503` when the pipeline hasn't been built yet, because an empty array
would be indistinguishable from "there are no matching jobs."

`POST /api/jobs/semantic-search` takes `{text, max}` and returns jobs with a
`distance` field (cosine distance, lower is closer). It returns `503` on the
SQLite backend — see [ADR-003](decisions.md) for why it fails loudly instead of
silently falling back to lexical matching.

### Applications — full CRUD, per-user, auth required

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/applications?status=` | List your applications |
| `GET` | `/api/applications/summary` | Counts by status |
| `POST` | `/api/applications` | Create → `201 {app_id}` |
| `PATCH` | `/api/applications/{app_id}` | Edit mutable fields |
| `POST` | `/api/applications/{app_id}/status` | Transition status |
| `DELETE` | `/api/applications/{app_id}` | Delete (cascades history) |
| `GET` | `/api/applications/{app_id}/history` | Status event log |
| `POST` | `/api/parse-email` | Classify a recruiter email into a status signal |

`PATCH` deliberately **cannot** change `status`. Status moves only through the
status endpoint, so every transition writes a `status_events` row and the
history stays complete. Splitting these was a design choice, not an oversight.

`source` must be one of `linkedin`, `company_site`, `simplify`, `referral`,
`email`, `other`. `status` must be one of `saved`, `applied`, `heard_back`,
`oa`, `interview`, `offer`, `rejected`, `withdrawn`.

Unusual status transitions (a rejection from a stage the system never saw) are
**accepted and logged**, not rejected — see [database.md](database.md#status-state-machine).

## Versioning

Currently unversioned; the API and its only frontend ship together. The
version string in `/api/health` reflects the application version and is
informational. If a third party ever integrates, the path prefix becomes
`/api/v1/` and this section gets a deprecation policy.

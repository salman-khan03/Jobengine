# Testing strategy

## Current state

61 tests, all passing, running on every push via
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) alongside `ruff` and
`mypy`. Run them with:

```bash
python -m pytest -q
```

## What is tested, and why that

The suite is not organized by coverage percentage. It is organized around the
places where a bug would be **silent** — where the code returns a plausible
wrong answer instead of crashing.

| Area | Module | Why it earns tests |
|---|---|---|
| Normalization + dedup | `normalize.py` | A dedup key that's subtly wrong produces duplicate listings that look fine individually. Nothing crashes; the product just quietly gets worse. |
| Sponsorship matching | `sponsor_index.py` | The core claim of the product. A false "strong sponsor" sends someone to apply into a dead end — the exact failure the project exists to prevent. |
| Multi-tenancy | `tracker.py`, `seed_demo.py` | A missing `user_id` filter leaks one user's data to another and produces no error. |
| Auth | `auth.py` | Token forgery and password handling fail closed only if tested. |
| Analytics maths | `analytics.py` | An off-by-one in the percentile index makes every number on the dashboard wrong but still plausible. |
| Resilience | `analytics.py` | The "never raises" guarantee is a claim; it's tested by making the database throw. |
| Status machine | `tracker.py` | History is append-only; a lost event can't be reconstructed. |

## Test levels

**Unit (majority).** Pure functions with no I/O — normalization, percentiles,
matching, the audit rules. Fast, deterministic, and where most edge cases live.

**Integration (`test_analytics.py`, `test_auth.py`, `test_tracker.py`).** Real
database, real FastAPI request cycle via `TestClient`. Each test gets a fresh
SQLite file through the `isolated_db` fixture, which monkeypatches
`config.DB_PATH` — this only works because `db.get_engine()` resolves the URL
lazily instead of baking an engine in at import time. That design choice exists
*for* testability.

**Contract (via schema).** Every route is typed with Pydantic, so the OpenAPI
document at `/openapi.json` is generated from the same models that validate
requests. The schema cannot drift from the implementation because it *is* the
implementation.

**Load ([`loadtest/`](../loadtest/README.md)).** k6 against Postgres in Docker.
Two profiles: `baseline` (50 VU, hard thresholds, safe to gate CI) and `stress`
(300 VU, no thresholds — the point is to find the breaking point).

## Portability testing

The same suite runs on both backends. Locally it's SQLite; setting
`DATABASE_URL` to a Postgres instance runs the identical tests against
Postgres. This catches the class of bug where SQLite's permissiveness (no
enforced foreign keys by default, looser typing) hides something Postgres will
reject in production.

```bash
DATABASE_URL=postgresql+psycopg://jobengine:jobengine@localhost:55432/jobengine python -m pytest -q
```

## What is deliberately not tested

- **The upstream feeds themselves.** `fetch.py`'s retry and failure handling is
  tested; whether GitHub is up is not this suite's business.
- **The optional LLM call.** Non-deterministic by nature. The offline fallback
  path is tested; the model's output quality is not something a unit test can
  assert.
- **The Next.js UI.** Type-checked and build-verified, but there are no
  component or end-to-end tests. This is the largest real gap — see below.

## Known gaps

1. **No frontend tests.** `tsc --noEmit` and a successful production build
   catch type and compile errors, and nothing else. A Playwright smoke test
   covering register → add application → change status → verify would catch
   the integration failures that matter most.
2. **No mutation testing.** Line coverage says a line ran, not that a bug in it
   would fail a test. `mutmut` on `normalize.py` and `sponsor_index.py` would
   be the highest-value place to check.
3. **No property-based tests.** `normalize.py` is a natural fit for Hypothesis
   — invariants like "normalizing twice equals normalizing once" are exactly
   what property tests find counterexamples to.
4. **No concurrency tests.** Two simultaneous status updates to the same
   application are untested. The load harness exercises concurrency at the HTTP
   level but doesn't assert on the resulting data.

## CI gates

| Gate | Tool | Blocks merge |
|---|---|---|
| Lint | `ruff check` | Yes |
| Types | `mypy src/jobengine` | Yes |
| Tests | `pytest` | Yes |
| Frontend types | `tsc --noEmit` | Yes |
| Frontend build | `next build` | Yes |
| Load baseline | `k6 run` | Not yet — needs a stable runner with Postgres |

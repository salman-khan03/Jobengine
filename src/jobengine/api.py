"""Typed HTTP API over the jobs/applications data — FastAPI, async-capable,
auto-generated OpenAPI docs at /docs.

This is the integration point: the Next.js frontend (or anything else) talks
to this instead of re-implementing fetch/dedupe/sponsorship in JavaScript.
`jobs` endpoints are read-only (the pipeline is the source of truth for
postings); `applications` endpoints are full CRUD, backed by tracker.py, and
require a logged-in user — each user only ever sees their own applications
(see db.py's note on `applications.user_id` for why the CLI stays unauthed
and separate). Every route is typed with Pydantic models, which is what
FastAPI uses to generate /docs and /openapi.json for free.

Run:  jobengine serve [--port 8765]
CORS is permissive (allow_origins=["*"]) since this is a local dev tool, not
a multi-tenant service — tighten it (JOBENGINE_CORS_ORIGINS) before deploying
publicly.
"""
from __future__ import annotations

import os
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from sqlalchemy.exc import TimeoutError as PoolTimeout

from . import analytics, auth, db, embeddings, query, tracker
from .logging_config import get_logger

log = get_logger(__name__)

app = FastAPI(
    title="RoleRadar / JobEngine API",
    description=(
        "v1: sponsor-ranked job listings + per-user application tracker. "
        "v2 (/api/v2): evidence-grounded 'should I apply?' decisions with "
        "cited resume evidence, plus outcome tracking and ranking evaluation."
    ),
    version="2.0.0",
)

_origins = os.environ.get("JOBENGINE_CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins == "*" else _origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- cross-cutting middleware ----------------------------------------------

@app.middleware("http")
async def observe(request: Request, call_next):
    """Time every request, translate pool exhaustion into a 503, and record
    the result for analytics.

    Ordering matters: the timer starts before `call_next` and the analytics
    write happens after the response is produced, so instrumentation latency
    is never counted as endpoint latency.
    """
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except PoolTimeout:
        # Every connection is checked out and the pool_timeout elapsed. This
        # is backpressure, not a bug: answer 503 + Retry-After so clients back
        # off, instead of a 500 that says "unknown failure" and invites a
        # retry storm. This path is the one the load test provoked.
        log.warning("db pool exhausted serving %s %s", request.method, request.url.path)
        response = JSONResponse(
            {"detail": "database busy — retry shortly"},
            status_code=503, headers={"Retry-After": "1"},
        )
    duration_ms = (time.perf_counter() - started) * 1000

    # The matched route template ("/api/applications/{app_id}"); falls back to
    # a constant for unmatched paths so 404 scans can't inflate cardinality.
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or "<unmatched>"
    response.headers["X-Response-Time-ms"] = f"{duration_ms:.1f}"
    analytics.record(route_path, request.method, response.status_code, duration_ms,
                     user_id=getattr(request.state, "user_id", None))
    return response


_bearer = HTTPBearer(auto_error=False)


def current_user(request: Request,
                 creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> auth.User:
    if creds is None:
        raise HTTPException(401, "sign in required — missing Authorization: Bearer token")
    try:
        user = auth.decode_token(creds.credentials)
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc))
    # Stash on request.state so the analytics middleware can attribute the
    # request to a user without re-decoding the JWT a second time.
    request.state.user_id = user.user_id
    return user


# --- request/response models ----------------------------------------------

class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    email: str


class ApplicationCreate(BaseModel):
    company: str
    title: str
    source: str
    dedup_key: str | None = None
    status: str = "applied"
    url: str = ""
    notes: str = ""
    contact_email: str = ""


class ApplicationEdit(BaseModel):
    company: str | None = None
    title: str | None = None
    url: str | None = None
    notes: str | None = None
    contact_email: str | None = None
    source: str | None = None
    dedup_key: str | None = None


class StatusUpdate(BaseModel):
    status: str
    note: str = ""


class EmailParseRequest(BaseModel):
    text: str


class SemanticSearchRequest(BaseModel):
    text: str
    max: int = 10


# --- operations: health + analytics ----------------------------------------

@app.get("/api/health")
def health():
    """Liveness *and* readiness in one probe.

    Deliberately touches the database: an API process that is running but
    cannot reach Postgres is not healthy, and a health check that only proves
    "the process answers HTTP" will happily keep a broken instance in the load
    balancer. `SELECT 1` is cheap enough to poll every 30s.
    """
    try:
        with db.get_engine().connect() as conn:
            conn.execute(sql_text("SELECT 1"))
    except Exception as exc:
        log.error("health check failed: %s", exc)
        raise HTTPException(503, f"database unreachable: {type(exc).__name__}")
    return {
        "status": "ok",
        "version": app.version,
        "backend": db.get_engine().dialect.name,
    }


@app.get("/api/analytics/summary")
def analytics_summary(hours: int = 24, user: auth.User = Depends(current_user)):
    """Usage rollup. Auth-gated — traffic and user counts are not public."""
    return analytics.summary(hours=hours)


# --- auth --------------------------------------------------------------

@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register(body: RegisterRequest):
    try:
        user = auth.register(body.email, body.password)
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc))
    return AuthResponse(token=auth.create_token(user), email=user.email)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(body: LoginRequest):
    try:
        user = auth.login(body.email, body.password)
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc))
    return AuthResponse(token=auth.create_token(user), email=user.email)


@app.get("/api/auth/me", response_model=AuthResponse)
def me(user: auth.User = Depends(current_user)):
    return AuthResponse(token="", email=user.email)


# --- jobs (read-only, public — no login needed to browse) ------------------

@app.get("/api/jobs")
def get_jobs(grad: str | None = None, tier: str | None = None,
             location: str | None = None, max: int = 200,
             agencies: bool = False, company: str | None = None,
             skill: str | None = None):
    try:
        return query.query(
            grad=grad,
            tiers=tier.split(",") if tier else None,
            location=location.split(",") if location else None,
            max_rows=max,
            include_agencies=agencies,
            company=company,
            skill=skill,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


@app.get("/api/jobs/summary")
def get_jobs_summary():
    try:
        return query.summary_dict()
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/jobs/semantic-search")
def semantic_search_jobs(body: SemanticSearchRequest):
    results = embeddings.search_jobs(body.text, k=body.max)
    if not results and not db.pgvector_available():
        raise HTTPException(
            503,
            "Vector search needs Postgres with `jobengine build --embed` run first "
            "— unavailable on the SQLite backend.",
        )
    return results


# --- applications (full CRUD, per-user) -------------------------------------

@app.get("/api/applications")
def get_applications(status: str | None = None, user: auth.User = Depends(current_user)):
    return tracker.list_applications(status=status, user_id=user.user_id)


@app.get("/api/applications/summary")
def get_applications_summary(user: auth.User = Depends(current_user)):
    return tracker.summary(user_id=user.user_id)


@app.post("/api/applications", status_code=201)
def create_application(body: ApplicationCreate, user: auth.User = Depends(current_user)):
    try:
        app_id = tracker.add(tracker.Application(**body.model_dump()), user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"app_id": app_id}


@app.patch("/api/applications/{app_id}")
def edit_application(app_id: int, body: ApplicationEdit, user: auth.User = Depends(current_user)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        tracker.edit(app_id, user_id=user.user_id, **fields)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/applications/{app_id}/status")
def update_application_status(app_id: int, body: StatusUpdate, user: auth.User = Depends(current_user)):
    try:
        tracker.update_status(app_id, body.status, note=body.note, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.delete("/api/applications/{app_id}")
def delete_application(app_id: int, user: auth.User = Depends(current_user)):
    try:
        tracker.delete(app_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True}


@app.get("/api/applications/{app_id}/history")
def get_application_history(app_id: int, user: auth.User = Depends(current_user)):
    return tracker.history(app_id, user_id=user.user_id)


@app.post("/api/parse-email")
def parse_email(body: EmailParseRequest, user: auth.User = Depends(current_user)):
    return tracker.parse_email_signal(body.text)


# --- RoleRadar v2 ----------------------------------------------------------
# Imported last, and guarded, for two reasons: the import registers RoleRadar's
# tables on db.metadata (a side effect that must happen before init_db), and a
# packaging problem in the decision layer must degrade the API to "v1 only"
# rather than taking the whole service down with it.
try:
    from roleradar.api_v2 import router as _roleradar_router

    app.include_router(_roleradar_router)
    log.info("RoleRadar v2 decision endpoints mounted at /api/v2")
except Exception as exc:  # pragma: no cover - defensive, logged not silent
    log.error("RoleRadar v2 endpoints unavailable: %s", exc)


def main() -> int:
    import argparse
    import uvicorn

    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    a = p.parse_args()

    log.info("Serving JobEngine API on http://%s:%d  (docs at /docs)", a.host, a.port)
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Database engine + schema, portable across SQLite (local/test) and Postgres (deployed).

DATABASE_URL drives the backend: unset -> a local SQLite file at config.DB_PATH
(zero setup, matches the original stdlib-only pipeline); set to a Postgres URL
(Supabase, Neon, or the local Docker instance used in dev) -> Postgres. Every
other module talks to the `ENGINE` / table objects defined here instead of
importing sqlite3 or a Postgres driver directly, so switching backends never
touches build.py/query.py/tracker.py.
"""
from __future__ import annotations

import os

from sqlalchemy import (
    BigInteger, Column, ForeignKey, Index, Integer, MetaData, Table, Text, create_engine,
    event, text,
)
from sqlalchemy.engine import Engine

from . import config
from .embeddings import DIMS as EMBEDDING_DIMS

def _default_url() -> str:
    return f"sqlite:///{config.DB_PATH}"


def current_database_url() -> str:
    return os.environ.get("DATABASE_URL") or _default_url()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def pool_settings() -> dict[str, int]:
    """Connection-pool bounds for the Postgres backend.

    Defaults are deliberate, not arbitrary. Postgres' own `max_connections`
    is 100 out of the box, and every backend connection costs a process plus
    ~5-10MB. `pool_size + max_overflow` is the *per-API-process* ceiling, so
    the real budget is that sum times the number of uvicorn workers. 10 + 10
    leaves room for 4 workers (80 connections) plus the refresh pipeline and
    a psql session inside a stock 100-connection server.

    `pool_timeout` is the load-shedding knob: when every pooled connection is
    checked out, a request waits at most this long and then fails fast with a
    503 instead of piling up until the client times out. Unbounded queueing is
    what turns a slow database into a fully unavailable API.
    """
    return {
        "pool_size": _int_env("JOBENGINE_DB_POOL_SIZE", 10),
        "max_overflow": _int_env("JOBENGINE_DB_MAX_OVERFLOW", 10),
        "pool_timeout": _int_env("JOBENGINE_DB_POOL_TIMEOUT", 5),
        "pool_recycle": _int_env("JOBENGINE_DB_POOL_RECYCLE", 1800),
    }


def make_engine(url: str | None = None) -> Engine:
    url = url or current_database_url()
    # SQLite needs this to allow use across threads (the FastAPI request
    # handlers each get their own thread); Postgres ignores it.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs: dict[str, object] = {}
    if not url.startswith("sqlite"):
        # SQLite's default pool is a single connection per file and takes none
        # of these options; only the networked backend needs bounding.
        kwargs.update(pool_settings())
        # Recycle stale sockets rather than handing a request a connection the
        # server (or a load balancer) already closed.
        kwargs["pool_pre_ping"] = True
    engine = create_engine(url, future=True, connect_args=connect_args, **kwargs)
    if url.startswith("sqlite"):
        # SQLite ignores FK constraints (and thus ON DELETE CASCADE) unless
        # each connection turns this pragma on explicitly — Postgres enforces
        # them by default, so this only matters for the local/test backend.
        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys = ON")
    return engine


_engine_cache: dict[str, Engine] = {}


def get_engine() -> Engine:
    """(Re)build the engine from the *current* DATABASE_URL / config.DB_PATH.

    A module-level Engine baked in at import time would break: (a) tests that
    monkeypatch config.DB_PATH per-test for an isolated throwaway DB, and (b)
    anything that sets DATABASE_URL after jobengine.db has already been
    imported. Engines are cached per URL (they hold a connection pool and are
    meant to be long-lived), so this only pays the construction cost once per
    distinct URL.
    """
    url = current_database_url()
    eng = _engine_cache.get(url)
    if eng is None:
        eng = _engine_cache[url] = make_engine(url)
    return eng


# Module-level dynamic attributes (PEP 562): `db.ENGINE` and `db.DATABASE_URL`
# always reflect the *current* config/env rather than a value frozen at
# import time, without callers having to switch to get_engine() everywhere.
def __getattr__(name: str):
    if name == "ENGINE":
        return get_engine()
    if name == "DATABASE_URL":
        return current_database_url()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


metadata = MetaData()

jobs = Table(
    "jobs", metadata,
    Column("dedup_key", Text, primary_key=True),
    Column("id", Text),
    Column("source_repo", Text),
    Column("company", Text),
    Column("company_norm", Text),
    Column("title", Text),
    Column("title_norm", Text),
    Column("category", Text),
    Column("active", Integer),
    Column("is_visible", Integer),
    Column("terms", Text),
    # BigInteger, not Integer: these are Unix epoch seconds, and Postgres maps
    # Integer to int4, which overflows on 2038-01-19. SQLite's dynamic typing
    # hid this entirely — it was only caught when the Spring Boot service's
    # Hibernate `ddl-auto: validate` refused to start against the real schema.
    # Safe to change without a migration because `jobs` is derived data that is
    # rebuilt from upstream on every pipeline run (see docs/architecture.md).
    Column("date_posted", BigInteger),
    Column("date_updated", BigInteger),
    Column("url", Text),
    Column("url_canon", Text),
    Column("locations", Text),
    Column("company_url", Text),
    Column("sponsorship_simplify", Text),
    Column("degrees", Text),
    Column("sponsor_tier", Text),
    Column("sponsor_lca_count", Integer),
    Column("sponsor_match", Text),
)
Index("idx_jobs_active", jobs.c.active, jobs.c.category)
Index("idx_jobs_sponsor", jobs.c.sponsor_tier)

users = Table(
    "users", metadata,
    Column("user_id", Integer, primary_key=True, autoincrement=True),
    Column("email", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

applications = Table(
    "applications", metadata,
    Column("app_id", Integer, primary_key=True, autoincrement=True),
    # Nullable and NOT a hard FK on purpose: rows created by the local CLI
    # (a trusted single-user surface, never gated behind login) have no
    # owner. Only the HTTP API is multi-user — it requires auth and always
    # writes/reads with a real user_id, so CLI rows simply never appear
    # through the API. Two access surfaces, one table, no migration drama.
    Column("user_id", Integer, ForeignKey("users.user_id", ondelete="CASCADE")),
    Column("dedup_key", Text),
    Column("company", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("applied_date", Text, nullable=False),
    Column("last_update", Text, nullable=False),
    Column("url", Text),
    Column("notes", Text),
    Column("contact_email", Text),
)
Index("idx_app_status", applications.c.status)
Index("idx_app_dedup", applications.c.dedup_key)
Index("idx_app_user", applications.c.user_id)

# Usage analytics. One row per HTTP request, written by api.py's middleware.
# Deliberately in the same database rather than a separate metrics store: at
# this scale a table Postgres can aggregate in one query beats operating a
# second system, and it keeps "who used what" joinable against `users`. The
# tradeoff is that a write-heavy analytics table shares the app's connection
# pool — which is exactly why the middleware writes best-effort and never
# blocks or fails a user request (see api.py).
api_events = Table(
    "api_events", metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("occurred_at", Text, nullable=False),
    # Route *template* ("/api/applications/{app_id}"), not the concrete path —
    # otherwise every app_id becomes its own cardinality explosion and you can
    # never aggregate latency per endpoint.
    Column("route", Text, nullable=False),
    Column("method", Text, nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("duration_ms", Integer, nullable=False),
    # Nullable: anonymous browsing of /api/jobs is the common case.
    Column("user_id", Integer),
)
Index("idx_api_events_route_time", api_events.c.route, api_events.c.occurred_at)
Index("idx_api_events_time", api_events.c.occurred_at)

status_events = Table(
    "status_events", metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("app_id", Integer,
           ForeignKey("applications.app_id", ondelete="CASCADE"), nullable=False),
    Column("status", Text, nullable=False),
    Column("note", Text),
    Column("occurred_at", Text, nullable=False),
)


def init_db(engine: Engine | None = None) -> None:
    metadata.create_all(engine or get_engine())


# --- pgvector: kept out of `metadata`/create_all on purpose -----------------
# The `vector` column type only exists on Postgres with the extension
# enabled; defining it as a normal SQLAlchemy Table would break `init_db()`
# on the SQLite backend. Raw DDL + a plain string cast (`CAST(:x AS vector)`)
# sidesteps needing a Postgres-only column type in the portable metadata
# object at all, and needs no extra client-side type adapter.

def pgvector_available(engine: Engine | None = None) -> bool:
    return (engine or get_engine()).dialect.name == "postgresql"


def ensure_job_embeddings(engine: Engine | None = None) -> bool:
    """Enable the pgvector extension + create job_embeddings (+ HNSW index).

    No-op returning False on SQLite — vector search is a Postgres-only
    feature there's no reasonable local-file equivalent for.
    """
    eng = engine or get_engine()
    if not pgvector_available(eng):
        return False
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS job_embeddings ("
            "dedup_key TEXT PRIMARY KEY REFERENCES jobs(dedup_key) ON DELETE CASCADE, "
            f"embedding vector({EMBEDDING_DIMS}) NOT NULL)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_job_embeddings_hnsw ON job_embeddings "
            "USING hnsw (embedding vector_cosine_ops)"
        ))
    return True

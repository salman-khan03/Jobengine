"""Application tracker.

Owns the *post-application* half of the system: what you applied to, where you
applied from, and what's happened since (OA, interview, offer, rejection).
Tracker rows link to `jobs` by dedup_key when the role came from the pipeline,
but also stand alone for roles applied to outside it (manual entry).

One source of truth: this reads/writes the same database (SQLite locally,
Postgres when DATABASE_URL is set — see db.py) that build.py/query.py
produce, so a frontend (Next.js, anything) integrating against JobEngine
talks to one source of truth, not two competing fetch layers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import func, select

from . import db
from .logging_config import get_logger

log = get_logger(__name__)


class Status(str, Enum):
    SAVED = "saved"
    APPLIED = "applied"
    HEARD_BACK = "heard_back"
    OA = "oa"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


# Allowed forward transitions. Not strictly enforced (rejections can land at
# any stage), but used to flag a status change that looks like a typo/regression.
_FORWARD = {
    Status.SAVED: {Status.APPLIED, Status.WITHDRAWN},
    Status.APPLIED: {Status.HEARD_BACK, Status.OA, Status.INTERVIEW, Status.REJECTED, Status.WITHDRAWN},
    Status.HEARD_BACK: {Status.OA, Status.INTERVIEW, Status.REJECTED, Status.WITHDRAWN},
    Status.OA: {Status.INTERVIEW, Status.REJECTED, Status.WITHDRAWN},
    Status.INTERVIEW: {Status.INTERVIEW, Status.OFFER, Status.REJECTED, Status.WITHDRAWN},
    Status.OFFER: {Status.WITHDRAWN},
    Status.REJECTED: set(),
    Status.WITHDRAWN: set(),
}

SOURCES = {"linkedin", "company_site", "simplify", "referral", "email", "other"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Application:
    company: str
    title: str
    source: str
    dedup_key: str | None = None
    status: str = Status.APPLIED.value
    url: str = ""
    notes: str = ""
    contact_email: str = ""
    applied_date: str = field(default_factory=_now)
    app_id: int | None = None


def _ensure_schema() -> None:
    db.init_db()


def add(a: Application, user_id: int | None = None) -> int:
    """user_id is None for CLI-created rows (unowned, CLI-only visibility);
    the HTTP API always passes the authenticated caller's id — see auth.py
    and db.py's note on `applications.user_id` for why these never mix."""
    if a.source not in SOURCES:
        raise ValueError(f"source must be one of {sorted(SOURCES)}, got {a.source!r}")
    _ensure_schema()
    now = _now()
    with db.ENGINE.begin() as conn:
        result = conn.execute(
            db.applications.insert().values(
                user_id=user_id, dedup_key=a.dedup_key, company=a.company, title=a.title,
                source=a.source, status=a.status, applied_date=a.applied_date,
                last_update=now, url=a.url, notes=a.notes,
                contact_email=a.contact_email,
            )
        )
        app_id = result.inserted_primary_key[0]
        conn.execute(
            db.status_events.insert().values(
                app_id=app_id, status=a.status, note="created", occurred_at=now,
            )
        )
    log.info("Added application #%d: %s — %s [%s]", app_id, a.company, a.title, a.status)
    return app_id


def _owned(stmt, app_id: int, user_id: int | None):
    where = [db.applications.c.app_id == app_id]
    if user_id is not None:
        where.append(db.applications.c.user_id == user_id)
    return stmt.where(*where)


def update_status(app_id: int, new_status: str, note: str = "", user_id: int | None = None) -> None:
    if new_status not in {s.value for s in Status}:
        raise ValueError(f"unknown status {new_status!r}")
    _ensure_schema()
    with db.ENGINE.begin() as conn:
        row = conn.execute(
            _owned(select(db.applications.c.status), app_id, user_id)
        ).first()
        if row is None:
            raise KeyError(f"no application with id {app_id}")
        old = Status(row.status)
        new = Status(new_status)
        if new not in _FORWARD.get(old, set()) and new != old:
            log.warning("Unusual transition %s -> %s for app #%d (allowed, but flagged)",
                        old.value, new.value, app_id)
        now = _now()
        conn.execute(
            _owned(db.applications.update(), app_id, user_id)
            .values(status=new_status, last_update=now)
        )
        conn.execute(
            db.status_events.insert().values(
                app_id=app_id, status=new_status, note=note, occurred_at=now,
            )
        )
    log.info("App #%d: %s -> %s", app_id, old.value, new_status)


def edit(app_id: int, user_id: int | None = None, **fields) -> None:
    """Update mutable fields (company/title/url/notes/contact_email/source).
    Does not touch status — use update_status for that, so the event log stays correct.
    """
    allowed = {"company", "title", "url", "notes", "contact_email", "source", "dedup_key"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"cannot edit fields: {bad}")
    if not fields:
        return
    if "source" in fields and fields["source"] not in SOURCES:
        raise ValueError(f"source must be one of {sorted(SOURCES)}")
    _ensure_schema()
    with db.ENGINE.begin() as conn:
        result = conn.execute(
            _owned(db.applications.update(), app_id, user_id)
            .values(**fields, last_update=_now())
        )
        if result.rowcount == 0:
            raise KeyError(f"no application with id {app_id}")


def delete(app_id: int, user_id: int | None = None) -> None:
    _ensure_schema()
    with db.ENGINE.begin() as conn:
        result = conn.execute(
            _owned(db.applications.delete(), app_id, user_id)
        )
        if result.rowcount == 0:
            raise KeyError(f"no application with id {app_id}")
    log.info("Deleted application #%d", app_id)


def list_applications(status: str | None = None, user_id: int | None = None) -> list[dict]:
    _ensure_schema()
    stmt = select(db.applications)
    if user_id is not None:
        stmt = stmt.where(db.applications.c.user_id == user_id)
    if status:
        stmt = stmt.where(db.applications.c.status == status)
    stmt = stmt.order_by(db.applications.c.last_update.desc())
    with db.ENGINE.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def history(app_id: int, user_id: int | None = None) -> list[dict]:
    _ensure_schema()
    # Confirm ownership before returning history, same boundary as the
    # mutating methods — a user shouldn't learn an app exists via 200 vs 404
    # on /history for an id that isn't theirs.
    if user_id is not None:
        with db.ENGINE.connect() as conn:
            owned = conn.execute(
                _owned(select(db.applications.c.app_id), app_id, user_id)
            ).first()
        if owned is None:
            return []
    stmt = (
        select(db.status_events.c.status, db.status_events.c.note,
               db.status_events.c.occurred_at)
        .where(db.status_events.c.app_id == app_id)
        .order_by(db.status_events.c.occurred_at.asc())
    )
    with db.ENGINE.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def summary(user_id: int | None = None) -> dict[str, int]:
    _ensure_schema()
    stmt = select(db.applications.c.status, func.count().label("c"))
    if user_id is not None:
        stmt = stmt.where(db.applications.c.user_id == user_id)
    stmt = stmt.group_by(db.applications.c.status)
    with db.ENGINE.connect() as conn:
        rows = conn.execute(stmt).all()
    return {r.status: r.c for r in rows}


# --- email signal parsing -------------------------------------------------
# Heuristic, not ML — deliberately simple and auditable rather than an opaque
# "AI" black box. Each pattern maps to a status; first match wins, in priority
# order (offer/rejection are the most decisive signals).
_SIGNAL_PATTERNS: list[tuple[str, re.Pattern]] = [
    (Status.OFFER.value, re.compile(
        r"\b(pleased to offer|extend(?:ing)? an offer|offer letter|welcome to the team)\b", re.I)),
    (Status.REJECTED.value, re.compile(
        r"\b(not (?:be )?moving forward|decided not to proceed|other candidates|"
        r"unable to offer|regret to inform|not a (?:fit|match) at this time)\b", re.I)),
    (Status.INTERVIEW.value, re.compile(
        r"\b(schedule (?:an|your) interview|interview (?:invitation|request)|"
        r"phone screen|onsite|virtual interview|meet with (?:the|our) team)\b", re.I)),
    (Status.OA.value, re.compile(
        r"\b(online assessment|coding (?:challenge|assessment)|hackerrank|"
        r"codesignal|take-?home (?:test|assignment))\b", re.I)),
    (Status.HEARD_BACK.value, re.compile(
        r"\b(thank you for (?:your interest|applying)|application received|"
        r"reviewing your application)\b", re.I)),
]


def parse_email_signal(text: str) -> dict:
    """Classify a pasted email by which status it most likely signals.

    Returns {"status": str|None, "matched_phrase": str|None, "confidence": float}.
    confidence is a simple heuristic (1.0 = exact pattern hit), not calibrated —
    surfaced honestly rather than dressed up as a model score.
    """
    for status, pattern in _SIGNAL_PATTERNS:
        m = pattern.search(text)
        if m:
            return {"status": status, "matched_phrase": m.group(0), "confidence": 1.0}
    return {"status": None, "matched_phrase": None, "confidence": 0.0}

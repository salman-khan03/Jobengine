"""Persistence for profiles, decisions and outcomes.

Tables are registered on JobEngine's existing `db.metadata` rather than a
second MetaData object, so `jobengine.db.init_db()` still creates the whole
schema in one call and the portability work already done there (SQLite local,
Postgres deployed) applies unchanged. The cost is that importing this module
has the side effect of extending the schema; that is stated here loudly
because a surprising import-time side effect is worse than an explicit one.

The reason decisions are stored at all: without a record of what the system
predicted *at the time*, outcome data cannot evaluate anything. Re-scoring a
job six months later uses today's weights, today's resume and today's
taxonomy, which would make the ranker look like whatever it currently is
rather than what it was when the user acted on it. `rr_decisions` is an
append-friendly audit log of predictions, and `payload` keeps the full cited
breakdown so an old decision can be re-displayed exactly as the user saw it.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import (
    Column, Float, ForeignKey, Index, Integer, Table, Text, delete, func,
    insert, select, update,
)

from jobengine import db
from jobengine.logging_config import get_logger

from .models import CandidateProfile, Decision

log = get_logger(__name__)

rr_profiles = Table(
    "rr_profiles", db.metadata,
    Column("profile_id", Integer, primary_key=True, autoincrement=True),
    # One profile per user. Nullable for the same reason applications.user_id
    # is: the CLI is a trusted single-user surface with no login.
    Column("user_id", Integer, ForeignKey("users.user_id", ondelete="CASCADE")),
    Column("name", Text),
    Column("location", Text),
    Column("work_authorization", Text),
    # Integer rather than Boolean: SQLite has no native boolean and the
    # tri-state (yes / no / not told us) must survive the round trip, so NULL
    # is meaningful here and must not be coerced to False on read.
    Column("needs_sponsorship", Integer),
    Column("graduation", Text),
    Column("degree_level", Text),
    Column("open_to_relocate", Integer),
    Column("us_citizen", Integer),
    Column("security_clearance", Integer),
    Column("seniority", Text),
    Column("resume_json", Text),
    Column("updated_at", Text),
)
Index("idx_rr_profiles_user", rr_profiles.c.user_id, unique=True)

rr_decisions = Table(
    "rr_decisions", db.metadata,
    Column("decision_id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.user_id", ondelete="CASCADE")),
    Column("job_key", Text, nullable=False),
    Column("title", Text),
    Column("company", Text),
    Column("verdict", Text, nullable=False),
    Column("score", Float, nullable=False),
    Column("confidence", Float),
    # Denormalized from `payload` on purpose: these are what the evaluation
    # query aggregates over thousands of rows, and pulling them out of JSON in
    # SQL is both slower and backend-specific (json_extract vs ->>).
    Column("required_coverage", Float),
    Column("semantic_similarity", Float),
    Column("risk_penalty", Float),
    Column("explanation_source", Text),
    # The exact weights/threshold set that produced this row. Without it, a
    # later evaluation silently mixes predictions from two different rankers
    # and attributes the blend to neither.
    Column("model_version", Text),
    Column("payload", Text),
    Column("created_at", Text, nullable=False),
)
Index("idx_rr_decisions_user_job", rr_decisions.c.user_id, rr_decisions.c.job_key)
Index("idx_rr_decisions_created", rr_decisions.c.created_at)

# --- decision / application / feedback / analytics loop ---------------------
#
# These four tables exist to keep concepts the rest of the product must never
# collapse: `rr_decisions` above is RoleRadar's *recommendation* (confusingly
# named `Decision` at the dataclass level, predating this module -- renaming
# it would ripple through decision.py/ranking.py/explain.py/tests for no
# behavioural gain, so it is called out here instead). `job_decisions` is the
# *user's* choice. `rr_applications` is whether they actually applied.
# `rr_application_events` is the immutable history of what happened after.
# `recommendation_feedback` is a separate signal again: whether the
# recommendation itself was useful, independent of what the user did with it.
# Conflating any two of these is exactly the bug this schema exists to
# prevent -- e.g. overwriting a recommendation with the user's outcome would
# make it impossible to later ask "was the *prediction* any good?".

job_decisions = Table(
    "job_decisions", db.metadata,
    Column("job_decision_id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.user_id", ondelete="CASCADE"),
           nullable=False),
    Column("job_key", Text, nullable=False),
    # The recommendation this decision was made against, if RoleRadar had
    # scored the job yet. Nullable + SET NULL for the same reason
    # rr_outcomes.decision_id is: a user can decide on a job found elsewhere,
    # and that row must survive the recommendation being re-scored or purged.
    Column("recommendation_id", Integer,
           ForeignKey("rr_decisions.decision_id", ondelete="SET NULL")),
    Column("decision", Text, nullable=False),  # apply | save | skip | defer
    Column("reason", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)
# One active decision per job per user: a second APPLY/SAVE/SKIP/DEFER on the
# same job is an edit, not a new fact, which is what PATCH is for. This is
# also the idempotency mechanism for POST -- a retried request upserts onto
# the same row instead of creating a duplicate.
Index("idx_job_decisions_user_job", job_decisions.c.user_id,
      job_decisions.c.job_key, unique=True)

VALID_DECISIONS = ("apply", "save", "skip", "defer")

rr_applications = Table(
    "rr_applications", db.metadata,
    Column("application_id", Integer, primary_key=True, autoincrement=True),
    # Nullable, like rr_decisions.user_id and jobengine.db.applications.user_id:
    # the CLI (`roleradar outcome add`) is a trusted single-user surface with
    # no login, and NULL keeps its rows distinct from -- and invisible to --
    # the multi-user HTTP API, which always writes a real user_id.
    Column("user_id", Integer, ForeignKey("users.user_id", ondelete="CASCADE")),
    # Nullable: the legacy `record_outcome` path (CLI `roleradar outcome add`,
    # and any job logged without ever going through a decision) auto-creates
    # an application with no job_decision_id, exactly as the FK it replaces
    # (rr_outcomes.decision_id) was nullable for the same reason. The new
    # explicit POST /applications path (`create_application`) always requires
    # a real APPLY decision and populates this.
    Column("job_decision_id", Integer,
           ForeignKey("job_decisions.job_decision_id", ondelete="SET NULL")),
    Column("job_key", Text, nullable=False),
    # Denormalized from job_decisions at creation time on purpose: a decision
    # can later be edited (PATCH) or its linked recommendation re-scored, and
    # an application must keep pointing at the prediction that was live when
    # the candidate actually applied, not whatever it is today.
    Column("recommendation_id", Integer,
           ForeignKey("rr_decisions.decision_id", ondelete="SET NULL")),
    Column("source", Text),
    Column("application_url", Text),
    Column("current_stage", Text, nullable=False),
    # NULL until the first "applied" event lands -- an application created
    # from an APPLY decision starts in "planned" and may never be submitted.
    Column("applied_at", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)
Index("idx_rr_applications_user_job", rr_applications.c.user_id,
      rr_applications.c.job_key, unique=True)
Index("idx_rr_applications_decision", rr_applications.c.job_decision_id, unique=True)

rr_application_events = Table(
    "rr_application_events", db.metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("application_id", Integer,
           ForeignKey("rr_applications.application_id", ondelete="CASCADE"),
           nullable=False),
    Column("stage", Text, nullable=False),
    Column("note", Text),
    # Server-stamped only -- no caller-supplied override. An immutable log a
    # client can backdate is not actually an audit trail.
    Column("occurred_at", Text, nullable=False),
)
Index("idx_rr_application_events_app", rr_application_events.c.application_id,
      rr_application_events.c.occurred_at)

# Ordered pipeline; terminal stages are a dead end (see `advance_application`).
# "planned" is new (an APPLY decision converted into a tracked application
# before it is actually submitted); the rest matches outcomes.FUNNEL/TERMINAL
# verbatim on purpose -- those are the evaluation-metric vocabulary and this
# is the state machine, kept as separate constants so a future metric change
# can never silently alter what transitions are legal, but there is no reason
# for a "technical screen" to have two different names in one codebase.
APPLICATION_STAGES: tuple[str, ...] = (
    "planned", "applied", "oa", "phone_screen", "interview", "onsite", "offer",
)
TERMINAL_STAGES: tuple[str, ...] = ("rejected", "ghosted", "withdrawn", "offer")
ALL_STAGES = set(APPLICATION_STAGES) | set(TERMINAL_STAGES)


class InvalidTransition(ValueError):
    """A stage transition that the state machine will not allow."""


recommendation_feedback = Table(
    "recommendation_feedback", db.metadata,
    Column("feedback_id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.user_id", ondelete="CASCADE"),
           nullable=False),
    Column("recommendation_id", Integer,
           ForeignKey("rr_decisions.decision_id", ondelete="CASCADE"),
           nullable=False),
    Column("relevant", Integer, nullable=False),
    Column("reason", Text, nullable=False),
    Column("comments", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)
# "one active feedback record per user per recommendation" -- POST upserts.
Index("idx_recommendation_feedback_user_rec", recommendation_feedback.c.user_id,
      recommendation_feedback.c.recommendation_id, unique=True)

FEEDBACK_REASONS = (
    "good_match", "wrong_skills", "too_senior", "too_junior",
    "location_mismatch", "work_authorization", "bad_explanation",
    "compensation", "not_interested", "other",
)

rr_analytics_events = Table(
    "rr_analytics_events", db.metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    # No FK, matching jobengine.db.api_events: analytics writes must never be
    # the reason a product action fails, and a hard FK is one more way for a
    # best-effort insert to raise.
    Column("user_id", Integer),
    Column("event_type", Text, nullable=False),
    Column("job_key", Text),
    Column("recommendation_id", Integer),
    Column("application_id", Integer),
    Column("event_metadata", Text),
    Column("occurred_at", Text, nullable=False),
)
Index("idx_rr_analytics_type_time", rr_analytics_events.c.event_type,
      rr_analytics_events.c.occurred_at)
Index("idx_rr_analytics_user_time", rr_analytics_events.c.user_id,
      rr_analytics_events.c.occurred_at)

def init() -> None:
    """Create every table, RoleRadar's and JobEngine's."""
    db.init_db()


# --- profiles ---------------------------------------------------------------

_PROFILE_BOOLS = ("needs_sponsorship", "open_to_relocate", "us_citizen",
                  "security_clearance")


def _to_row(profile: CandidateProfile, resume: dict | None, now: str) -> dict[str, Any]:
    row = profile.as_dict()
    for key in _PROFILE_BOOLS:
        val = row.get(key)
        row[key] = None if val is None else int(bool(val))
    row["resume_json"] = json.dumps(resume) if resume is not None else None
    row["updated_at"] = now
    return row


def _from_row(row: dict[str, Any]) -> CandidateProfile:
    fields = set(CandidateProfile.__dataclass_fields__)
    data = {k: v for k, v in row.items() if k in fields}
    for key in _PROFILE_BOOLS:
        if key in data:
            data[key] = None if data[key] is None else bool(data[key])
    # security_clearance/open_to_relocate are non-optional on the dataclass;
    # a NULL from an older row must land on the declared default, not None.
    if data.get("security_clearance") is None:
        data.pop("security_clearance", None)
    if data.get("open_to_relocate") is None:
        data.pop("open_to_relocate", None)
    return CandidateProfile(**data)


def save_profile(profile: CandidateProfile, user_id: int | None = None,
                 resume: dict | None = None, now: str = "") -> int:
    """Upsert the single profile for a user; returns its id.

    Hand-rolled select-then-insert/update rather than a dialect-specific
    upsert, because the same code must run on SQLite and Postgres. The race
    window is irrelevant here: a user editing their own profile twice in the
    same millisecond is not a scenario worth a second codepath.
    """
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = _to_row(profile, resume, now)
    with db.get_engine().begin() as conn:
        existing = conn.execute(
            select(rr_profiles.c.profile_id).where(rr_profiles.c.user_id == user_id)
        ).first()
        if existing:
            conn.execute(update(rr_profiles)
                         .where(rr_profiles.c.profile_id == existing[0])
                         .values(**row))
            return int(existing[0])
        result = conn.execute(insert(rr_profiles).values(user_id=user_id, **row))
        # A single-row INSERT on a table with an autoincrement PK always
        # populates this; the Optional is for executemany, which we never use
        # on this path.
        assert result.inserted_primary_key is not None
        return int(result.inserted_primary_key[0])


def load_profile(user_id: int | None = None) -> tuple[CandidateProfile, dict] | None:
    """(profile, resume) for a user, or None if they have not saved one."""
    with db.get_engine().connect() as conn:
        row = conn.execute(
            select(rr_profiles).where(rr_profiles.c.user_id == user_id)
        ).first()
    if row is None:
        return None
    data = dict(row._mapping)
    resume = json.loads(data["resume_json"]) if data.get("resume_json") else {}
    return _from_row(data), resume


# --- decisions --------------------------------------------------------------

def model_version() -> str:
    """Identifies the scoring configuration that produced a decision."""
    from . import ranking
    weights = ",".join(f"{k}={v}" for k, v in sorted(ranking.WEIGHTS.items()))
    return f"v2|{weights}|apply>={ranking.APPLY_THRESHOLD}"


def save_decision(decision: Decision, user_id: int | None = None,
                  evidence: dict | None = None) -> int:
    payload = decision.as_dict()
    if evidence is not None:
        payload["evidence"] = evidence
    with db.get_engine().begin() as conn:
        result = conn.execute(insert(rr_decisions).values(
            user_id=user_id,
            job_key=decision.job_key,
            title=decision.title,
            company=decision.company,
            verdict=decision.verdict,
            score=decision.score,
            confidence=decision.confidence,
            required_coverage=decision.breakdown.required_coverage,
            semantic_similarity=decision.breakdown.semantic_similarity,
            risk_penalty=decision.breakdown.risk_penalty,
            explanation_source=decision.explanation_source,
            model_version=model_version(),
            payload=json.dumps(payload),
            created_at=decision.generated_at,
        ))
        assert result.inserted_primary_key is not None
        return int(result.inserted_primary_key[0])


def save_decisions(decisions: Iterable[Decision], user_id: int | None = None) -> int:
    """Bulk-persist a ranked batch in one transaction."""
    rows = []
    for d in decisions:
        rows.append({
            "user_id": user_id, "job_key": d.job_key, "title": d.title,
            "company": d.company, "verdict": d.verdict, "score": d.score,
            "confidence": d.confidence,
            "required_coverage": d.breakdown.required_coverage,
            "semantic_similarity": d.breakdown.semantic_similarity,
            "risk_penalty": d.breakdown.risk_penalty,
            "explanation_source": d.explanation_source,
            "model_version": model_version(),
            "payload": json.dumps(d.as_dict()),
            "created_at": d.generated_at,
        })
    if not rows:
        return 0
    with db.get_engine().begin() as conn:
        conn.execute(insert(rr_decisions), rows)
    return len(rows)


def latest_decision(job_key: str, user_id: int | None = None) -> dict | None:
    with db.get_engine().connect() as conn:
        row = conn.execute(
            select(rr_decisions)
            .where(rr_decisions.c.job_key == job_key,
                   rr_decisions.c.user_id == user_id)
            .order_by(rr_decisions.c.decision_id.desc()).limit(1)
        ).first()
    return dict(row._mapping) if row else None


def list_decisions(user_id: int | None = None, verdict: str | None = None,
                   limit: int = 50) -> list[dict]:
    stmt = select(rr_decisions).where(rr_decisions.c.user_id == user_id)
    if verdict:
        stmt = stmt.where(rr_decisions.c.verdict == verdict)
    stmt = stmt.order_by(rr_decisions.c.score.desc()).limit(limit)
    with db.get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


# --- job decisions -----------------------------------------------------------

def save_job_decision(job_key: str, decision: str, user_id: int,
                      reason: str = "", recommendation_id: int | None = None,
                      now: str = "") -> dict:
    """Upsert the user's APPLY/SAVE/SKIP/DEFER choice for one job.

    Idempotent by (user_id, job_key): a retried POST updates the same row
    instead of creating a duplicate decision, and an explicit change of mind
    (SAVE -> APPLY) is the same codepath as PATCH /decisions/{id} -- both are
    "the user's current decision on this job changed," which is one fact with
    one row, not an append-only log. (Compare `rr_application_events`, which
    *is* append-only, because what actually happened after the decision must
    never be edited away.)
    """
    if decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}")
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if recommendation_id is None:
        recommendation_id = _latest_recommendation_id(user_id, job_key)
    with db.get_engine().begin() as conn:
        existing = conn.execute(
            select(job_decisions).where(job_decisions.c.user_id == user_id,
                                        job_decisions.c.job_key == job_key)
        ).mappings().first()
        # `changed` distinguishes a real state transition from an identical
        # retry, so the API layer can skip emitting a product-analytics event
        # for a repost -- otherwise a client retrying a flaky POST would
        # inflate recommendation_accepted/rejected counts for one real action.
        if existing:
            changed = (existing["decision"] != decision
                      or (existing["reason"] or "") != reason)
            conn.execute(update(job_decisions)
                         .where(job_decisions.c.job_decision_id == existing["job_decision_id"])
                         .values(decision=decision, reason=reason or None,
                                # A later decision on an already-scored job may
                                # attach the recommendation it was missing; an
                                # already-linked one is never overwritten, so
                                # editing SAVE -> APPLY cannot quietly re-point
                                # the decision at a newer, different scoring run.
                                recommendation_id=existing["recommendation_id"]
                                or recommendation_id,
                                updated_at=now))
            row_id = existing["job_decision_id"]
        else:
            changed = True
            result = conn.execute(insert(job_decisions).values(
                user_id=user_id, job_key=job_key, decision=decision,
                reason=reason or None, recommendation_id=recommendation_id,
                created_at=now, updated_at=now))
            assert result.inserted_primary_key is not None
            row_id = int(result.inserted_primary_key[0])
        row = conn.execute(select(job_decisions)
                           .where(job_decisions.c.job_decision_id == row_id)
                           ).mappings().first()
        assert row is not None
        return {**dict(row), "changed": changed}


def update_job_decision(job_decision_id: int, user_id: int,
                        decision: str | None = None,
                        reason: str | None = None, now: str = "") -> dict | None:
    """PATCH a decision by id. Returns None if it does not exist or belongs
    to a different user -- callers turn that into a 404, never a 403, so an
    id's mere existence is not leaked to a non-owner."""
    if decision is not None and decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}")
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.get_engine().begin() as conn:
        existing = conn.execute(
            select(job_decisions)
            .where(job_decisions.c.job_decision_id == job_decision_id,
                   job_decisions.c.user_id == user_id)
        ).mappings().first()
        if existing is None:
            return None
        values: dict[str, Any] = {"updated_at": now}
        if decision is not None:
            values["decision"] = decision
        if reason is not None:
            values["reason"] = reason
        # Same `changed` contract as save_job_decision: PATCH is the other
        # path to an APPLY/SKIP decision (SAVE -> APPLY without going back
        # through POST), and it must feed recommendation_accepted/rejected
        # analytics too, or a user who only ever edits via PATCH is invisible
        # to that metric entirely.
        changed = ((decision is not None and decision != existing["decision"])
                  or (reason is not None and reason != (existing["reason"] or "")))
        conn.execute(update(job_decisions)
                     .where(job_decisions.c.job_decision_id == job_decision_id)
                     .values(**values))
        row = conn.execute(select(job_decisions)
                           .where(job_decisions.c.job_decision_id == job_decision_id)
                           ).mappings().first()
        return {**dict(row), "changed": changed} if row else None


def get_job_decision(job_decision_id: int, user_id: int) -> dict | None:
    with db.get_engine().connect() as conn:
        row = conn.execute(
            select(job_decisions)
            .where(job_decisions.c.job_decision_id == job_decision_id,
                   job_decisions.c.user_id == user_id)
        ).mappings().first()
    return dict(row) if row else None


def _latest_recommendation_id(user_id: int, job_key: str) -> int | None:
    with db.get_engine().connect() as conn:
        row = conn.execute(
            select(rr_decisions.c.decision_id)
            .where(rr_decisions.c.user_id == user_id, rr_decisions.c.job_key == job_key)
            .order_by(rr_decisions.c.decision_id.desc()).limit(1)
        ).first()
    return int(row[0]) if row else None


# --- applications and immutable events ---------------------------------------

def create_application(job_decision_id: int, user_id: int,
                       source: str = "", application_url: str = "",
                       now: str = "") -> dict:
    """Convert an APPLY decision into a tracked application.

    Idempotent by (user_id, job_key): retrying this call (network retry,
    double-click) returns the existing application rather than erroring or
    duplicating it. The first event -- "planned" -- is written in the same
    transaction as the row itself, so an application can never exist with a
    current_stage that has no corresponding event to justify it.
    """
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.get_engine().begin() as conn:
        jd = conn.execute(
            select(job_decisions)
            .where(job_decisions.c.job_decision_id == job_decision_id,
                   job_decisions.c.user_id == user_id)
        ).mappings().first()
        if jd is None:
            raise LookupError("no such decision")
        if jd["decision"] != "apply":
            raise InvalidTransition(
                "an application can only be created from an APPLY decision")

        existing = conn.execute(
            select(rr_applications)
            .where(rr_applications.c.user_id == user_id,
                   rr_applications.c.job_key == jd["job_key"])
        ).mappings().first()
        # `created` lets the API layer skip re-emitting application_created
        # analytics for a retried POST that resolved to the same row.
        if existing:
            return {**dict(existing), "created": False}

        result = conn.execute(insert(rr_applications).values(
            user_id=user_id, job_decision_id=job_decision_id,
            job_key=jd["job_key"], recommendation_id=jd["recommendation_id"],
            source=source or None, application_url=application_url or None,
            current_stage="planned", applied_at=None,
            created_at=now, updated_at=now))
        assert result.inserted_primary_key is not None
        app_id = int(result.inserted_primary_key[0])
        conn.execute(insert(rr_application_events).values(
            application_id=app_id, stage="planned", note=None, occurred_at=now))
        row = conn.execute(select(rr_applications)
                           .where(rr_applications.c.application_id == app_id)
                           ).mappings().first()
        assert row is not None
        return {**dict(row), "created": True}


def get_application(application_id: int, user_id: int) -> dict | None:
    with db.get_engine().connect() as conn:
        row = conn.execute(
            select(rr_applications)
            .where(rr_applications.c.application_id == application_id,
                   rr_applications.c.user_id == user_id)
        ).mappings().first()
    return dict(row) if row else None


def list_applications(user_id: int, status: str | None = None) -> list[dict]:
    stmt = select(rr_applications).where(rr_applications.c.user_id == user_id)
    if status:
        stmt = stmt.where(rr_applications.c.current_stage == status)
    stmt = stmt.order_by(rr_applications.c.updated_at.desc())
    with db.get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def application_history(application_id: int, user_id: int) -> list[dict] | None:
    """Every immutable event for one application, oldest first. None if the
    application does not exist or is not owned by this user."""
    with db.get_engine().connect() as conn:
        owned = conn.execute(
            select(rr_applications.c.application_id)
            .where(rr_applications.c.application_id == application_id,
                   rr_applications.c.user_id == user_id)).first()
        if owned is None:
            return None
        rows = conn.execute(
            select(rr_application_events)
            .where(rr_application_events.c.application_id == application_id)
            .order_by(rr_application_events.c.event_id)
        )
        return [dict(r._mapping) for r in rows]


def advance_application(application_id: int, user_id: int, stage: str,
                        note: str = "", now: str = "") -> dict:
    """Append an immutable event and move current_stage forward.

    Two integrity rules, enforced here rather than trusted to callers:

    1. Once an application reaches a terminal stage (rejected/withdrawn/
       ghosted/offer) it is a dead end -- appending an event past that point
       would let a UI bug or a stale retry resurrect a closed application.
    2. Re-posting the stage the application is already on is a no-op, not a
       new history entry -- a retried request must not fabricate a second
       "moved to onsite" event at a different timestamp.

    3. "planned" is a create-time-only bootstrap stage (see
       `create_application`) -- it is never a legal target here, even from
       itself via rule 2's no-op path being skipped. Allowing it back in
       would let a stale client request erase real progress from
       current_stage while the (correct) event history stayed append-only
       underneath it, so the funnel and the history would disagree.

    Returns the latest event row plus a `changed` flag distinguishing a real
    transition from an idempotent repost, so the API layer can skip emitting
    a duplicate product-analytics event for a retried request.
    """
    if stage not in ALL_STAGES:
        raise ValueError(f"stage must be one of {sorted(ALL_STAGES)}")
    if stage == "planned":
        raise InvalidTransition("\"planned\" is set automatically when an "
                                "application is created and cannot be re-entered")
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.get_engine().begin() as conn:
        app = conn.execute(
            select(rr_applications)
            .where(rr_applications.c.application_id == application_id,
                   rr_applications.c.user_id == user_id)
            .with_for_update()
        ).mappings().first()
        if app is None:
            raise LookupError("no such application")
        if stage == app["current_stage"]:
            row = conn.execute(
                select(rr_application_events)
                .where(rr_application_events.c.application_id == application_id)
                .order_by(rr_application_events.c.event_id.desc()).limit(1)
            ).mappings().first()
            return {**dict(row), "changed": False} if row else {"changed": False}
        if app["current_stage"] in TERMINAL_STAGES:
            raise InvalidTransition(
                f"application is already {app['current_stage']} and cannot be "
                "moved further")

        conn.execute(insert(rr_application_events).values(
            application_id=application_id, stage=stage, note=note or None,
            occurred_at=now))
        values: dict[str, Any] = {"current_stage": stage, "updated_at": now}
        if stage == "applied" and app["applied_at"] is None:
            values["applied_at"] = now
        conn.execute(update(rr_applications)
                     .where(rr_applications.c.application_id == application_id)
                     .values(**values))
        row = conn.execute(
            select(rr_application_events)
            .where(rr_application_events.c.application_id == application_id)
            .order_by(rr_application_events.c.event_id.desc()).limit(1)
        ).mappings().first()
        assert row is not None
        return {**dict(row), "changed": True}


# --- legacy outcome logging ---------------------------------------------------
#
# `roleradar outcome add` and the original /api/v2/outcomes route predate the
# applications/job_decisions split and let a user log a stage for any job_key
# directly, with no APPLY decision required first. That convenience is kept:
# `record_outcome` now auto-vivifies an `rr_applications` row (job_decision_id
# left NULL, same meaning NULL carried on the table it replaces) instead of
# writing to the flat `rr_outcomes` log that used to back it.

def record_outcome(job_key: str, stage: str, user_id: int | None = None,
                   note: str = "", occurred_at: str = "") -> int:
    """Pin the prediction at first activity; later rescoring cannot rewrite it.
    Returns the application_id (an outcome IS an application event now)."""
    if stage not in ALL_STAGES:
        raise ValueError("invalid application outcome stage")
    from datetime import datetime, timezone
    occurred_at = occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.get_engine().begin() as conn:
        # Serialize this user's first-event lookup on PostgreSQL. Otherwise two
        # simultaneous first events could pin different predictions.
        if user_id is not None:
            conn.execute(select(db.users.c.user_id)
                         .where(db.users.c.user_id == user_id).with_for_update())
        existing = conn.execute(
            select(rr_applications)
            .where(rr_applications.c.user_id == user_id,
                   rr_applications.c.job_key == job_key)
        ).mappings().first()
        if existing is None:
            prior = conn.execute(select(rr_decisions.c.decision_id).where(
                rr_decisions.c.user_id == user_id, rr_decisions.c.job_key == job_key,
                rr_decisions.c.created_at <= occurred_at)
                .order_by(rr_decisions.c.decision_id.desc()).limit(1)).first()
            recommendation_id = prior[0] if prior else None
            result = conn.execute(insert(rr_applications).values(
                user_id=user_id, job_decision_id=None, job_key=job_key,
                recommendation_id=recommendation_id, current_stage=stage,
                applied_at=occurred_at if stage == "applied" else None,
                created_at=occurred_at, updated_at=occurred_at))
            assert result.inserted_primary_key is not None
            app_id = int(result.inserted_primary_key[0])
        else:
            app_id = existing["application_id"]
            values: dict[str, Any] = {"current_stage": stage, "updated_at": occurred_at}
            if stage == "applied" and existing["applied_at"] is None:
                values["applied_at"] = occurred_at
            conn.execute(update(rr_applications)
                         .where(rr_applications.c.application_id == app_id)
                         .values(**values))
        conn.execute(insert(rr_application_events).values(
            application_id=app_id, stage=stage, note=note or None,
            occurred_at=occurred_at))
        return app_id


def delete_outcomes(job_key: str, user_id: int | None = None) -> int:
    """Remove an application (and its events, via ON DELETE CASCADE) by
    job_key. Kept for CLI/test symmetry with the old rr_outcomes helper."""
    with db.get_engine().begin() as conn:
        res = conn.execute(delete(rr_applications).where(
            rr_applications.c.job_key == job_key, rr_applications.c.user_id == user_id))
        return int(res.rowcount or 0)


def scored_outcomes(user_id: int | None = None) -> list[tuple[float, str]]:
    """(predicted score, furthest stage) per job -- the evaluation input.

    One row per job, not per event: an application with five logged events is
    one prediction the ranker made, and counting it five times would let a
    chatty user's single lucky application dominate every metric.
    """
    from .outcomes import furthest_stage, is_positive

    stmt = (select(rr_applications.c.job_key, rr_application_events.c.stage,
                   rr_decisions.c.score)
            .select_from(rr_applications
                .join(rr_application_events,
                      rr_application_events.c.application_id
                      == rr_applications.c.application_id)
                .outerjoin(
                    rr_decisions,
                    (rr_applications.c.recommendation_id == rr_decisions.c.decision_id)
                    & rr_decisions.c.user_id.is_not_distinct_from(rr_applications.c.user_id)))
            .where(rr_applications.c.user_id == user_id)
            .order_by(rr_application_events.c.event_id))
    by_job: dict[str, tuple[float | None, list[str]]] = {}
    with db.get_engine().connect() as conn:
        for job_key, stage, score in conn.execute(stmt):
            _, stages = by_job.setdefault(job_key, (
                float(score) if score is not None else None, []))
            stages.append(stage)
    # An unanswered application is censored, not a negative training label.
    # Withdrawal before any progress is a candidate choice, not rejection.
    return [(score, furthest_stage(stages)) for score, stages in by_job.values()
            if score is not None and (is_positive(furthest_stage(stages))
                                      or "rejected" in stages or "ghosted" in stages)]


def funnel_counts(user_id: int | None = None) -> dict[str, int]:
    """Current stage per distinct job. Evaluation separately uses deepest
    progress across the whole event history, not the current one."""
    stmt = (select(rr_applications.c.current_stage)
            .where(rr_applications.c.user_id == user_id))
    counts: dict[str, int] = {}
    with db.get_engine().connect() as conn:
        for (stage,) in conn.execute(stmt):
            counts[stage] = counts.get(stage, 0) + 1
    return counts


# --- recommendation feedback ---------------------------------------------------

def save_feedback(recommendation_id: int, user_id: int, relevant: bool,
                  reason: str, comments: str = "", now: str = "") -> dict:
    """Upsert the one active feedback record for (user, recommendation)."""
    if reason not in FEEDBACK_REASONS:
        raise ValueError(f"reason must be one of {FEEDBACK_REASONS}")
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.get_engine().begin() as conn:
        owns = conn.execute(
            select(rr_decisions.c.decision_id)
            .where(rr_decisions.c.decision_id == recommendation_id,
                   rr_decisions.c.user_id == user_id)).first()
        if owns is None:
            raise LookupError("no such recommendation")
        existing = conn.execute(
            select(recommendation_feedback)
            .where(recommendation_feedback.c.user_id == user_id,
                   recommendation_feedback.c.recommendation_id == recommendation_id)
        ).mappings().first()
        values = {"relevant": int(bool(relevant)), "reason": reason,
                  "comments": comments or None}
        if existing:
            conn.execute(update(recommendation_feedback)
                         .where(recommendation_feedback.c.feedback_id
                                == existing["feedback_id"])
                         .values(updated_at=now, **values))
            fid = existing["feedback_id"]
        else:
            result = conn.execute(insert(recommendation_feedback).values(
                user_id=user_id, recommendation_id=recommendation_id,
                created_at=now, updated_at=now, **values))
            assert result.inserted_primary_key is not None
            fid = int(result.inserted_primary_key[0])
        row = conn.execute(select(recommendation_feedback)
                           .where(recommendation_feedback.c.feedback_id == fid)
                           ).mappings().first()
        assert row is not None
        return dict(row)


# --- analytics ------------------------------------------------------------

def emit_analytics(event_type: str, user_id: int | None = None,
                   job_key: str | None = None, recommendation_id: int | None = None,
                   application_id: int | None = None,
                   metadata: dict | None = None) -> None:
    """Best-effort product-analytics write. Mirrors jobengine.db's `observe`
    HTTP-telemetry pattern: a broken analytics insert must never fail the
    request that triggered it, so every exception is swallowed here rather
    than propagated."""
    from datetime import datetime, timezone
    try:
        with db.get_engine().begin() as conn:
            conn.execute(insert(rr_analytics_events).values(
                user_id=user_id, event_type=event_type, job_key=job_key,
                recommendation_id=recommendation_id, application_id=application_id,
                event_metadata=json.dumps(metadata) if metadata else None,
                occurred_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
    except Exception:
        log.warning("analytics event write failed: %s", event_type, exc_info=True)


def analytics_counts(user_id: int | None = None,
                     since: str | None = None) -> dict[str, int]:
    """Raw counts by event_type -- the building block for funnel endpoints."""
    stmt = select(rr_analytics_events.c.event_type, func.count())
    if user_id is not None:
        stmt = stmt.where(rr_analytics_events.c.user_id == user_id)
    if since:
        stmt = stmt.where(rr_analytics_events.c.occurred_at >= since)
    stmt = stmt.group_by(rr_analytics_events.c.event_type)
    with db.get_engine().connect() as conn:
        return {event_type: count for event_type, count in conn.execute(stmt)}

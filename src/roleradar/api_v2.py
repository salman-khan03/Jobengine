"""RoleRadar HTTP surface, mounted onto JobEngine's FastAPI app at /api/v2.

Versioned under /v2 rather than replacing /api/*: the v1 jobs/applications
endpoints already have a frontend and a Spring Boot consumer, and breaking
them to ship a new feature would be self-inflicted. v2 adds the decision
layer beside them.

Auth model, and the one deliberate exception:

* `/profile`, `/decisions`, `/outcomes`, `/evaluation` require a bearer token
  — they are per-user records and must never leak across accounts.
* `/decide` accepts an **anonymous** request carrying its own resume and job
  description inline. Nothing is stored, nothing is billed to an account, and
  a recruiter or reviewer can exercise the entire evidence-grounded pipeline
  with one curl and no signup. Requiring registration to see the core idea
  work would be the wrong trade for a portfolio product.

Pydantic models are defined here rather than reusing the dataclasses in
`models.py` so the wire format can stay stable while the internal domain
model changes -- see that module's header note.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, TypeAdapter, field_validator
from sqlalchemy import func, select

from jobengine import auth, db
from jobengine.logging_config import get_logger

from . import decision as decision_mod, evidence as ev, outcomes, store, taxonomy
from .models import CandidateProfile

log = get_logger(__name__)
router = APIRouter(prefix="/api/v2", tags=["roleradar"])

_bearer = HTTPBearer(auto_error=False)

# Batch scoring is O(postings); an unbounded `scan` would let one request pin
# a worker for minutes. 500 is comfortably under a second on the measured
# pipeline and still more than a user reads in a sitting.
MAX_SCAN = 500


def _require_user(request: Request,
                  creds: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    """Bearer auth, duplicated from api.py's `current_user` on purpose.

    Importing it would create a cycle: api.py includes this router at import
    time. Twelve lines of duplication beats a lazy-import dance that FastAPI's
    dependency injection cannot introspect.
    """
    if creds is None:
        raise HTTPException(401, "sign in required — missing Authorization: Bearer token")
    try:
        user = auth.decode_token(creds.credentials)
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc))
    request.state.user_id = user.user_id
    return user


# --- wire models ------------------------------------------------------------

class ResumeItem(BaseModel):
    name: str | None = None
    title: str | None = None
    dates: str | None = None
    stack: list[str] | None = None
    bullets: list[str] | None = None


class EducationItem(BaseModel):
    school: str | None = None
    degree: str | None = None
    graduation: str | None = None
    coursework: list[str] | None = None


class ResumeShape(BaseModel):
    projects: list[ResumeItem] | None = None
    experience: list[ResumeItem] | None = None
    training: list[ResumeItem] | None = None
    education: EducationItem | list[EducationItem] | None = None
    skills: dict[str, list[str] | None] | list[str] | None = None


def _validate_resume(resume: dict | None) -> dict | None:
    if resume is not None:
        if len(json.dumps(resume)) > 100_000:
            raise ValueError("resume exceeds 100,000 characters")
        ResumeShape.model_validate(resume)
    return resume


class ProfileIn(BaseModel):
    resume: dict = Field(..., description="resume.json contents")
    needs_sponsorship: bool | None = None
    graduation: str | None = None
    location: str | None = None
    us_citizen: bool | None = None
    open_to_relocate: bool | None = None
    seniority: str | None = None

    _resume_shape = field_validator("resume")(_validate_resume)


class ProfileOut(BaseModel):
    profile: dict
    evidence_units: int
    skills_detected: list[str]


class DecideIn(BaseModel):
    """Either `job_key` (look the posting up) or an inline `job` dict."""

    job_key: str | None = None
    job: dict | None = None
    jd_text: str = Field(default="", max_length=50_000)
    resume: dict | None = None
    profile: dict | None = None
    use_llm: bool = False
    save: bool = False

    _resume_shape = field_validator("resume")(_validate_resume)

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, profile: dict | None) -> dict | None:
        if profile is None:
            return None
        validated = TypeAdapter(CandidateProfile).validate_python(profile).as_dict()
        return {key: validated[key] for key in profile if key in validated}


class RankIn(BaseModel):
    grad: Literal["intern", "newgrad"] | None = None
    company: str | None = None
    title_contains: str | None = None
    tiers: list[str] | None = None
    scan: int = Field(200, ge=1, le=MAX_SCAN)
    limit: int = Field(20, ge=1, le=100)
    save: bool = False


class OutcomeIn(BaseModel):
    job_key: str = Field(min_length=1, max_length=512)
    stage: str
    note: str | None = Field(default=None, max_length=4000)


class JobDecisionIn(BaseModel):
    decision: Literal["apply", "save", "skip", "defer"]
    reason: str = Field(default="", max_length=2000)


class JobDecisionPatch(BaseModel):
    decision: Literal["apply", "save", "skip", "defer"] | None = None
    reason: str | None = Field(default=None, max_length=2000)


class ApplicationIn(BaseModel):
    job_decision_id: int
    source: str = Field(default="", max_length=200)
    application_url: str = Field(default="", max_length=2000)


class ApplicationStageIn(BaseModel):
    stage: str
    note: str = Field(default="", max_length=4000)


class FeedbackIn(BaseModel):
    relevant: bool
    reason: Literal[
        "good_match", "wrong_skills", "too_senior", "too_junior",
        "location_mismatch", "work_authorization", "bad_explanation",
        "compensation", "not_interested", "other",
    ]
    comments: str = Field(default="", max_length=4000)


# --- helpers ----------------------------------------------------------------

def _profile_from_payload(resume: dict, overrides: dict | None) -> CandidateProfile:
    fields = set(CandidateProfile.__dataclass_fields__)
    clean = {k: v for k, v in (overrides or {}).items() if k in fields
             and (v is not None or k in {"needs_sponsorship", "graduation", "us_citizen"})}
    return replace(ev.profile_from_resume(resume), **clean)


def _load_context(user_id: int | None, body_resume: dict | None,
                  body_profile: dict | None):
    """(profile, resume) from the request body, falling back to the saved one.

    Body wins so a caller can score against a resume variant without
    overwriting the profile they have stored.
    """
    if body_resume is not None:
        return _profile_from_payload(body_resume, body_profile), body_resume
    stored = store.load_profile(user_id)
    if stored is None:
        raise HTTPException(
            400, "no saved profile — POST /api/v2/profile first, or include "
                 "`resume` in this request")
    profile, resume = stored
    if body_profile:
        fields = set(CandidateProfile.__dataclass_fields__)
        merged = {**profile.as_dict(),
                  **{k: v for k, v in body_profile.items()
                     if k in fields}}
        profile = CandidateProfile(**merged)
    return profile, resume


def _find_jobs(body: RankIn) -> list[dict]:
    j = db.jobs
    stmt = select(j).where(j.c.active == 1, j.c.is_visible == 1)
    if body.grad:
        stmt = stmt.where(j.c.source_repo == body.grad)
    if body.company:
        stmt = stmt.where(j.c.company_norm.like(f"%{body.company.lower()}%"))
    if body.title_contains:
        stmt = stmt.where(func.lower(j.c.title).like(f"%{body.title_contains.lower()}%"))
    if body.tiers:
        stmt = stmt.where(j.c.sponsor_tier.in_(body.tiers))
    stmt = stmt.order_by(j.c.date_posted.desc()).limit(body.scan)
    with db.get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def _job_by_key(job_key: str) -> dict:
    with db.get_engine().connect() as conn:
        row = conn.execute(
            select(db.jobs).where(db.jobs.c.dedup_key == job_key)).first()
    if row is None:
        raise HTTPException(404, f"no posting with dedup_key {job_key!r}")
    return dict(row._mapping)


# --- routes -----------------------------------------------------------------

@router.post("/profile", response_model=ProfileOut)
def save_profile(body: ProfileIn, user=Depends(_require_user)) -> ProfileOut:
    profile = _profile_from_payload(body.resume,
                                    body.model_dump(exclude={"resume"}, exclude_unset=True))
    store.save_profile(profile, user_id=user.user_id, resume=body.resume)
    units = ev.extract_evidence(body.resume)
    skills = sorted({s for u in units for s in u.skills})
    return ProfileOut(profile=profile.as_dict(), evidence_units=len(units),
                      skills_detected=skills)


@router.get("/profile", response_model=ProfileOut)
def get_profile(user=Depends(_require_user)) -> ProfileOut:
    stored = store.load_profile(user.user_id)
    if stored is None:
        raise HTTPException(404, "no profile saved yet")
    profile, resume = stored
    units = ev.extract_evidence(resume)
    return ProfileOut(profile=profile.as_dict(), evidence_units=len(units),
                      skills_detected=sorted({s for u in units for s in u.skills}))


@router.get("/evidence")
def list_evidence(user=Depends(_require_user)) -> dict[str, Any]:
    """Every citable unit extracted from the stored resume.

    Exposed because citations are only trustworthy if the cited corpus is
    inspectable: a user must be able to see exactly what the scorer can see.
    """
    stored = store.load_profile(user.user_id)
    if stored is None:
        raise HTTPException(404, "no profile saved yet")
    units = ev.extract_evidence(stored[1])
    return {"count": len(units), "units": [u.as_dict() for u in units]}


@router.post("/decide")
def decide(body: DecideIn,
           creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """Score one posting. Anonymous when the request carries its own resume.

    `save` and looking a job up by `job_key` both need an account; an inline
    job + inline resume needs nothing.
    """
    user_id: int | None = None
    if creds is not None:
        try:
            user_id = auth.decode_token(creds.credentials).user_id
        except auth.AuthError as exc:
            raise HTTPException(401, str(exc))

    if body.resume is None and user_id is None:
        raise HTTPException(
            401, "include `resume` in the request body to score anonymously, "
                 "or sign in to use your saved profile")

    if body.save and user_id is None:
        raise HTTPException(401, "sign in to save a decision")

    profile, resume = _load_context(user_id, body.resume, body.profile)

    if body.job is not None:
        job = dict(body.job)
        # Different requisitions with the same company/title must not share
        # outcomes. The description and location distinguish inline postings;
        # rescoring that posting against another resume keeps the identity.
        identity = json.dumps({"job": job, "jd": body.jd_text.strip()}, sort_keys=True)
        job.setdefault("dedup_key", "inline:" + hashlib.sha256(identity.encode()).hexdigest()[:24])
    elif body.job_key:
        job = _job_by_key(body.job_key)
    else:
        raise HTTPException(400, "provide either `job_key` or an inline `job`")

    units = ev.extract_evidence(resume)
    d = decision_mod.decide(job, profile, units, jd_text=body.jd_text,
                            use_llm=body.use_llm)

    payload = d.as_dict()
    # Ship the cited evidence inline. Without it a client would have to make a
    # second call to render the citations, and the citation *is* the feature.
    cited = {u.evidence_id: u.as_dict() for u in units
             if u.evidence_id in set(d.cited_evidence_ids)
             or any(u.evidence_id in c.evidence_ids for c in d.coverages)}
    payload["evidence"] = cited
    if body.save:
        payload["decision_id"] = store.save_decision(d, user_id=user_id, evidence=cited)
    return payload


@router.post("/rank")
def rank(body: RankIn, user=Depends(_require_user)) -> dict:
    """Batch-score the listing set for the signed-in user.

    Never calls an LLM, no matter what: this path can touch 500 postings, and
    the explanations shown here are the deterministic ones. A user who opens
    a specific role gets the model-written version from `/decide`.
    """
    profile, resume = _load_context(user.user_id, None, None)
    jobs = _find_jobs(body)
    if not jobs:
        return {"scanned": 0, "results": [], "counts": {},
                "note": "no postings matched those filters"}
    decisions = decision_mod.decide_many(jobs, resume, profile, use_llm=False,
                                         top_k=body.limit)
    if body.save:
        store.save_decisions(decisions, user_id=user.user_id)
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.verdict] = counts.get(d.verdict, 0) + 1
    return {"scanned": len(jobs), "counts": counts,
            "results": [d.as_dict() for d in decisions]}


@router.get("/decisions")
def list_decisions(verdict: str | None = None, limit: int = 50,
                   user=Depends(_require_user)) -> dict:
    rows = store.list_decisions(user.user_id, verdict=verdict,
                                limit=max(1, min(limit, 200)))
    return {"count": len(rows), "decisions": rows}


@router.post("/outcomes", status_code=201)
def add_outcome(body: OutcomeIn, user=Depends(_require_user)) -> dict:
    """Legacy convenience route: log a stage for a job_key directly, with no
    APPLY decision required first. Kept beside the new /jobs/.../decisions +
    /applications flow for CLI and quick-logging callers; both write to the
    same rr_applications/rr_application_events tables underneath."""
    if body.stage not in store.ALL_STAGES:
        raise HTTPException(400, f"stage must be one of {sorted(store.ALL_STAGES)}")
    app_id = store.record_outcome(body.job_key, body.stage, user_id=user.user_id,
                                  note=body.note or "")
    # Return the actual pinned prediction, never the latest rescore.
    with db.get_engine().connect() as conn:
        row = conn.execute(select(store.rr_decisions).join(
            store.rr_applications,
            store.rr_applications.c.recommendation_id == store.rr_decisions.c.decision_id)
            .where(store.rr_applications.c.application_id == app_id,
                   store.rr_decisions.c.user_id == user.user_id)).mappings().first()
    linked = dict(row) if row else None
    return {"application_id": app_id, "stage": body.stage,
            "linked_prediction": {"score": linked["score"],
                                  "verdict": linked["verdict"],
                                  "created_at": linked["created_at"]} if linked else None}


@router.get("/outcomes/funnel")
def funnel(user=Depends(_require_user)) -> dict:
    counts = store.funnel_counts(user.user_id)
    ordered = [s for s in outcomes.FUNNEL if counts.get(s)]
    ordered += [s for s in outcomes.TERMINAL if s not in outcomes.FUNNEL and counts.get(s)]
    return {"funnel": {s: counts[s] for s in ordered}, "total": sum(counts.values())}


# --- decisions / applications / feedback: the persistent recommendation ->
# decision -> application -> outcome -> feedback loop. Never overwrites the
# recommendation itself (rr_decisions, untouched by anything below).

def _decision_out(row: dict) -> dict:
    # snake_case, like every other field in this API (evidence, applications,
    # decisions list) -- not the camelCase shown in early drafts of this
    # route's spec, which would have made this the one inconsistent corner
    # of an otherwise uniform wire format. Named `job_decision_id`, not
    # `decision_id`: /decide and /decisions already use `decision_id` for the
    # *recommendation*'s id (rr_decisions), and reusing that name here for a
    # different table would recreate, at the wire level, exactly the
    # recommendation/decision conflation this whole feature exists to keep
    # apart.
    return {"job_decision_id": row["job_decision_id"], "job_key": row["job_key"],
            "recommendation_id": row["recommendation_id"],
            "decision": row["decision"], "reason": row["reason"],
            "saved": True}


@router.post("/jobs/{job_key}/decisions", status_code=201)
def save_job_decision(job_key: str, body: JobDecisionIn,
                      user=Depends(_require_user)) -> dict:
    """APPLY/SAVE/SKIP/DEFER for one job. Idempotent: repeating this call
    (retry, double submit) updates the same decision rather than creating a
    second one -- see `store.save_job_decision`."""
    row = store.save_job_decision(job_key, body.decision, user_id=user.user_id,
                                  reason=body.reason)
    if row["changed"]:
        store.emit_analytics(
            "recommendation_accepted" if body.decision == "apply"
            else "recommendation_rejected" if body.decision == "skip"
            else "job_decision_recorded",
            user_id=user.user_id, job_key=job_key,
            recommendation_id=row["recommendation_id"],
            metadata={"decision": body.decision})
    return _decision_out(row)


@router.patch("/decisions/{job_decision_id}")
def patch_job_decision(job_decision_id: int, body: JobDecisionPatch,
                       user=Depends(_require_user)) -> dict:
    try:
        row = store.update_job_decision(job_decision_id, user_id=user.user_id,
                                        decision=body.decision, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "no such decision")
    if row["changed"] and body.decision is not None:
        store.emit_analytics(
            "recommendation_accepted" if body.decision == "apply"
            else "recommendation_rejected" if body.decision == "skip"
            else "job_decision_recorded",
            user_id=user.user_id, job_key=row["job_key"],
            recommendation_id=row["recommendation_id"],
            metadata={"decision": body.decision})
    return _decision_out(row)


@router.post("/applications", status_code=201)
def post_application(body: ApplicationIn, user=Depends(_require_user)) -> dict:
    """Convert an APPLY decision into a tracked application. Idempotent by
    (user, job): a retried request returns the same application."""
    try:
        row = store.create_application(body.job_decision_id, user_id=user.user_id,
                                       source=body.source,
                                       application_url=body.application_url)
    except LookupError:
        raise HTTPException(404, "no such decision")
    except store.InvalidTransition as exc:
        raise HTTPException(400, str(exc))
    created = row.pop("created")
    if created:
        store.emit_analytics("application_created", user_id=user.user_id,
                             job_key=row["job_key"], recommendation_id=row["recommendation_id"],
                             application_id=row["application_id"])
    return row


@router.get("/applications")
def get_applications(status: str | None = None, user=Depends(_require_user)) -> dict:
    rows = store.list_applications(user.user_id, status=status)
    return {"count": len(rows), "applications": rows}


@router.get("/applications/{application_id}")
def get_application(application_id: int, user=Depends(_require_user)) -> dict:
    row = store.get_application(application_id, user_id=user.user_id)
    if row is None:
        raise HTTPException(404, "no such application")
    return row


@router.get("/applications/{application_id}/events")
def get_application_events(application_id: int, user=Depends(_require_user)) -> dict:
    history = store.application_history(application_id, user_id=user.user_id)
    if history is None:
        raise HTTPException(404, "no such application")
    return {"count": len(history), "events": history}


@router.patch("/applications/{application_id}/stage")
def patch_application_stage(application_id: int, body: ApplicationStageIn,
                            user=Depends(_require_user)) -> dict:
    return _advance(application_id, body, user)


@router.post("/applications/{application_id}/events", status_code=201)
def post_application_event(application_id: int, body: ApplicationStageIn,
                           user=Depends(_require_user)) -> dict:
    return _advance(application_id, body, user)


def _advance(application_id: int, body: ApplicationStageIn, user) -> dict:
    try:
        event = store.advance_application(application_id, user_id=user.user_id,
                                          stage=body.stage, note=body.note)
    except store.InvalidTransition as exc:
        # Must be caught before ValueError: InvalidTransition subclasses it,
        # so this branch would otherwise never run and every illegal
        # transition would incorrectly surface as a 400 instead of a 409.
        raise HTTPException(409, str(exc))
    except LookupError:
        raise HTTPException(404, "no such application")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    changed = event.pop("changed")
    if changed:
        store.emit_analytics("application_stage_changed", user_id=user.user_id,
                             application_id=application_id,
                             metadata={"stage": body.stage})
    return event


@router.post("/recommendations/{recommendation_id}/feedback", status_code=201)
def post_feedback(recommendation_id: int, body: FeedbackIn,
                  user=Depends(_require_user)) -> dict:
    try:
        row = store.save_feedback(recommendation_id, user_id=user.user_id,
                                  relevant=body.relevant, reason=body.reason,
                                  comments=body.comments)
    except LookupError:
        raise HTTPException(404, "no such recommendation")
    store.emit_analytics("feedback_submitted", user_id=user.user_id,
                         recommendation_id=recommendation_id,
                         metadata={"relevant": body.relevant, "reason": body.reason})
    return {**row, "relevant": bool(row["relevant"])}


@router.get("/evaluation")
def evaluation(min_sample: int = outcomes.MIN_SAMPLE,
               user=Depends(_require_user)) -> dict:
    """Did the ranking actually predict outcomes? Reported honestly, including
    when the answer is "not enough data" or "no better than random"."""
    report = outcomes.evaluate(store.scored_outcomes(user.user_id),
                               min_sample=max(outcomes.MIN_SAMPLE, min_sample))
    return report.as_dict()


@router.get("/taxonomy")
def get_taxonomy() -> dict:
    """The skill vocabulary and its implication edges — public, and useful for
    client-side autocomplete as well as for auditing what the matcher knows."""
    return {
        "skills": sorted(taxonomy.CANONICAL_SKILLS),
        "aliases": {k: list(v) for k, v in taxonomy.ALIASES.items() if v},
        "implies": {k: list(v) for k, v in taxonomy.IMPLIES.items()},
    }


@router.get("/model")
def model_info() -> dict:
    """The exact weights and thresholds in force.

    Public on purpose. A scoring system users are asked to act on should not
    be a black box, and publishing the weights costs nothing that matters.
    """
    from . import ranking, skills_match

    return {
        "version": store.model_version(),
        "weights": ranking.WEIGHTS,
        "thresholds": {"apply": ranking.APPLY_THRESHOLD,
                       "stretch": ranking.STRETCH_THRESHOLD,
                       "apply_min_required_coverage": ranking.APPLY_MIN_REQUIRED},
        "evidence_scores": {"demonstrated_direct": skills_match._STRONG,
                            "demonstrated_implied": skills_match._IMPLIED,
                            "listed_direct": skills_match._LISTED,
                            "listed_implied": skills_match._LISTED_IMPLIED},
        "max_risk_penalty": 0.30,
        "llm": {"used_for": "explanation only, never the verdict or the score",
                "grounding": "every claim must cite supplied evidence ids; "
                             "claims with uncited numbers are dropped"},
    }

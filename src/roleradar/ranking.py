"""Score composition and the apply/stretch/skip verdict.

Everything here is a linear model with hand-set weights, printed alongside the
result. That is a choice, not a limitation. A learned ranker needs labelled
outcomes, and on day one there are none -- the honest move is to ship a
transparent prior, log the decisions, and let `evaluation.py` measure whether
the ordering actually predicts interviews. Once enough outcomes exist, the
weights here are exactly what a fitted model would replace, and the evaluation
harness is already the thing that would prove the replacement is better.

Bounded influence is the second rule. Semantic similarity is capped at 20% of
the score because the embedding is a hashing-trick vector (jobengine's
`embeddings.py`), not a trained sentence encoder: useful for tie-breaking
between two plausible roles, not trustworthy enough to override the fact that
a candidate has zero evidence of a required skill.
"""
from __future__ import annotations

from typing import Sequence

from jobengine.embeddings import embed

from .constraints import risk_penalty
from .models import (
    CandidateProfile, EvidenceUnit, Gate, JobRequirements, ScoreBreakdown,
    SkillCoverage,
)
from . import skills_match

# Sum to 1.0 before the risk penalty is subtracted. Required coverage carries
# half the score on its own: it is the only term backed by explicit citations.
WEIGHTS: dict[str, float] = {
    "required_coverage": 0.50,
    "preferred_coverage": 0.15,
    "semantic_similarity": 0.20,
    "seniority_fit": 0.15,
}

APPLY_THRESHOLD = 0.70
STRETCH_THRESHOLD = 0.45
# A strong average can hide a fatal hole -- 0.9 on nine requirements and 0.0
# on the tenth still averages well. "apply" therefore also requires that the
# required half of the match is genuinely covered, not just that the blended
# number looks good.
APPLY_MIN_REQUIRED = 0.60

_CANDIDATE_LEVEL = {"student": 0.0, "junior": 1.0, "mid": 2.0,
                    "senior": 3.0, "staff": 4.0}
_JOB_LEVEL = {"intern": 0.0, "new_grad": 0.5, "junior": 1.0, "mid": 2.0,
              "senior": 3.0, "staff": 4.0}

# Reaching up is penalized harder than reaching down, because the failure
# modes are not symmetric: a new grad applying to a staff role is screened
# out, while a senior applying to a mid role is merely overqualified.
_OVER_REACH_COST = 0.35
_UNDER_REACH_COST = 0.15


def seniority_fit(profile: CandidateProfile, job: JobRequirements) -> float:
    """0..1 fit between the candidate's level and the posting's."""
    if job.seniority == "unknown":
        # Neutral-but-uncertain, not neutral-and-fine: an unlabelled posting
        # should not outrank one explicitly targeting this candidate's level.
        return 0.60
    cand = _CANDIDATE_LEVEL.get(profile.seniority, 0.0)
    role = _JOB_LEVEL.get(job.seniority, 1.0)
    diff = role - cand
    cost = (_OVER_REACH_COST if diff > 0 else _UNDER_REACH_COST) * abs(diff)
    return round(max(0.0, 1.0 - cost), 4)


def semantic_similarity(candidate_text: str, job_text: str) -> float:
    """Cosine similarity of two hashing-trick embeddings, clamped to 0..1.

    `embed` returns unit vectors, so the dot product *is* the cosine and no
    normalization pass is needed here. Negative cosines (possible because
    feature hashing uses signed buckets) clamp to 0 -- "less related than
    unrelated" is not a meaningful distinction for ranking.
    """
    if not candidate_text.strip() or not job_text.strip():
        return 0.0
    a, b = embed(candidate_text), embed(job_text)
    return round(max(0.0, sum(x * y for x, y in zip(a, b))), 4)


def job_text(job: JobRequirements) -> str:
    """The posting's own words, for embedding: title plus every extracted ask."""
    parts = [job.title, job.company]
    parts.extend(r.text for r in job.requirements)
    return "\n".join(p for p in parts if p)


def compose(coverages: Sequence[SkillCoverage], gate: Gate,
            profile: CandidateProfile, job: JobRequirements,
            candidate_text: str = "") -> ScoreBreakdown:
    required, preferred = skills_match.aggregate(coverages)
    return ScoreBreakdown(
        required_coverage=required,
        preferred_coverage=preferred,
        semantic_similarity=semantic_similarity(candidate_text, job_text(job)),
        seniority_fit=seniority_fit(profile, job),
        risk_penalty=risk_penalty(gate),
        weights=dict(WEIGHTS),
    )


def score_of(breakdown: ScoreBreakdown) -> float:
    """The weighted sum, minus risk, clamped to 0..1."""
    raw = (WEIGHTS["required_coverage"] * breakdown.required_coverage
           + WEIGHTS["preferred_coverage"] * breakdown.preferred_coverage
           + WEIGHTS["semantic_similarity"] * breakdown.semantic_similarity
           + WEIGHTS["seniority_fit"] * breakdown.seniority_fit)
    return round(max(0.0, min(1.0, raw - breakdown.risk_penalty)), 4)


def verdict_of(score: float, gate: Gate, breakdown: ScoreBreakdown) -> str:
    if not gate.passed:
        return "blocked"
    if score >= APPLY_THRESHOLD and breakdown.required_coverage >= APPLY_MIN_REQUIRED:
        return "apply"
    if score >= STRETCH_THRESHOLD:
        return "stretch"
    return "skip"


def confidence_of(job: JobRequirements, gate: Gate,
                  coverages: Sequence[SkillCoverage]) -> float:
    """How much to trust this decision, 0..1 -- reported, never used to score.

    Confidence and score answer different questions, and collapsing them is a
    classic matcher bug: a listing with no description can still be a genuine
    0.8 match on title alone, but the user deserves to know the system was
    working from three extracted requirements rather than twenty-five.
    """
    n = len(job.requirements)
    # Saturating rather than linear: the 25th requirement adds far less
    # certainty than the 3rd.
    evidence_conf = min(1.0, n / 12.0) ** 0.5 if n else 0.15
    unknowns = sum(1 for v in gate.verdicts if v.status == "unknown")
    penalty = min(0.30, 0.10 * unknowns)
    if job.extractor == "llm":
        evidence_conf = min(1.0, evidence_conf + 0.05)
    cited = sum(1 for c in coverages if c.evidence_ids)
    citation_conf = min(1.0, cited / max(1, len(coverages))) if coverages else 0.3
    return round(max(0.05, min(1.0, 0.65 * evidence_conf + 0.35 * citation_conf - penalty)), 4)


def candidate_text_of(units: Sequence[EvidenceUnit]) -> str:
    return "\n".join(u.text for u in units)

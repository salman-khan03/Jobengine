"""Core domain types.

Frozen dataclasses rather than Pydantic models on purpose: these are the
*internal* vocabulary shared by the extraction, gating, matching and ranking
stages, and they must be hashable/comparable so tests can assert on them
directly. The HTTP boundary (api_v2.py) defines its own Pydantic models and
converts -- keeping wire format and domain model free to change apart.

Every structure that ends up in front of a user carries provenance:
EvidenceUnit.source points at a JSON path inside the candidate's resume,
Requirement.source points at the line of the posting it came from. That is
what lets explain.py refuse to publish an unciteable claim.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# --- candidate side ---------------------------------------------------------

EvidenceKind = Literal["project", "experience", "education", "skill", "training"]


@dataclass(frozen=True)
class EvidenceUnit:
    """One atomic, citable claim the candidate has already made about themself.

    Never synthesized: `text` is a verbatim slice of resume.json. `source` is
    the JSON path it came from, so any UI can deep-link back to the exact
    bullet and a reviewer can audit the chain in one hop.
    """

    evidence_id: str
    kind: EvidenceKind
    label: str
    text: str
    source: str
    skills: tuple[str, ...] = ()
    started: str | None = None
    ended: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "skills": list(self.skills)}


@dataclass(frozen=True)
class CandidateProfile:
    """The facts a hard constraint can be checked against.

    Separate from EvidenceUnit because these are *attributes* of the person
    (work authorization, graduation date), not claims about their work. The
    constraint gate reads only this; the skill matcher reads only evidence.
    """

    name: str = ""
    location: str = ""
    work_authorization: str = "unknown"
    needs_sponsorship: bool | None = None
    graduation: str | None = None
    degree_level: str = "bachelors"
    open_to_relocate: bool = True
    us_citizen: bool | None = None
    security_clearance: bool = False
    seniority: str = "student"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- job side ---------------------------------------------------------------

ConstraintKind = Literal[
    "sponsorship", "work_authorization", "citizenship", "clearance",
    "graduation_window", "degree", "location", "enrollment",
]


@dataclass(frozen=True)
class HardConstraint:
    """A posting requirement that is pass/fail, not a matter of degree.

    Kept apart from Requirement because these are *disqualifiers*: no amount
    of skill overlap compensates for a role that cannot sponsor a candidate
    who needs sponsorship. Scoring them as one more weighted feature is the
    most common way job matchers produce confidently wrong advice.
    """

    constraint_id: str
    kind: ConstraintKind
    text: str
    source: str
    value: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Requirement:
    """A gradable requirement -- a skill, tool, domain, or years-of-experience
    ask. `importance` splits the posting's "required" from its "nice to have",
    because a missing preferred skill should cost far less than a missing
    required one.
    """

    requirement_id: str
    text: str
    canonical_skill: str | None = None
    importance: Literal["required", "preferred"] = "required"
    source: str = ""
    years: float | None = None
    # Other skills that satisfy this same ask. "Python or Go" is ONE
    # requirement with two acceptable answers, not two requirements the
    # candidate fails half of -- scoring it as two is how a matcher decides a
    # Python developer is a 50% fit for a Python job.
    alternatives: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "alternatives": list(self.alternatives)}


@dataclass(frozen=True)
class JobRequirements:
    job_key: str
    title: str = ""
    company: str = ""
    requirements: tuple[Requirement, ...] = ()
    constraints: tuple[HardConstraint, ...] = ()
    seniority: str = "unknown"
    min_years: float | None = None
    extractor: str = "rules"

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_key": self.job_key,
            "title": self.title,
            "company": self.company,
            "requirements": [r.as_dict() for r in self.requirements],
            "constraints": [c.as_dict() for c in self.constraints],
            "seniority": self.seniority,
            "min_years": self.min_years,
            "extractor": self.extractor,
        }


# --- match results ----------------------------------------------------------

VerdictStatus = Literal["ok", "risk", "blocked", "unknown"]


@dataclass(frozen=True)
class ConstraintVerdict:
    constraint_id: str
    kind: ConstraintKind
    status: VerdictStatus
    reason: str
    profile_field: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Gate:
    """Result of the hard-constraint stage.

    `passed` False means the role is a dead end for this candidate and the
    decision short-circuits regardless of how good the skill match looks.
    `risks` are soft fails (unknowns, partial location mismatch) that survive
    into the final score as a penalty rather than a veto.
    """

    passed: bool
    verdicts: tuple[ConstraintVerdict, ...] = ()

    @property
    def blockers(self) -> tuple[ConstraintVerdict, ...]:
        return tuple(v for v in self.verdicts if v.status == "blocked")

    @property
    def risks(self) -> tuple[ConstraintVerdict, ...]:
        return tuple(v for v in self.verdicts if v.status in ("risk", "unknown"))

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "verdicts": [v.as_dict() for v in self.verdicts]}


CoverageStatus = Literal["strong", "partial", "missing"]


@dataclass(frozen=True)
class SkillCoverage:
    """How well one requirement is covered -- and by which evidence.

    `evidence_ids` is the whole point. A score without citations is an
    opinion; a score with citations is an argument the candidate can check.
    """

    requirement_id: str
    requirement_text: str
    skill: str | None
    importance: str
    status: CoverageStatus
    score: float
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "evidence_ids": list(self.evidence_ids)}


@dataclass(frozen=True)
class ScoreBreakdown:
    """Every term that moved the final number, kept so the UI can show the
    arithmetic instead of a mystery percentage.
    """

    required_coverage: float
    preferred_coverage: float
    semantic_similarity: float
    seniority_fit: float
    risk_penalty: float
    weights: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    """The answer to "should I apply?", plus the chain that produced it."""

    job_key: str
    title: str
    company: str
    verdict: Literal["apply", "stretch", "skip", "blocked"]
    score: float
    confidence: float
    gate: Gate
    coverages: tuple[SkillCoverage, ...]
    breakdown: ScoreBreakdown
    explanation: str = ""
    explanation_source: str = "deterministic"
    cited_evidence_ids: tuple[str, ...] = ()
    generated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_key": self.job_key,
            "title": self.title,
            "company": self.company,
            "verdict": self.verdict,
            "score": self.score,
            "confidence": self.confidence,
            "gate": self.gate.as_dict(),
            "coverages": [c.as_dict() for c in self.coverages],
            "breakdown": self.breakdown.as_dict(),
            "explanation": self.explanation,
            "explanation_source": self.explanation_source,
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "generated_at": self.generated_at,
        }

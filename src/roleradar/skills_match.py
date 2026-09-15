"""Requirement x evidence -> cited coverage.

The output of this module is the argument the whole product rests on: for
every ask in the posting, either a set of evidence ids that back it, or an
explicit "missing". Nothing in between, and no unattributed credit.

Scoring recognizes that not all evidence is equally strong, which is a
distinction keyword overlap cannot make at all:

    demonstrated + named outright   1.00   "Built X in Postgres" vs "Postgres"
    demonstrated + implied          0.75   "Built X in pgvector" vs "Postgres"
    listed in a skills section      0.55   "Databases: Postgres" vs "Postgres"
    listed + implied                0.40
    absent                          0.00

The gap between 1.00 and 0.55 is deliberate and is the honesty mechanism: a
skills-section keyword is the candidate's claim, not their proof, and a system
that scores the two identically is teaching people to stuff keyword lists.
The UI surfaces that difference as "listed, not demonstrated", which doubles
as the most actionable feedback the product gives.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .models import (
    CandidateProfile, CoverageStatus, EvidenceUnit, Requirement, SkillCoverage,
)
from .taxonomy import expand

# Evidence kinds ordered by how much weight a reader would give them.
_DEMONSTRATED = ("project", "experience", "training")
_STRONG = 1.00
_IMPLIED = 0.75
_LISTED = 0.55
_LISTED_IMPLIED = 0.40
_STRONG_THRESHOLD = 0.75

# Coarse experience bands, in years, used only for years-of-experience asks.
# Deliberately coarse and named as a band rather than computed to two decimals
# from resume date ranges: overlapping internships and part-time work make a
# precise figure spurious, and a fake-precise "2.37 years" invites a scorer to
# treat noise as signal.
_SENIORITY_YEARS = {"student": 0.5, "junior": 1.5, "mid": 3.5,
                    "senior": 7.0, "staff": 10.0, "unknown": 1.0}


def _index_evidence(units: Sequence[EvidenceUnit]) -> dict[str, list[tuple[str, EvidenceUnit]]]:
    """skill -> [(relation, unit)], where relation is "direct" or "implied".

    Built once per decision instead of re-scanning every unit per requirement:
    with ~40 evidence units and ~25 requirements that is 1,000 set lookups
    versus one pass, and it keeps batch scoring over thousands of postings
    linear in evidence rather than quadratic.
    """
    index: dict[str, list[tuple[str, EvidenceUnit]]] = {}
    for unit in units:
        for skill, relation in expand(unit.skills).items():
            index.setdefault(skill, []).append((relation, unit))
    return index


def _score_for(relation: str, unit: EvidenceUnit) -> float:
    demonstrated = unit.kind in _DEMONSTRATED
    if relation == "direct":
        return _STRONG if demonstrated else _LISTED
    return _IMPLIED if demonstrated else _LISTED_IMPLIED


def _rationale(best_relation: str, best_unit: EvidenceUnit, skill: str) -> str:
    if best_unit.kind in _DEMONSTRATED:
        if best_relation == "direct":
            return f"Demonstrated in {best_unit.label}."
        return (f"Implied by {best_unit.label}, which uses a technology that "
                f"requires {skill}.")
    if best_relation == "direct":
        return f"Listed under {best_unit.label}, but no project or role demonstrates it."
    return f"Only indirectly implied by listed skills; nothing demonstrates {skill}."


def cover_requirement(req: Requirement,
                      index: dict[str, list[tuple[str, EvidenceUnit]]],
                      profile: CandidateProfile | None = None,
                      max_citations: int = 3) -> SkillCoverage:
    """Coverage for a single requirement, citing the strongest evidence first."""
    if req.canonical_skill is None:
        return _cover_years(req, profile)

    # An alternatives group ("Python or Go") is satisfied by its best-covered
    # member, and reports *which* one -- the candidate needs to know they
    # qualify via Python, not just that the row is green.
    options = (req.canonical_skill,) + tuple(req.alternatives)
    scored: list[tuple[float, str, EvidenceUnit, str]] = []
    for option in options:
        for rel, unit in index.get(option, []):
            scored.append((_score_for(rel, unit), rel, unit, option))

    if not scored:
        named = " or ".join(options)
        return SkillCoverage(
            requirement_id=req.requirement_id, requirement_text=req.text,
            skill=req.canonical_skill, importance=req.importance,
            status="missing", score=0.0, evidence_ids=(),
            rationale=f"No evidence of {named} anywhere in your resume.",
        )

    scored.sort(key=lambda t: (-t[0], t[2].evidence_id))
    best_score, best_rel, best_unit, best_option = scored[0]
    status: CoverageStatus = "strong" if best_score >= _STRONG_THRESHOLD else "partial"
    rationale = _rationale(best_rel, best_unit, best_option)
    if len(options) > 1:
        rationale = f"Satisfied via {best_option}. " + rationale
    return SkillCoverage(
        requirement_id=req.requirement_id, requirement_text=req.text,
        skill=best_option, importance=req.importance,
        status=status, score=round(best_score, 4),
        evidence_ids=tuple(dict.fromkeys(
            u.evidence_id for _, _, u, _ in scored[:max_citations])),
        rationale=rationale,
    )


def _cover_years(req: Requirement, profile: CandidateProfile | None) -> SkillCoverage:
    """Years-of-experience asks, scored against a coarse seniority band.

    Partial credit rather than pass/fail because "3+ years" on an intern-
    adjacent posting is routinely aspirational -- treating it as a hard bar
    would filter out roles new grads are hired into every cycle.
    """
    want = req.years or 0.0
    have = _SENIORITY_YEARS.get((profile.seniority if profile else "unknown"), 1.0)
    if want <= 0:
        ratio = 1.0
    else:
        ratio = min(have / want, 1.0)
    status: CoverageStatus = (
        "strong" if ratio >= _STRONG_THRESHOLD
        else ("partial" if ratio > 0 else "missing"))
    return SkillCoverage(
        requirement_id=req.requirement_id, requirement_text=req.text,
        skill=None, importance=req.importance, status=status,
        score=round(ratio, 4), evidence_ids=(),
        rationale=(f"Asks for ~{want:g} years; your profile is in the "
                   f"~{have:g}-year band."),
    )


def cover_all(requirements: Iterable[Requirement],
              units: Sequence[EvidenceUnit],
              profile: CandidateProfile | None = None) -> tuple[SkillCoverage, ...]:
    """Coverage for every requirement, required-first then weakest-first.

    Sort order is a product decision, not cosmetics: the candidate needs to
    see the required gaps at the top, because those are what they would have
    to address before applying.
    """
    index = _index_evidence(units)
    covs = [cover_requirement(r, index, profile) for r in requirements]
    return tuple(sorted(covs, key=lambda c: (c.importance != "required", c.score,
                                             c.requirement_text)))


def aggregate(coverages: Iterable[SkillCoverage]) -> tuple[float, float]:
    """(required_coverage, preferred_coverage), each 0..1.

    A posting with no required asks returns 1.0 for that term rather than 0.0
    -- "we could not find any hard requirement" must not be scored as "you
    fail every hard requirement". That sign error is the difference between a
    listing-only posting ranking first and ranking last.
    """
    covs = list(coverages)
    req = [c.score for c in covs if c.importance == "required"]
    pref = [c.score for c in covs if c.importance != "required"]
    return (round(sum(req) / len(req), 4) if req else 1.0,
            round(sum(pref) / len(pref), 4) if pref else 1.0)


def gaps(coverages: Iterable[SkillCoverage], limit: int = 5) -> tuple[SkillCoverage, ...]:
    """The required misses, worst first -- the "what to fix" list."""
    missing = [c for c in coverages
               if c.importance == "required" and c.status != "strong"]
    return tuple(sorted(missing, key=lambda c: c.score)[:limit])


def strengths(coverages: Iterable[SkillCoverage], limit: int = 5) -> tuple[SkillCoverage, ...]:
    """The strongest demonstrated matches -- the "lead with this" list."""
    hits = [c for c in coverages if c.status == "strong" and c.evidence_ids]
    return tuple(sorted(hits, key=lambda c: (c.importance != "required", -c.score))[:limit])

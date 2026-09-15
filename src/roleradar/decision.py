"""The orchestrator: one function that answers "should I apply?".

Stage order is load-bearing, not stylistic:

    extract evidence  ->  extract requirements  ->  gate  ->  cover  ->
    score  ->  verdict  ->  explain

The gate runs before scoring so a blocked role costs almost nothing to
evaluate, and the LLM runs last so it can only ever describe a finished
result. `decide_many` exploits the first property directly: evidence is
extracted once per candidate rather than once per job, and blocked roles
skip explanation entirely, which is what makes scoring a whole 32k-row
result set tractable instead of a per-job API call.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from . import constraints, evidence as ev, explain as explain_mod, ranking, requirements, skills_match
from .models import CandidateProfile, Decision, EvidenceUnit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decide(job: dict, profile: CandidateProfile,
           units: Sequence[EvidenceUnit],
           jd_text: str = "", use_llm: bool = True) -> Decision:
    """Score one posting against one candidate.

    `units` is passed in rather than derived from a resume here so that batch
    callers extract evidence once. It is the single most expensive candidate-
    side step and it does not vary by job.
    """
    reqs = requirements.extract_requirements(job, jd_text)
    return decide_prepared(reqs, profile, units, use_llm=use_llm)


def decide_prepared(reqs, profile: CandidateProfile,
                    units: Sequence[EvidenceUnit],
                    use_llm: bool = True) -> Decision:
    """Same as `decide`, but over already-extracted requirements.

    Split out because requirement extraction is the part an LLM extractor or
    a cache can replace, and the rest of the pipeline must not care which
    produced them.
    """
    gate = constraints.evaluate(reqs.constraints, profile)
    coverages = skills_match.cover_all(reqs.requirements, units, profile)
    candidate_text = ranking.candidate_text_of(units)
    breakdown = ranking.compose(coverages, gate, profile, reqs, candidate_text)
    score = ranking.score_of(breakdown)
    verdict = ranking.verdict_of(score, gate, breakdown)

    decision = Decision(
        job_key=reqs.job_key, title=reqs.title, company=reqs.company,
        verdict=verdict,  # type: ignore[arg-type]
        score=score,
        confidence=ranking.confidence_of(reqs, gate, coverages),
        gate=gate, coverages=coverages, breakdown=breakdown,
        generated_at=_now(),
    )

    # A blocked role gets the deterministic explanation only. Paying a model
    # to write prose about a dead end is spending money to be eloquent about
    # "no" -- the blocker text already says everything useful.
    text, source, cited, _dropped = explain_mod.explain(
        decision, units, use_llm=use_llm and gate.passed)
    decision.explanation = text
    decision.explanation_source = source
    decision.cited_evidence_ids = cited
    return decision


def decide_many(jobs: Iterable[dict], resume: dict,
                profile: CandidateProfile | None = None,
                jd_texts: dict[str, str] | None = None,
                use_llm: bool = False,
                top_k: int | None = None) -> list[Decision]:
    """Rank a whole result set for one candidate.

    `use_llm` defaults to **False** here while it defaults to True for a
    single decision: explaining 500 postings with a model is a cost the user
    did not ask for. The intended flow is batch-rank deterministically, then
    explain the handful the user actually opens.

    Sorted blocked-last, then by score: a blocked role with a 0.9 skill match
    must never outrank an eligible 0.6, because the user cannot accept it.
    """
    units = ev.extract_evidence(resume)
    prof = profile or ev.profile_from_resume(resume)
    texts = jd_texts or {}
    out: list[Decision] = []
    for job in jobs:
        key = str(job.get("dedup_key") or job.get("job_key") or job.get("id") or "")
        out.append(decide(job, prof, units, jd_text=texts.get(key, ""), use_llm=use_llm))
    out.sort(key=lambda d: (d.verdict == "blocked", -d.score, d.company))
    return out[:top_k] if top_k else out


def explain_decision(decision: Decision, units: Sequence[EvidenceUnit]) -> Decision:
    """Attach (or upgrade to) an LLM explanation for one already-scored job.

    The lazy half of the batch flow: `decide_many` leaves deterministic text
    on every row, and this replaces it only for the role the user opened.
    """
    text, source, cited, _dropped = explain_mod.explain(decision, units, use_llm=True)
    decision.explanation = text
    decision.explanation_source = source
    decision.cited_evidence_ids = cited
    return decision

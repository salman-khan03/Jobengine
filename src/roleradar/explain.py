"""Grounded explanation: prose the model writes, but only about facts it was given.

This is the module that makes "AI job matching" defensible rather than
decorative. The generation contract is narrow on purpose:

* The model receives the **already-final** verdict, score, blockers, cited
  coverage rows and the verbatim evidence text. It is not asked to judge
  anything. If the model disagrees with the verdict, the verdict wins -- the
  model is a writer, not the decision-maker.
* The model must return claims, each with `evidence_ids` drawn from the
  supplied set.
* `validate_grounding` then deletes every claim that cites an id it was not
  given, cites nothing, or contains a number that appears nowhere in the
  evidence it cites.

The numeric check catches one common failure mode. A model
asked to sell a candidate will write "you have 3 years of Python experience"
from a resume that never says so. Here that sentence cites an evidence id, the
validator scans the cited text for "3", does not find it, and drops the
sentence before a human ever sees it -- and records why, so the drop rate is
measurable rather than a matter of faith.

These are citation and numeric consistency checks, not semantic entailment.
A cited sentence may still misrepresent its source or express a number in
words. The structured verdict, blockers, and gaps always remain visible;
uncited model summaries and suggested next steps are never published.

If nothing survives, or there is no API key at all, `explain()` returns the
deterministic template. The deterministic version is not a degraded mode; it
is the floor the LLM has to beat, and it is what CI exercises.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Sequence

from . import llm_client
from .models import Decision, EvidenceUnit, Gate, SkillCoverage

SYSTEM_PROMPT = (
    "You are a careful career adviser writing the rationale for an already-"
    "decided recommendation. You are given a verdict, a score, and a list of "
    "evidence items with ids. Your job is ONLY to explain the given verdict in "
    "plain, specific language.\n"
    "Hard rules:\n"
    "1. Never contradict or re-litigate the verdict.\n"
    "2. Every claim about the candidate MUST cite one or more evidence_ids "
    "from the supplied list. Never invent an id.\n"
    "3. Never state a number (years, counts, percentages, dollar amounts) "
    "unless that exact number appears in the evidence text you cite.\n"
    "4. Never claim the candidate has a skill listed as missing.\n"
    "5. No flattery, no hedging filler, no restating the job description.\n"
    'Return strict JSON: {"claims": [{"text": str, "evidence_ids": [str]}]}'
)

# Keep magnitudes intact (10 is not 1), including grouped thousands.
_NUMBER_RE = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {str(Decimal(n.replace(",", "")).normalize())
            for n in _NUMBER_RE.findall(text)}


def validate_grounding(
    claims: Sequence[object],
    evidence: dict[str, EvidenceUnit],
) -> tuple[list[dict], list[dict]]:
    """Split model claims into (kept, dropped-with-reason).

    Returns both halves rather than just the survivors so the drop reason can
    be logged and counted. A grounding checker whose rejections are invisible
    is indistinguishable from one that never rejects anything.
    """
    kept: list[dict] = []
    dropped: list[dict] = []

    for claim in claims:
        if not isinstance(claim, dict):
            dropped.append({"text": "", "evidence_ids": [],
                            "drop_reason": "malformed claim: expected object"})
            continue
        raw_text, ids = claim.get("text"), claim.get("evidence_ids")
        if (not isinstance(raw_text, str) or not isinstance(ids, list)
                or any(not isinstance(i, str) for i in ids)):
            dropped.append({"text": raw_text if isinstance(raw_text, str) else "",
                            "evidence_ids": [], "drop_reason": "malformed claim fields"})
            continue
        text = raw_text.strip()
        if not text:
            continue
        if not ids:
            dropped.append({**claim, "drop_reason": "no evidence cited"})
            continue
        unknown = [i for i in ids if i not in evidence]
        if unknown:
            dropped.append({**claim,
                            "drop_reason": f"cited unknown evidence id(s): "
                                           f"{', '.join(unknown)}"})
            continue
        cited_text = " ".join(evidence[i].text for i in ids)
        supported = _numbers(cited_text)
        bad = _numbers(text) - supported
        if bad:
            dropped.append({**claim,
                            "drop_reason": f"number(s) not in cited evidence: "
                                           f"{', '.join(sorted(bad))}"})
            continue
        kept.append({"text": text, "evidence_ids": ids})
    return kept, dropped


# --- deterministic renderer -------------------------------------------------

_VERDICT_LEAD = {
    "blocked": "Do not apply.",
    "apply": "Apply.",
    "stretch": "Worth a shot, with caveats.",
    "skip": "Probably skip this one.",
}


def deterministic_explanation(verdict: str, score: float, gate: Gate,
                              coverages: Sequence[SkillCoverage],
                              evidence: dict[str, EvidenceUnit],
                              title: str = "", company: str = "") -> str:
    """Render the structured decision without introducing model-generated facts.

    Accuracy still depends on the extraction and decision rules upstream.
    """
    from . import skills_match

    lines = [f"{_VERDICT_LEAD.get(verdict, '')} Match score {score * 100:.0f}/100"
             + (f" for {title} at {company}." if title else ".")]

    blockers = gate.blockers
    if blockers:
        lines.append("")
        lines.append("Blocking:")
        lines.extend(f"- {b.reason}" for b in blockers)

    hits = skills_match.strengths(coverages)
    if hits:
        lines.append("")
        lines.append("What backs you up:")
        for c in hits:
            cite = evidence.get(c.evidence_ids[0]) if c.evidence_ids else None
            where = f" ({cite.label} — {cite.source})" if cite else ""
            lines.append(f"- {c.skill}: {c.rationale}{where}")

    misses = skills_match.gaps(coverages)
    if misses:
        lines.append("")
        lines.append("Gaps against the required list:")
        for c in misses:
            lines.append(f"- {c.skill or c.requirement_text[:60]}: {c.rationale}")

    risks = gate.risks
    if risks:
        lines.append("")
        lines.append("Flags to check before applying:")
        lines.extend(f"- {r.reason}" for r in risks)

    return "\n".join(lines).strip()


# --- LLM path ---------------------------------------------------------------

def _shown_evidence(coverages: Sequence[SkillCoverage],
                    evidence: dict[str, EvidenceUnit], limit: int = 14
                    ) -> dict[str, EvidenceUnit]:
    from . import skills_match

    rows = list(skills_match.strengths(coverages, limit=6)) + \
        list(skills_match.gaps(coverages, limit=6))
    ids = dict.fromkeys(i for c in rows for i in c.evidence_ids if i in evidence)
    return {i: evidence[i] for i in list(ids)[:limit]}


def _context(verdict: str, score: float, gate: Gate,
             coverages: Sequence[SkillCoverage],
             evidence: dict[str, EvidenceUnit],
             title: str, company: str, limit: int = 14) -> str:
    """The prompt payload: only the evidence the model is allowed to cite.

    Truncated to the rows that actually drove the decision. Sending all ~40
    evidence units would cost more tokens and, worse, give the model room to
    cite something irrelevant that still passes validation.
    """
    from . import skills_match

    rows = list(skills_match.strengths(coverages, limit=6)) + \
        list(skills_match.gaps(coverages, limit=6))
    shown = _shown_evidence(coverages, evidence, limit)

    parts = [
        f"ROLE: {title} at {company}",
        f"FINAL VERDICT (do not change): {verdict}",
        f"SCORE: {score * 100:.0f}/100",
        "",
        "BLOCKERS:" if gate.blockers else "BLOCKERS: none",
    ]
    parts.extend(f"- {b.kind}: {b.reason}" for b in gate.blockers)
    parts.append("")
    parts.append("RISK FLAGS:" if gate.risks else "RISK FLAGS: none")
    parts.extend(f"- {r.kind}: {r.reason}" for r in gate.risks)
    parts.append("")
    parts.append("REQUIREMENT COVERAGE:")
    for c in rows:
        parts.append(f"- [{c.importance}/{c.status}] {c.skill or c.requirement_text[:60]}"
                     f" :: {c.rationale} :: cites {', '.join(c.evidence_ids) or 'none'}")
    parts.append("")
    parts.append("EVIDENCE (cite by id; quote nothing that is not here):")
    for i, u in shown.items():
        parts.append(f"- {i} [{u.kind}] {u.label} ({u.source}): {u.text}")
    return "\n".join(parts)


def _render(summary: str, claims: Sequence[dict],
            evidence: dict[str, EvidenceUnit]) -> str:
    out = [summary.strip()] if summary.strip() else []
    if claims:
        out.append("")
        for c in claims:
            cites = ", ".join(
                f"{evidence[i].label} — {evidence[i].source}"
                for i in c["evidence_ids"] if i in evidence
            )
            out.append(f"- {c['text'].rstrip()} [{cites}]" if cites else f"- {c['text']}")
    return "\n".join(out).strip()


def explain(decision: Decision, evidence_units: Sequence[EvidenceUnit],
            use_llm: bool = True) -> tuple[str, str, tuple[str, ...], list[dict]]:
    """(text, source, cited_evidence_ids, dropped_claims).

    `source` is "llm" or "deterministic" and is stored on the Decision, so a
    reviewer can always tell which explanations a model wrote. `dropped` is
    returned rather than logged-and-forgotten so callers can report the
    grounding rejection rate.
    """
    evidence = {u.evidence_id: u for u in evidence_units}
    fallback = deterministic_explanation(
        decision.verdict, decision.score, decision.gate, decision.coverages,
        evidence, decision.title, decision.company)
    all_cited = tuple(i for c in decision.coverages for i in c.evidence_ids)

    if not use_llm or not llm_client.available():
        return fallback, "deterministic", all_cited, []

    payload = llm_client.complete_json(
        SYSTEM_PROMPT,
        _context(decision.verdict, decision.score, decision.gate,
                 decision.coverages, evidence, decision.title, decision.company),
    )
    if not isinstance(payload, dict):
        return fallback, "deterministic", all_cited, []

    claims = payload.get("claims")
    if not isinstance(claims, list):
        return fallback, "deterministic", all_cited, []

    # Scores belong to the deterministic decision, not candidate evidence.
    kept, dropped = validate_grounding(
        claims, _shown_evidence(decision.coverages, evidence))
    if not kept:
        # Everything the model said was unsupported. Publishing the summary
        # alone would be publishing exactly the unverifiable half.
        return fallback, "deterministic", all_cited, dropped

    # Retain the authoritative recommendation and its blockers/gaps. Model
    # summaries and next steps have no evidence contract and are discarded.
    text = _render(fallback, kept, evidence)
    cited = tuple(dict.fromkeys((*all_cited,
                                *(i for c in kept for i in c["evidence_ids"]))))
    return (text or fallback), ("llm" if text else "deterministic"), cited, dropped

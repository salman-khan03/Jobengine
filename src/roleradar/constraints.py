"""Hard-constraint gate: the pass/fail stage that runs before any scoring.

Why a separate stage rather than more features in the scorer: eligibility is
not continuous. A role that cannot sponsor is not "a slightly worse match" for
a candidate who needs sponsorship -- it is a zero, and averaging it with a 0.9
skill overlap produces a confident, expensive lie. So this module can veto,
and `ranking.py` respects the veto instead of out-voting it.

The three-way outcome is the other half of the design:

  blocked -> disqualifying, decision short-circuits
  risk    -> real but not fatal (or genuinely unknown), scored as a penalty
  ok      -> satisfied, shown as a green line so the user sees it was checked

`unknown` is never silently promoted to `ok`. If the candidate has not told us
their work authorization, a posting that forbids sponsorship yields a *risk*
with an explicit "tell us your status for a definite answer" -- the system
declines to guess rather than guessing wrong in either direction. Guessing
"blocked" would hide real opportunities; guessing "ok" would waste real
applications.
"""
from __future__ import annotations

import re
from datetime import date

from .models import CandidateProfile, ConstraintVerdict, Gate, HardConstraint

_DEGREE_ORDER = {"associates": 0, "bachelors": 1, "masters": 2, "phd": 3}
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def parse_grad(value: str | None) -> tuple[int, int] | None:
    """"May 2027" / "2027-05" / "Spring 2027" -> (2027, 5). Month defaults to
    June (a mid-year anchor) when only a year is given, so a "graduating by
    June 2027" window neither auto-passes nor auto-fails a bare "2027".
    """
    if not value:
        return None
    low = str(value).lower()
    m = _YEAR_RE.search(low)
    if not m:
        return None
    year = int(m.group(0))
    for name, num in _MONTHS.items():
        if name in low:
            return year, num
    for season, num in (("spring", 5), ("summer", 8), ("fall", 12),
                        ("autumn", 12), ("winter", 1)):
        if season in low:
            return year, num
    iso = re.search(r"(?:19|20)\d{2}-(\d{2})", low)
    if iso:
        return year, int(iso.group(1))
    return year, 6


def _verdict(c: HardConstraint, status: str, reason: str,
             field: str = "") -> ConstraintVerdict:
    return ConstraintVerdict(
        constraint_id=c.constraint_id, kind=c.kind,
        status=status,  # type: ignore[arg-type]
        reason=reason, profile_field=field,
    )


def _sponsorship(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    if c.value == "available":
        return _verdict(c, "ok", "Employer states sponsorship is available.",
                        "needs_sponsorship")
    if p.needs_sponsorship is True:
        return _verdict(
            c, "blocked",
            "You need visa sponsorship and this employer states it is not "
            "available. Applying cannot lead to an offer you can accept.",
            "needs_sponsorship")
    if p.needs_sponsorship is False:
        return _verdict(c, "ok",
                        "No sponsorship needed, so this restriction does not apply.",
                        "needs_sponsorship")
    return _verdict(
        c, "unknown",
        "This role does not sponsor. Set your work-authorization status to get "
        "a definite answer instead of a warning.",
        "needs_sponsorship")


def _citizenship(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    if p.us_citizen is True:
        return _verdict(c, "ok", "Citizenship requirement met.", "us_citizen")
    if p.us_citizen is False:
        return _verdict(c, "blocked",
                        "Posting restricts this role to US citizens or green-card "
                        "holders.", "us_citizen")
    return _verdict(c, "unknown",
                    "Posting mentions a citizenship requirement; your status is "
                    "not set.", "us_citizen")


def _clearance(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    if p.security_clearance:
        return _verdict(c, "ok", "You hold a clearance.", "security_clearance")
    active = bool(re.search(r"\bactive\b|\bcurrent\b|must (?:have|hold)", c.text.lower()))
    if active:
        return _verdict(
            c, "blocked",
            "Role requires an already-active security clearance, which cannot be "
            "obtained by applying.", "security_clearance")
    # "Ability to obtain a clearance" is sponsorable by the employer and is a
    # real but surmountable hurdle -- a risk, not a veto.
    return _verdict(c, "risk",
                    "Role involves a security clearance you do not hold; usually "
                    "requires US citizenship and a months-long process.",
                    "security_clearance")


def _work_auth(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    if p.needs_sponsorship is True:
        # Deliberately not a blocker. An F-1 student on CPT/OPT *is* legally
        # authorized to work; that clause only becomes disqualifying when the
        # posting also rules out future sponsorship, which is a separate
        # constraint that the sponsorship rule above catches on its own.
        return _verdict(
            c, "risk",
            "You are work-authorized via CPT/OPT for the role itself, but this "
            "employer may read this clause as excluding future sponsorship.",
            "work_authorization")
    return _verdict(c, "ok", "You are authorized to work without sponsorship.",
                    "work_authorization")


def _graduation(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    grad = parse_grad(p.graduation)
    years = sorted({int(y) for y in _YEAR_RE.findall(c.value or "")}) or \
        sorted({int(y) for y in _YEAR_RE.findall(c.text)})
    if not grad:
        return _verdict(c, "unknown",
                        "Posting restricts graduation dates; your graduation date "
                        "is not set.", "graduation")
    if not years:
        return _verdict(c, "risk",
                        "Posting restricts graduation dates but the window could "
                        "not be parsed -- check the posting.", "graduation")
    lo, hi = min(years), max(years)
    if lo <= grad[0] <= hi:
        return _verdict(c, "ok",
                        f"You graduate {p.graduation}, inside the posting's "
                        f"{lo}-{hi} window.", "graduation")
    return _verdict(
        c, "blocked",
        f"Posting targets {lo}-{hi} graduates; you graduate {p.graduation}.",
        "graduation")


def _degree(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    low = c.text.lower()
    needed = "bachelors"
    if "phd" in low or "ph.d" in low or "doctorate" in low:
        needed = "phd"
    elif "master" in low or re.search(r"\bm\.?s\.?\b", low):
        needed = "masters"
    have, want = _DEGREE_ORDER.get(p.degree_level, 1), _DEGREE_ORDER[needed]
    if have >= want:
        return _verdict(c, "ok", f"Your {p.degree_level} degree meets the "
                                 f"{needed} requirement.", "degree_level")
    # An "or equivalent"/"or related" clause is the employer telling you the
    # bar is soft; without one, a PhD-only ask is close to a veto but still
    # not one, because postings routinely over-state degree requirements.
    return _verdict(c, "risk",
                    f"Posting asks for a {needed} degree; you have a "
                    f"{p.degree_level}.", "degree_level")


def _enrollment(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    if p.seniority == "student":
        return _verdict(c, "ok", "You are currently enrolled.", "seniority")
    return _verdict(c, "blocked",
                    "Role requires current student enrollment.", "seniority")


def _location(c: HardConstraint, p: CandidateProfile) -> ConstraintVerdict:
    if c.value == "remote":
        return _verdict(c, "ok", "Remote role.", "location")
    here = (p.location or "").lower()
    there = c.text.lower()
    if here and any(tok and tok in there for tok in re.split(r"[,\s]+", here) if len(tok) > 3):
        return _verdict(c, "ok", "Role location matches your location.", "location")
    if p.open_to_relocate:
        return _verdict(c, "risk",
                        "On-site role outside your area; you are open to "
                        "relocating, so this is a cost, not a blocker.", "location")
    return _verdict(c, "blocked",
                    "On-site role outside your area and you are not open to "
                    "relocating.", "location")


_HANDLERS = {
    "sponsorship": _sponsorship,
    "citizenship": _citizenship,
    "clearance": _clearance,
    "work_authorization": _work_auth,
    "graduation_window": _graduation,
    "degree": _degree,
    "enrollment": _enrollment,
    "location": _location,
}


def evaluate(constraints: tuple[HardConstraint, ...] | list[HardConstraint],
             profile: CandidateProfile) -> Gate:
    """Run every constraint against the profile.

    An unrecognized constraint kind produces an `unknown` verdict rather than
    being skipped: a requirement nobody wrote a handler for still deserves to
    be shown to the candidate, and silence here is how eligibility bugs hide.
    """
    verdicts = []
    for c in constraints:
        handler = _HANDLERS.get(c.kind)
        if handler is None:
            verdicts.append(_verdict(c, "unknown",
                                     f"Unhandled requirement: {c.text[:120]}"))
        else:
            verdicts.append(handler(c, profile))
    return Gate(passed=not any(v.status == "blocked" for v in verdicts),
                verdicts=tuple(verdicts))


def risk_penalty(gate: Gate) -> float:
    """Total score penalty from non-fatal risks, capped at 0.30.

    Capped because risks are correlated (an on-site role far away is often
    also the one asking about relocation and citizenship), and letting four
    soft flags sum to a full veto would quietly re-create the blocking
    behaviour this stage deliberately separates out.
    """
    weights = {"clearance": 0.12, "citizenship": 0.10, "sponsorship": 0.10,
               "graduation_window": 0.08, "degree": 0.05, "location": 0.04,
               "work_authorization": 0.04, "enrollment": 0.05}
    total = sum(weights.get(v.kind, 0.03) for v in gate.risks)
    return round(min(total, 0.30), 4)


def default_profile_today() -> date:
    """Indirection so tests can pin "today" without monkeypatching datetime."""
    return date.today()

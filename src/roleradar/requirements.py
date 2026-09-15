"""Job posting -> structured requirements + hard constraints (rules layer).

The rules extractor is the *default*, not the fallback. An LLM extractor
(extract_llm.py) can refine the result, but the system must produce a correct,
fully-cited decision for all 32k ingested postings with no API key, no network,
and no per-call cost. Anything else is a demo, not a pipeline.

Two things this stage must get right, in priority order:

1. **Never miss a disqualifier.** A false "you can apply" on a role that says
   "we do not sponsor" wastes a real application on a candidate who needs
   sponsorship. Constraint patterns are therefore matched on normalized text
   with negation handled explicitly ("will not sponsor" vs "will sponsor"),
   and anything ambiguous is emitted as a constraint whose *verdict* becomes a
   flagged risk -- surfaced, never silently dropped.
2. **Separate required from preferred.** Section-aware parsing, because the
   same sentence ("Experience with Kubernetes") means something very different
   under "Minimum Qualifications" than under "Nice to have".

Every emitted object records the line it came from (`source="jd:L42"`), which
is what lets the UI highlight the exact sentence behind a blocker.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from .models import HardConstraint, JobRequirements, Requirement
from .taxonomy import extract_skills

# --- section detection ------------------------------------------------------

_PREFERRED_HEADERS = (
    "preferred qualification", "preferred skill", "nice to have", "nice-to-have",
    "bonus", "desired", "preferred experience",
    "good to have", "we'd love", "we would love", "stand out",
)
_REQUIRED_HEADERS = (
    "minimum qualification", "basic qualification", "required qualification",
    "requirements", "what you need", "what you'll need", "what we're looking for",
    "must have", "must-have", "qualifications", "who you are", "your background",
)
_NEUTRAL_HEADERS = (
    "responsibilities", "what you'll do", "what you will do", "about the role",
    "about us", "the role", "benefits", "perks", "compensation", "equal opportunity",
)

_HEADER_MAX_WORDS = 8


def _header_kind(line: str, bulleted: bool = False) -> str | None:
    """Classify a line as a section header, or None if it is body text.

    Two guards, both learned from real postings:

    * **Bulleted lines are never headers.** "- Experience with React or
      Next.js is a plus" contains a preferred-section phrase, and treating it
      as a header both loses its skills *and* silently reclassifies every
      requirement after it. Headers do not carry bullet glyphs; list items do.
    * **Length-gated.** "Requirements" is a header; a 30-word sentence
      containing the word "requirements" is prose and must not flip the
      importance of everything that follows it.
    """
    if bulleted:
        return None
    stripped = line.strip().strip(":").strip()
    if not stripped or len(stripped.split()) > _HEADER_MAX_WORDS:
        return None
    low = stripped.lower()
    if any(h in low for h in _PREFERRED_HEADERS):
        return "preferred"
    if any(h in low for h in _REQUIRED_HEADERS):
        return "required"
    if any(h in low for h in _NEUTRAL_HEADERS):
        return "neutral"
    return None


_MUST_WORDS = re.compile(
    r"\b(must|required|require|requires|minimum|at least|essential|mandatory)\b")
_NICE_WORDS = re.compile(
    r"\b(preferred|plus|bonus|nice to have|ideally|desirable|familiarity)\b")


def _line_importance(line: str, section: str) -> str:
    """In-line modals override the section, because postings mix them freely:
    a "Preferred" section routinely contains one "must be enrolled" line.
    """
    low = line.lower()
    if _NICE_WORDS.search(low):
        return "preferred"
    if _MUST_WORDS.search(low):
        return "required"
    if section in ("required", "preferred"):
        return section
    # Unlabelled prose (responsibilities, blurb). Skills mentioned there are
    # real signal but weak evidence of a hard requirement, so they must not
    # be able to tank a candidate's required-coverage score.
    return "preferred"


# --- hard constraints -------------------------------------------------------

# (kind, value, compiled pattern). Order matters: the first pattern that fires
# for a given kind on a given line wins, so the more specific negative forms
# are listed before the permissive ones.
_CONSTRAINT_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # Negation is spelled a dozen ways in real postings and getting any of
    # them wrong means telling a candidate who needs sponsorship to apply to a
    # role that cannot hire them. Listed explicitly rather than assembled from
    # a clever "can|will + n't" pattern, because "can" already consumes the
    # "n" of "can't" and that bug passed a whole test suite unnoticed.
    ("sponsorship", "unavailable", re.compile(
        r"(?:cannot|can\s?not|can't|will\s+not|won't|do(?:es)?\s+not"
        r"|do(?:es)?n't|is\s+not|isn't|are\s+not|aren't|unable\s+to)"
        r"\s+(?:be\s+)?(?:able\s+to\s+)?(?:provide|offer|sponsor)"
        r"[^.]{0,40}?(?:sponsor|visa)"
        r"|no\s+(?:visa\s+)?sponsorship"
        r"|sponsorship\s+(?:is\s+not|isn't)\s+(?:available|offered|provided)"
        r"|without\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+)?"
        r"(?:visa\s+)?sponsorship"
        r"|not\s+eligible\s+for\s+(?:visa\s+)?sponsorship")),
    ("sponsorship", "available", re.compile(
        r"(?:sponsorship\s+(?:is\s+)?available"
        r"|will\s+sponsor"
        r"|we\s+sponsor\s+visas"
        r"|open\s+to\s+sponsor)")),
    ("citizenship", "required", re.compile(
        r"(?:must\s+be\s+a\s+)?u\.?s\.?\s+citizen(?:ship)?\s*(?:is\s+)?"
        r"(?:required|only)?"
        r"|citizenship\s+required"
        r"|green\s+card\s+holder")),
    ("clearance", "required", re.compile(
        r"(?:active\s+)?(?:security\s+)?clearance"
        r"|ts/sci|top\s+secret|secret\s+clearance|public\s+trust")),
    ("work_authorization", "required", re.compile(
        r"(?:legally\s+)?authorized\s+to\s+work"
        r"|work\s+authorization\s+(?:is\s+)?required"
        r"|eligible\s+to\s+work\s+in\s+the\s+u")),
    ("enrollment", "required", re.compile(
        r"currently\s+enrolled"
        r"|actively\s+enrolled"
        r"|(?:rising|current)\s+(?:junior|senior|sophomore)"
        r"|must\s+be\s+(?:a\s+)?(?:full[-\s]?time\s+)?student"
        r"|pursuing\s+(?:a|an)\s+(?:bachelor|master|b\.?s|m\.?s|degree)")),
    ("degree", "required", re.compile(
        r"(?:bachelor|master|phd|ph\.d|doctorate|b\.?s\.?|m\.?s\.?)"
        r"[^.]{0,30}(?:degree|required|or\s+equivalent)")),
    ("graduation_window", "required", re.compile(
        r"graduat\w*\s+(?:in|by|between|before|after|no\s+later\s+than)\s+"
        r"[^.]{0,50}?(?:19|20)\d{2}"
        r"|(?:19|20)\d{2}\s+grad(?:uate|uation)?s?\b"
        r"|expected\s+graduation[^.]{0,40}(?:19|20)\d{2}"
        r"|degree\s+conferral[^.]{0,40}(?:19|20)\d{2}")),
    ("location", "onsite", re.compile(
        r"\bon[-\s]?site\b|\bin[-\s]office\b|hybrid\b|\bin\s+person\b"
        r"|relocat\w+\s+(?:is\s+)?required")),
    ("location", "remote", re.compile(r"\b(?:fully\s+)?remote\b|work\s+from\s+anywhere")),
)

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_YEARS_EXP_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)\s+(?:of\s+)?"
    r"(?:relevant\s+|professional\s+|industry\s+|hands[-\s]on\s+)?experience")


def _cid(kind: str, line_no: int, text: str) -> str:
    return f"hc_{kind[:4]}_{hashlib.sha1(f'{line_no}{text}'.encode()).hexdigest()[:6]}"


def _rid(text: str, skill: str | None) -> str:
    return f"rq_{hashlib.sha1(f'{skill}|{text}'.encode()).hexdigest()[:8]}"


# "Python or Go", "React/Vue", "Java, Kotlin, or Scala" -- one ask, several
# acceptable answers. Requires an explicit disjunction token, so "Docker and
# Kubernetes" (two real asks) is never collapsed into one.
_DISJUNCTION_RE = re.compile(r"\bor\b|\beither\b|/")
# ...but only when the disjunction sits between the skills rather than after
# them ("Kubernetes and Docker, or similar tooling" is a conjunction with a
# trailing hedge). Checked by requiring no conjunction token in the span.
_CONJUNCTION_RE = re.compile(r"\band\b|\bplus\b|&")


def _is_disjunctive(line: str, skills: tuple[str, ...]) -> bool:
    """True when a line offers alternatives rather than listing requirements.

    Conservative by design: a false positive merges two genuine requirements
    into one and silently forgives a real gap, which is worse for a decision
    system than a false negative that merely under-credits the candidate.
    """
    if len(skills) < 2:
        return False
    low = line.lower()
    return bool(_DISJUNCTION_RE.search(low)) and not _CONJUNCTION_RE.search(low)


def _clean(line: str) -> str:
    """Strip bullet glyphs/numbering so pattern anchors see the real sentence."""
    return re.sub(r"^\s*(?:[-*•‣◦⁃∙+>]|\d+[.)])\s*", "", line).strip()


def find_constraints(jd_text: str, extra_source: str = "jd") -> tuple[HardConstraint, ...]:
    """Scan a posting for pass/fail conditions.

    At most one constraint per (kind, value) pair survives, keyed on the first
    line that produced it -- postings repeat their sponsorship language in the
    body and again in a legal footer, and showing the candidate the same
    blocker three times is noise.
    """
    found: dict[tuple[str, str], HardConstraint] = {}
    for i, raw in enumerate((jd_text or "").splitlines(), start=1):
        line = _clean(raw)
        if not line:
            continue
        low = line.lower()
        for kind, value, pattern in _CONSTRAINT_PATTERNS:
            if not pattern.search(low):
                continue
            key = (kind, value)
            if key in found:
                continue
            found[key] = HardConstraint(
                constraint_id=_cid(kind, i, line),
                kind=kind,  # type: ignore[arg-type]
                text=line[:300],
                source=f"{extra_source}:L{i}",
                value=_constraint_value(kind, value, low),
            )
    # A posting that says both "sponsorship available" and "will not sponsor"
    # is either two roles in one page or boilerplate contradiction. The safe
    # reading for a candidate who needs sponsorship is the negative one, so
    # the permissive variant is dropped rather than both being shown.
    if ("sponsorship", "unavailable") in found:
        found.pop(("sponsorship", "available"), None)
    return tuple(found.values())


def _constraint_value(kind: str, value: str, low: str) -> str:
    """Attach the parsed payload a verdict needs (e.g. the graduation years)."""
    if kind == "graduation_window":
        years = sorted({int(y) for y in _YEAR_RE.findall(low)})
        if years:
            return ",".join(str(y) for y in years)
    return value


def find_requirements(jd_text: str, title: str = "",
                      source: str = "jd") -> tuple[Requirement, ...]:
    """Gradable asks, one per (skill, importance-winning) mention.

    A skill named in both a required and a preferred section resolves to
    required -- the strictest reading of what the employer asked for.
    """
    by_skill: dict[str, Requirement] = {}
    other: list[Requirement] = []
    section = "neutral"

    for i, raw in enumerate((jd_text or "").splitlines(), start=1):
        line = _clean(raw)
        if not line:
            continue
        kind = _header_kind(line, bulleted=line != raw.strip())
        if kind:
            section = kind
            continue
        importance = _line_importance(line, section)
        skills = extract_skills(line)
        if _is_disjunctive(line, skills):
            # One requirement, keyed on the first-named skill, satisfied by any
            # of them. Keyed on the whole group so the same "Python or Go" line
            # repeated elsewhere in the posting does not produce a second row.
            primary, alternatives = skills[0], skills[1:]
            key = "|".join(sorted(skills))
            existing = by_skill.get(key)
            if not (existing and (existing.importance == "required"
                                  or importance == "preferred")):
                by_skill[key] = Requirement(
                    requirement_id=_rid(key, primary),
                    text=line[:240],
                    canonical_skill=primary,
                    importance=importance,  # type: ignore[arg-type]
                    source=f"{source}:L{i}",
                    alternatives=alternatives,
                )
            continue
        for skill in skills:
            existing = by_skill.get(skill)
            if existing and (existing.importance == "required" or importance == "preferred"):
                continue
            by_skill[skill] = Requirement(
                requirement_id=_rid(skill, skill),
                text=line[:240],
                canonical_skill=skill,
                importance=importance,  # type: ignore[arg-type]
                source=f"{source}:L{i}",
            )
        years = _YEARS_EXP_RE.search(line.lower())
        if years and not skills:
            other.append(Requirement(
                requirement_id=_rid(line[:60], None),
                text=line[:240],
                canonical_skill=None,
                importance=importance,  # type: ignore[arg-type]
                source=f"{source}:L{i}",
                years=float(years.group(1)),
            ))

    # Title skills are requirements even when the body never repeats them: a
    # "Backend Engineer, Go" posting requires Go whether or not a bullet says so.
    for skill in extract_skills(title):
        by_skill.setdefault(skill, Requirement(
            requirement_id=_rid(skill, skill),
            text=f"Role title: {title}".strip(),
            canonical_skill=skill,
            importance="required",
            source="title",
        ))

    return tuple(by_skill.values()) + tuple(other)


_SENIORITY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("intern", ("intern", "internship", "co-op", "coop", "summer analyst")),
    ("new_grad", ("new grad", "new-grad", "university grad", "campus hire",
                  "early career", "entry level", "entry-level", "graduate program",
                  "rotational")),
    ("staff", ("staff", "principal", "distinguished", "architect", "fellow")),
    ("senior", ("senior", "sr.", "sr ", "lead", "manager", "director", "head of")),
    ("mid", ("ii", "iii", "mid-level")),
    ("junior", ("junior", "jr.", "associate", " i ")),
)


def infer_seniority(title: str, jd_text: str = "") -> str:
    """Seniority from the title first, body only as a tiebreak.

    Ordering is not alphabetical: "Senior Software Engineering Intern" does
    not exist, but "Intern" appearing anywhere in a title is decisive, whereas
    "lead" shows up in senior *and* staff titles. Most-specific first.
    """
    low = f" {title.lower()} "
    for label, needles in _SENIORITY_RULES:
        if any(n in low for n in needles):
            return label
    low_body = (jd_text or "").lower()
    for label, needles in _SENIORITY_RULES[:2]:
        if any(n in low_body for n in needles):
            return label
    return "unknown"


def _min_years(reqs: Iterable[Requirement], jd_text: str) -> float | None:
    """The smallest years-of-experience figure asked for.

    Smallest, not largest: a posting listing "2+ years" under minimum and
    "5+ years" under preferred has a real bar of 2. Taking the max would
    mark every strong candidate as under-qualified.
    """
    values = [r.years for r in reqs if r.years is not None]
    values += [float(m.group(1)) for m in _YEARS_EXP_RE.finditer((jd_text or "").lower())]
    return min(values) if values else None


def extract_requirements(job: dict, jd_text: str = "") -> JobRequirements:
    """Full structured view of one posting.

    `job` is a row from JobEngine's `jobs` table (or any dict with
    company/title/locations/sponsor_tier). `jd_text` is the pasted description
    when the candidate has it -- most aggregated listings do not ship one, and
    the extractor degrades to title + row metadata rather than failing.
    """
    title = str(job.get("title") or "")
    body = jd_text or ""
    reqs = find_requirements(body, title)
    constraints = list(find_constraints(body))

    # The ingest pipeline already resolved sponsorship from H-1B LCA filings
    # (sponsor_index.py). That is stronger evidence than JD prose, so it is
    # promoted to a first-class constraint when the posting itself is silent.
    tier = str(job.get("sponsor_tier") or "unknown")
    if tier in ("does_not_sponsor", "citizen_only") and not any(
            c.kind == "sponsorship" for c in constraints):
        constraints.append(HardConstraint(
            constraint_id=f"hc_spon_{tier}",
            kind="sponsorship",
            text=f"Employer sponsorship tier from H-1B filing history: {tier}",
            source="sponsor_index",
            value="unavailable",
        ))

    locations = job.get("locations")
    if locations and not any(c.kind == "location" for c in constraints):
        loc_text = locations if isinstance(locations, str) else ", ".join(map(str, locations))
        constraints.append(HardConstraint(
            constraint_id=f"hc_loca_{hashlib.sha1(loc_text.encode()).hexdigest()[:6]}",
            kind="location",
            text=f"Location: {loc_text}",
            source="listing.locations",
            value="remote" if "remote" in loc_text.lower() else "onsite",
        ))

    return JobRequirements(
        job_key=str(job.get("dedup_key") or job.get("job_key") or job.get("id") or ""),
        title=title,
        company=str(job.get("company") or ""),
        requirements=reqs,
        constraints=tuple(constraints),
        seniority=infer_seniority(title, body),
        min_years=_min_years(reqs, body),
        extractor="rules",
    )

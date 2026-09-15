"""Resume -> evidence units, with provenance.

This is the candidate half of the grounding contract. Every EvidenceUnit is a
*verbatim* slice of resume.json tagged with the JSON path it came from, so a
downstream claim like "you have shipped Postgres work" can be expanded into
"...at projects[1].bullets[0]: 'Modelled 32k listings in Postgres'".

Two deliberate non-features:

* **Nothing is rewritten.** No paraphrasing, no LLM "enhancement" of bullets.
  The moment text is rewritten, provenance becomes a lie -- the citation would
  point at a bullet the candidate never wrote. JobEngine's metrics_audit.py
  exists to catch inflated resume claims; it would be incoherent for RoleRadar
  to generate them.
* **No skill inference from vibes.** Skills attached to a unit come from
  taxonomy.extract_skills over the unit's own text plus its declared stack.
  If the word is not there, the skill is not claimed.

Evidence ids are content-addressed (`ev_<kind>_<8 hex>`) rather than
positional, so re-ordering projects in resume.json does not invalidate every
stored citation from a previous decision -- which matters once decisions are
persisted and evaluated against outcomes months later.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .models import CandidateProfile, EvidenceUnit
from .taxonomy import extract_skills

_MAX_TEXT = 600


def _eid(kind: str, source: str, text: str) -> str:
    digest = hashlib.sha1(f"{kind}|{source}|{text}".encode("utf-8")).hexdigest()[:8]
    return f"ev_{kind[:4]}_{digest}"


def _unit(kind: str, label: str, text: str, source: str,
          extra_skill_text: str = "", started: str | None = None,
          ended: str | None = None) -> EvidenceUnit:
    text = " ".join((text or "").split())[:_MAX_TEXT]
    skills = extract_skills(f"{text} {extra_skill_text}")
    return EvidenceUnit(
        evidence_id=_eid(kind, source, text),
        kind=kind,  # type: ignore[arg-type]
        label=label,
        text=text,
        source=source,
        skills=skills,
        started=started,
        ended=ended,
    )


def _split_dates(dates: str | None) -> tuple[str | None, str | None]:
    """"Jan 2025 - Present" -> ("Jan 2025", "Present"). Best-effort: an
    unparseable string is kept whole as the start so nothing is silently lost.
    """
    if not dates:
        return None, None
    for sep in (" - ", " – ", " — ", "-", "–", "—", " to "):
        if sep in dates:
            left, _, right = dates.partition(sep)
            return left.strip() or None, right.strip() or None
    return dates.strip() or None, None


def _iter_section(resume: dict, key: str, kind: str) -> Iterable[EvidenceUnit]:
    """Emit one unit per bullet, plus a header unit naming the item itself.

    Per-bullet granularity is what makes citations useful: "your Redis caching
    work" should point at the one bullet about Redis, not at a whole project
    the reader then has to scan.
    """
    for i, item in enumerate(resume.get(key) or []):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("title") or f"{key}[{i}]"
        stack = item.get("stack") or []
        stack_text = " ".join(str(s) for s in stack)
        started, ended = _split_dates(item.get("dates"))
        org = item.get("org") or item.get("location") or ""
        header = " ".join(x for x in [str(name), stack_text, str(org)] if x)
        if header.strip():
            yield _unit(kind, str(name), header, f"{key}[{i}]",
                        extra_skill_text=stack_text, started=started, ended=ended)
        for b, bullet in enumerate(item.get("bullets") or []):
            if not str(bullet).strip():
                continue
            yield _unit(kind, str(name), str(bullet), f"{key}[{i}].bullets[{b}]",
                        extra_skill_text=stack_text, started=started, ended=ended)


def extract_evidence(resume: dict) -> tuple[EvidenceUnit, ...]:
    """All citable units in a resume.json, deduplicated by evidence_id.

    Dedup matters because the same sentence can legitimately appear under two
    sections (a project that is also listed as work); citing it twice would
    double-count it in coverage scoring.
    """
    units: dict[str, EvidenceUnit] = {}

    def add(u: EvidenceUnit) -> None:
        units.setdefault(u.evidence_id, u)

    for kind, key in (("project", "projects"), ("experience", "experience"),
                      ("training", "training")):
        for u in _iter_section(resume, key, kind):
            add(u)

    edu = resume.get("education")
    for i, e in enumerate([edu] if isinstance(edu, dict) else (edu or [])):
        if not isinstance(e, dict):
            continue
        coursework = ", ".join(str(c) for c in (e.get("coursework") or []))
        text = " ".join(str(x) for x in [
            e.get("degree", ""), e.get("school", ""), e.get("graduation", ""),
            f"Coursework: {coursework}" if coursework else "",
        ] if x)
        if text.strip():
            add(_unit("education", str(e.get("school") or "Education"), text,
                      f"education[{i}]" if not isinstance(edu, dict) else "education",
                      ended=str(e.get("graduation") or "") or None))

    # Declared skills are weaker evidence than a bullet describing work, but
    # they are still the candidate's own claim, and a JD requirement with no
    # project behind it should surface as "listed, not demonstrated" rather
    # than as a flat miss. Kind is what encodes that difference downstream.
    skills = resume.get("skills")
    if isinstance(skills, dict):
        for group, items in skills.items():
            listed = ", ".join(str(s) for s in (items or []))
            if listed:
                add(_unit("skill", str(group), f"{group}: {listed}",
                          f"skills.{group}"))
    elif isinstance(skills, list) and skills:
        add(_unit("skill", "Skills", ", ".join(str(s) for s in skills), "skills"))

    return tuple(units.values())


def profile_from_resume(resume: dict, **overrides: Any) -> CandidateProfile:
    """Build the constraint-checkable profile from resume.json + explicit
    overrides.

    Work authorization is the one field never guessed from resume text. A
    resume rarely states visa status, and inferring "needs sponsorship" from
    an international-sounding name or school would be both unreliable and
    discriminatory. Unset stays `None`/"unknown", and constraints.py treats
    unknown as a *risk to flag*, never as a pass or a fail.
    """
    edu = resume.get("education")
    edu = edu if isinstance(edu, dict) else (edu or [{}])[0] if edu else {}
    base: dict[str, Any] = {
        "name": str(resume.get("name") or ""),
        "location": str(resume.get("location") or ""),
        "graduation": str(edu.get("graduation") or "") or None,
        "degree_level": _degree_level(str(edu.get("degree") or "")),
    }
    base.update({k: v for k, v in overrides.items() if v is not None})
    known = {f for f in CandidateProfile.__dataclass_fields__}
    return CandidateProfile(**{k: v for k, v in base.items() if k in known})


def _degree_level(degree: str) -> str:
    d = degree.lower()
    if "ph" in d and "d" in d.split():
        return "phd"
    if "phd" in d or "doctor" in d:
        return "phd"
    if "master" in d or d.startswith("ms") or "m.s" in d or "meng" in d:
        return "masters"
    if "associate" in d:
        return "associates"
    return "bachelors"


def load_resume(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence_corpus(units: Iterable[EvidenceUnit]) -> str:
    """One blob of the candidate's own words, for embedding-based ranking."""
    return "\n".join(u.text for u in units)

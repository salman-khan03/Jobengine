"""Metric audit.

Scans resume bullets for quantified claims and flags the ones that will hurt in
an interview: unverifiable user counts, implausibly high accuracy figures, and
vague "improved X by N%" metrics with no defensible source.

The goal is not to delete numbers — quantified impact is good *when true*. The
goal is to make sure every number on the resume is one the candidate can defend
when an interviewer asks "how did you measure that?"
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_USERS = re.compile(r"(\d[\d,]*)\s*\+?\s*users", re.I)
_MULT = re.compile(r"\b(\d+(?:\.\d+)?)x\b", re.I)


@dataclass
class Flag:
    severity: str          # "high" | "medium" | "low"
    bullet: str
    issue: str
    suggestion: str


def _accuracy_context(text: str) -> bool:
    return bool(re.search(r"accuracy|prediction|precision|recall|f1", text, re.I))


def audit_bullet(text: str) -> list[Flag]:
    flags: list[Flag] = []

    # Implausibly high accuracy on a hard prediction task.
    for m in _PCT.finditer(text):
        val = float(m.group(1))
        if _accuracy_context(text) and val >= 70:
            flags.append(Flag(
                "high", text,
                f"{val:.0f}% accuracy on a prediction task is implausibly high "
                "and is the first thing an ML interviewer will challenge.",
                "Replace with the real metric from your evaluation harness "
                "(e.g. Brier score, log loss, or hit-rate vs. a baseline). "
                "A defensible 53% beats an indefensible 85%.",
            ))
        elif val >= 30:
            flags.append(Flag(
                "medium", text,
                f"\"{m.group(0)}\" improvement has no stated baseline or "
                "measurement method.",
                "Anchor it: state the before/after, the measurement, and the "
                "timeframe — or drop the number and describe the change.",
            ))

    # User-count claims on personal/portfolio projects.
    for m in _USERS.finditer(text):
        count = int(m.group(1).replace(",", ""))
        if count >= 100:
            flags.append(Flag(
                "high", text,
                f"\"{m.group(0)}\" is an unverifiable user count on a personal "
                "project; interviewers probe this and it rarely holds up.",
                "If there isn't real traffic you can show, reframe around what "
                "you built (the NLP pipeline, the plan generator) rather than a "
                "user number.",
            ))

    for m in _MULT.finditer(text):
        flags.append(Flag(
            "low", text,
            f"\"{m.group(0)}\" multiplier needs a baseline to be credible.",
            "State what it was measured against.",
        ))

    return flags


def audit_resume(resume: dict) -> list[Flag]:
    flags: list[Flag] = []
    for section in ("training", "experience", "projects"):
        for item in resume.get(section, []):
            for b in item.get("bullets", []):
                flags.extend(audit_bullet(b))
    return flags


_ACC_PHRASE = re.compile(r"~?\s*\d+(?:\.\d+)?%", re.I)


def scrub_bullet(text: str) -> str:
    """Soften a flagged bullet for a draft copy. Deleting the number outright
    leaves a broken sentence, so for high-severity accuracy claims we drop in an
    explicit rewrite marker instead — making it impossible to send by accident.
    Used only when --scrub is requested."""
    out = text
    if _accuracy_context(text):
        out = _ACC_PHRASE.sub("[INSERT REAL METRIC]", out, count=1)
    out = _USERS.sub(lambda m: "users"
                     if int(m.group(1).replace(",", "")) >= 100 else m.group(0), out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


def main() -> int:
    from . import config
    if not config.RESUME_PATH.exists():
        print(f"{config.RESUME_PATH} not found.")
        return 1
    resume = json.loads(config.RESUME_PATH.read_text())
    flags = audit_resume(resume)
    order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(flags, key=lambda x: order[x.severity]):
        print(f"[{f.severity.upper()}] {f.bullet[:70]}...")
        print(f"   issue: {f.issue}")
        print(f"   fix:   {f.suggestion}\n")
    if not flags:
        print("No flagged claims. Resume is clean.")
    return 1 if any(f.severity == "high" for f in flags) else 0


if __name__ == "__main__":
    raise SystemExit(main())

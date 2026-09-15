"""JD-aware keyword scoring used to rank resume content per role.

Deliberately transparent: keyword overlap you can print and defend, not an
embedding similarity you can't explain in an interview. jd_keywords() builds
the target vocabulary from the job title/category plus an optional pasted
job description; rank_* reorder existing resume content by overlap — nothing
is ever added or invented.
"""
from __future__ import annotations

import re
from collections import Counter

_WORD = re.compile(r"[a-z][a-z0-9+#.]{1,}")

# Words that appear in every JD and carry no signal.
_STOP = {
    "the", "and", "for", "with", "you", "our", "are", "will", "this", "that",
    "have", "has", "your", "who", "can", "not", "all", "any", "but", "into",
    "from", "their", "they", "them", "his", "her", "its", "was", "were",
    "been", "being", "more", "most", "other", "some", "such", "than", "then",
    "also", "each", "may", "must", "should", "would", "could", "about",
    "job", "role", "team", "work", "working", "candidate", "candidates",
    "experience", "years", "ability", "skills", "including", "required",
    "preferred", "qualifications", "responsibilities", "requirements",
    "opportunity", "position", "company", "employees", "benefits", "per",
    "etc", "well", "strong", "join", "help", "new", "using", "use",
}

# Multi-word tech terms worth catching as a unit before tokenizing.
_PHRASES = [
    "machine learning", "deep learning", "computer vision", "data science",
    "natural language", "ci cd", "unit testing", "rest api", "full stack",
    "distributed systems", "cloud computing",
]


def _tokens(text: str) -> list[str]:
    text = (text or "").lower()
    out = []
    for ph in _PHRASES:
        if ph in text:
            out.append(ph.replace(" ", "_"))
    out.extend(w for w in _WORD.findall(text) if w not in _STOP)
    return out


def jd_keywords(title: str, category: str, jd_text: str = "") -> Counter:
    """Weighted keyword vocabulary for the target role.

    Title/category words count triple — they're the strongest signal of what
    the role actually is; a long JD's boilerplate shouldn't drown them out.
    """
    kw: Counter = Counter()
    for w in _tokens(f"{title} {category}"):
        kw[w] += 3
    for w in _tokens(jd_text):
        kw[w] += 1
    return kw


def _item_text(item: dict) -> str:
    parts = [item.get("name", ""), " ".join(item.get("stack", []))]
    parts.extend(item.get("bullets", []))
    return " ".join(parts)


def score_item(item: dict, kw: Counter) -> int:
    """Sum of JD-keyword weights present in this resume item."""
    seen = set(_tokens(_item_text(item)))
    return sum(weight for word, weight in kw.items() if word in seen)


def rank_projects(resume: dict, kw: Counter) -> list[dict]:
    """Most role-relevant projects first; original order breaks ties so the
    output is stable when nothing matches (no JD pasted)."""
    projects = resume.get("projects", [])
    return sorted(projects, key=lambda p: -score_item(p, kw))


def rank_skills(skills: dict, kw: Counter) -> dict:
    """Within each skill group, JD-matched items float to the front.
    Groups themselves keep their order; nothing is dropped."""
    ranked = {}
    for group, items in skills.items():
        ranked[group] = sorted(
            items, key=lambda s: -kw.get(s.lower().replace(" ", "_"),
                                          kw.get(s.lower(), 0))
        )
    return ranked


def matched_strengths(resume: dict, kw: Counter) -> list[str]:
    """Short natural-language strengths for the cover letter, drawn from the
    top-scoring projects — text the candidate already wrote, reworded zero."""
    out = []
    for p in rank_projects(resume, kw)[:2]:
        stack = ", ".join(p.get("stack", [])[:3])
        out.append(f"I built {p['name']}" + (f" ({stack})" if stack else ""))
    return out

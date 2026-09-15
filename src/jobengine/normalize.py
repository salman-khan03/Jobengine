"""Company/title/URL normalization + the unified Job schema.

Both Simplify repos publish slightly different JSON; this module flattens
either shape into one Job dataclass and computes the normalized fields the
dedup and sponsor-index layers key on. Normalization rules live here and
nowhere else — build.py, sponsor_index.py, and the tests all import them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Legal/marketing suffixes that make "Google LLC" != "Google" if kept.
_SUFFIXES = re.compile(
    r"\b(incorporated|inc|llc|llp|ltd|limited|corp|corporation|company|co|"
    r"plc|gmbh|holdings|group|technologies|technology|labs)\b\.?",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_company(name: str) -> str:
    """'GOOGLE LLC' and 'Google' must collapse to the same key."""
    s = (name or "").lower().replace("&", " and ")
    s = _NON_ALNUM.sub(" ", s)
    s = _SUFFIXES.sub(" ", s)
    return _WS.sub(" ", s).strip()


def normalize_title(title: str) -> str:
    s = _NON_ALNUM.sub(" ", (title or "").lower())
    return _WS.sub(" ", s).strip()


def canonical_url(url: str) -> str:
    """Strip tracking params/fragments so the same posting from both repos
    (which append different ?utm_source= tags) dedups to one row."""
    if not url:
        return ""
    p = urlparse(url.strip())
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}"


@dataclass
class Job:
    id: str
    source_repo: str            # "intern" | "newgrad"
    company: str
    title: str
    category: str
    active: int
    is_visible: int
    terms: list[str]
    date_posted: int
    date_updated: int
    url: str
    locations: list[str]
    company_url: str
    sponsorship_simplify: str
    degrees: list[str]
    # derived
    company_norm: str = ""
    title_norm: str = ""
    url_canon: str = ""
    dedup_key: str = ""
    # filled in by SponsorIndex.annotate()
    sponsor_tier: str = "unknown"
    sponsor_lca_count: int = 0
    sponsor_match: str = ""

    def __post_init__(self) -> None:
        self.company_norm = normalize_company(self.company)
        self.title_norm = normalize_title(self.title)
        self.url_canon = canonical_url(self.url)
        self.dedup_key = f"{self.company_norm}|{self.title_norm}|{self.url_canon}"

    def to_row(self) -> dict:
        """Flatten for SQLite — list fields stored as JSON text."""
        return {
            "dedup_key": self.dedup_key,
            "id": self.id,
            "source_repo": self.source_repo,
            "company": self.company,
            "company_norm": self.company_norm,
            "title": self.title,
            "title_norm": self.title_norm,
            "category": self.category,
            "active": int(self.active),
            "is_visible": int(self.is_visible),
            "terms": json.dumps(self.terms),
            "date_posted": int(self.date_posted),
            "date_updated": int(self.date_updated),
            "url": self.url,
            "url_canon": self.url_canon,
            "locations": json.dumps(self.locations),
            "company_url": self.company_url,
            "sponsorship_simplify": self.sponsorship_simplify,
            "degrees": json.dumps(self.degrees),
            "sponsor_tier": self.sponsor_tier,
            "sponsor_lca_count": self.sponsor_lca_count,
            "sponsor_match": self.sponsor_match,
        }


def _from_record(rec: dict, source_repo: str) -> Job:
    # The two repos disagree on field names (terms vs seasons, etc.) —
    # .get() with defaults absorbs both shapes and future drift.
    return Job(
        id=str(rec.get("id", "")),
        source_repo=source_repo,
        company=rec.get("company_name", rec.get("company", "")),
        title=rec.get("title", ""),
        category=rec.get("category", ""),
        active=1 if rec.get("active", False) else 0,
        is_visible=1 if rec.get("is_visible", True) else 0,
        terms=list(rec.get("terms", rec.get("seasons", []) or [])),
        date_posted=int(rec.get("date_posted", 0) or 0),
        date_updated=int(rec.get("date_updated", 0) or 0),
        url=rec.get("url", ""),
        locations=list(rec.get("locations", []) or []),
        company_url=rec.get("company_url", ""),
        sponsorship_simplify=rec.get("sponsorship", ""),
        degrees=list(rec.get("degrees", []) or []),
    )


def load(intern_path: str, newgrad_path: str) -> list[Job]:
    """Parse both raw listing files into one unified list."""
    jobs: list[Job] = []
    for path, repo in ((intern_path, "intern"), (newgrad_path, "newgrad")):
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        jobs.extend(_from_record(r, repo) for r in records)
    return jobs

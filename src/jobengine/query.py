"""Query + export layer.

Examples:
  python query.py --summary
  python query.py --grad newgrad --tier offers,very_high,high --export shortlist.csv
  python query.py --grad intern --location TX,Remote --max 50
"""
from __future__ import annotations

import argparse
import csv
import json

from sqlalchemy import func, select

from . import db
from .logging_config import get_logger

log = get_logger(__name__)

# Categories relevant to a SWE / AI candidate.
SWE_CATS = (
    "Software", "Software Engineering", "AI/ML/Data",
    "Data Science, AI & Machine Learning",
)

# Tiers that mean "worth applying as an international candidate", best first.
SPONSOR_RANK = {
    "very_high": 0, "high": 1, "offers": 2, "medium": 3,
    "low": 4, "unknown": 5,
}
# Tiers to always exclude for someone who needs sponsorship.
EXCLUDE = {"does_not_sponsor", "citizen_only"}


def _require_db() -> None:
    if db.DATABASE_URL.startswith("sqlite") and not db.config.DB_PATH.exists():
        raise FileNotFoundError(
            f"{db.config.DB_PATH} not found. Run `jobengine fetch` then "
            "`jobengine build` first."
        )


def query(grad=None, tiers=None, location=None, max_rows=None,
          include_agencies=False, swe_only=True, company=None, skill=None):
    _require_db()
    j = db.jobs
    stmt = select(j).where(j.c.active == 1, j.c.is_visible == 1)
    if swe_only:
        stmt = stmt.where(j.c.category.in_(SWE_CATS))
    if grad:
        stmt = stmt.where(j.c.source_repo == grad)

    with db.ENGINE.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(stmt)]

    # Tier filter (default: drop the hard-no tiers).
    wanted = set(tiers) if tiers else None
    company_needle = company.strip().lower() if company else None
    skill_needle = skill.strip().lower() if skill else None
    out = []
    for r in rows:
        if r["sponsor_tier"] in EXCLUDE:
            continue
        if wanted and r["sponsor_tier"] not in wanted:
            continue
        if not include_agencies and "agency" in (r["sponsor_match"] or ""):
            continue
        if location:
            locs = " ".join(json.loads(r["locations"])).lower()
            if not any(tok.strip().lower() in locs for tok in location):
                continue
        if company_needle and company_needle not in (r["company_norm"] or "").lower():
            continue
        if skill_needle:
            # Substring/lexical match against title and the terms array, not
            # semantic search -- vector search over embeddings is a separate,
            # opt-in path (embeddings.py / `jobengine build --embed`). Same
            # honest limitation as everywhere else this pattern appears: a
            # search for "distributed systems" will not find "microservices".
            haystack = f"{r['title']} {r['terms']}".lower()
            if skill_needle not in haystack:
                continue
        out.append(r)

    out.sort(key=lambda r: (
        SPONSOR_RANK.get(r["sponsor_tier"], 9), -r["date_posted"]
    ))
    return out[:max_rows] if max_rows else out


def summary_dict() -> dict[str, int]:
    _require_db()
    j = db.jobs
    stmt = (
        select(j.c.sponsor_tier, func.count().label("c"))
        .where(j.c.active == 1, j.c.is_visible == 1, j.c.category.in_(SWE_CATS))
        .group_by(j.c.sponsor_tier)
        .order_by(func.count().desc())
    )
    with db.ENGINE.connect() as conn:
        rows = conn.execute(stmt).all()
    return {r.sponsor_tier: r.c for r in rows}


def summary() -> None:
    counts = summary_dict()
    print("Active SWE / AI-ML roles by sponsorship tier:")
    for tier, c in counts.items():
        print(f"  {tier:18} {c:>5}")


def export(rows, path):
    fields = ["company", "title", "source_repo", "category", "sponsor_tier",
              "sponsor_lca_count", "sponsor_match", "terms", "url"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {len(rows)} rows -> {path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--summary", action="store_true")
    p.add_argument("--grad", choices=["intern", "newgrad"])
    p.add_argument("--tier", help="comma list e.g. offers,very_high,high")
    p.add_argument("--location", help="comma list e.g. TX,Remote,CA")
    p.add_argument("--max", type=int)
    p.add_argument("--agencies", action="store_true", help="include staffing firms")
    p.add_argument("--export")
    a = p.parse_args()

    try:
        if a.summary:
            summary()
            return 0
        rows = query(
            grad=a.grad,
            tiers=a.tier.split(",") if a.tier else None,
            location=a.location.split(",") if a.location else None,
            max_rows=a.max,
            include_agencies=a.agencies,
        )
    except FileNotFoundError as exc:
        log.error(str(exc))
        return 1

    print(f"{len(rows)} matching roles")
    for r in rows[:20]:
        loc = ", ".join(json.loads(r["locations"])[:2]) or "n/a"
        print(f"  [{r['sponsor_tier']:9}] {r['company'][:24]:24} | "
              f"{r['title'][:42]:42} | {loc}")
    if a.export:
        export(rows, a.export)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

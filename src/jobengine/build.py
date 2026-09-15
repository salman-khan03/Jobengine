"""Dedup + persistence (SQLite or Postgres, via db.py) + pipeline build.

Run:  jobengine build   (or: python -m jobengine.build)
Produces a `jobs` table (one canonical row per real posting) in whichever
backend DATABASE_URL points at.
"""
from __future__ import annotations

from . import config, db, embeddings
from .normalize import load, Job
from .sponsor_index import SponsorIndex
from .logging_config import get_logger

log = get_logger(__name__)


class MissingDataError(RuntimeError):
    """Raised when the raw listings haven't been fetched yet."""


def dedup(jobs: list[Job]) -> list[Job]:
    """Collapse duplicates sharing a dedup_key (company|role|url).

    Keeps the most recently posted record, preferring active postings.
    """
    best: dict[str, Job] = {}
    for j in jobs:
        cur = best.get(j.dedup_key)
        if cur is None or (j.active, j.date_posted) > (cur.active, cur.date_posted):
            best[j.dedup_key] = j
    return list(best.values())


def _require_raw_data() -> None:
    missing = [p for p in (config.INTERN_RAW, config.NEWGRAD_RAW) if not p.exists()]
    if missing:
        names = ", ".join(str(p) for p in missing)
        raise MissingDataError(
            f"Missing raw listings: {names}. Run `jobengine fetch` first."
        )


def build(dol_csv: str | None = None, embed: bool = False) -> dict:
    _require_raw_data()
    raw_jobs = load(str(config.INTERN_RAW), str(config.NEWGRAD_RAW))
    raw_count = len(raw_jobs)
    if raw_count == 0:
        raise MissingDataError(
            "Raw listings parsed but contained zero records — the upstream "
            "JSON shape may have changed."
        )

    deduped = dedup(raw_jobs)
    log.info("Deduplicated %d raw records -> %d unique postings",
              raw_count, len(deduped))

    idx = SponsorIndex.from_seed()
    if dol_csv:
        n = idx.load_dol_csv(dol_csv)
        log.info("Loaded %d employers from DOL CSV: %s", n, dol_csv)
    for j in deduped:
        idx.annotate(j)

    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db.init_db()
    with db.ENGINE.begin() as conn:
        conn.execute(db.jobs.delete())
        conn.execute(db.jobs.insert(), [j.to_row() for j in deduped])

    embedded = 0
    if embed:
        active = [j for j in deduped if j.active and j.is_visible]
        rows = [(j.dedup_key, f"{j.title} {j.category} {j.company}") for j in active]
        embedded = embeddings.build_job_embeddings(rows)
        if embedded:
            log.info("Embedded %d active postings for vector search", embedded)

    return {
        "raw": raw_count,
        "deduped": len(deduped),
        "removed": raw_count - len(deduped),
        "embedded": embedded,
        "db_path": db.DATABASE_URL,
    }


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dol-csv", help="optional DOL LCA disclosure CSV for real sponsor counts")
    p.add_argument("--embed", action="store_true",
                   help="also build pgvector embeddings for active postings "
                        "(Postgres only; enables /api/jobs/semantic-search)")
    args = p.parse_args()

    try:
        stats = build(dol_csv=args.dol_csv, embed=args.embed)
    except MissingDataError as exc:
        log.error(str(exc))
        return 1

    log.info("Raw records:        %s", f"{stats['raw']:,}")
    log.info("After dedup:        %s", f"{stats['deduped']:,}")
    log.info("Duplicates removed: %s", f"{stats['removed']:,}")
    if args.embed:
        log.info("Embedded:           %s", f"{stats['embedded']:,}")
    log.info("Wrote %s", stats["db_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

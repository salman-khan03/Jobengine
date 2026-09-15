"""Tailoring engine.

Base resume in (resume.json), per-job tailored resume + cover letter out.
Selection/reordering only — every line traces back to real resume content.
The metric audit runs on every job and is surfaced, not hidden.

Examples:
  # tailor for a specific role from the DB (by company + keyword in title)
  python tailor.py --company Amazon --match "software engineer" --grad newgrad

  # tailor against a pasted job description for sharper matching
  python tailor.py --company Stripe --title "Backend Engineer" --jd-file jd.txt

  # soften indefensible metrics in the tailored copy
  python tailor.py --company Meta --match "data engineer" --scrub
"""
from __future__ import annotations

import argparse
import json
import re

from sqlalchemy import func, select

from . import config, db
from . import match
from . import semantic_match
from . import metrics_audit as audit
from . import llm
from .logging_config import get_logger

log = get_logger(__name__)
OUTDIR = config.OUT_DIR


def find_job(company=None, match_title=None, grad=None):
    j = db.jobs
    stmt = select(j).where(j.c.active == 1, j.c.is_visible == 1)
    if company:
        stmt = stmt.where(j.c.company_norm.like(f"%{company.lower()}%"))
    if match_title:
        stmt = stmt.where(func.lower(j.c.title).like(f"%{match_title.lower()}%"))
    if grad:
        stmt = stmt.where(j.c.source_repo == grad)
    stmt = stmt.order_by(j.c.date_posted.desc()).limit(1)
    with db.ENGINE.connect() as conn:
        row = conn.execute(stmt).first()
    return dict(row._mapping) if row else None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:50]


def render_resume(resume, ranked_projects, ranked_skills, scrub=False):
    r = resume
    L = []
    L.append(f"# {r['name']}")
    L.append(f"{r['location']} • {r['email']} • {r['linkedin']} • {r['github']}\n")

    e = r["education"]
    L.append("## Education")
    L.append(f"**{e['school']}**, {e['location']} — {e['degree']} ({e['graduation']})")
    L.append(f"GPA: {e['gpa']}")
    L.append(f"*Relevant coursework:* {', '.join(e['coursework'])}\n")

    L.append("## Technical Skills")
    for group, items in ranked_skills.items():
        L.append(f"- **{group}:** {', '.join(items)}")
    L.append("")

    L.append("## Projects")
    for p in ranked_projects:
        L.append(f"**{p['name']}** — {', '.join(p['stack'])}  ({p['dates']})")
        for b in p["bullets"]:
            L.append(f"- {audit.scrub_bullet(b) if scrub else b}")
        L.append("")

    if r.get("experience"):
        L.append("## Experience")
        for x in r["experience"]:
            L.append(f"**{x['title']}**, {x['org']} — {x['location']} ({x['dates']})")
            for b in x["bullets"]:
                L.append(f"- {audit.scrub_bullet(b) if scrub else b}")
            L.append("")

    if r.get("training"):
        L.append("## AI & Specialized Training")
        for t in r["training"]:
            L.append(f"**{t['title']}** — {t['location']} ({t['dates']})")
            for b in t["bullets"]:
                L.append(f"- {b}")
            L.append("")
    return "\n".join(L)


def render_cover_letter(resume, job, strengths):
    company = job["company"]
    title = job["title"]
    s = strengths + ["", "", ""]
    draft = f"""Dear {company} Hiring Team,

I'm applying for the {title} role. I'm a Computer Science student at North
American University (graduating May 2027) who builds and ships full-stack and
AI systems end to end, and {company}'s work is exactly the kind of problem I
want to work on.

Two things from my background map directly to this role. First, {s[0]} — where I
owned the system from backend to frontend. Second, {s[1]}, which sharpened the
engineering judgment this role calls for. I work primarily in Python and
TypeScript across React, FastAPI/Node, and AWS, and I'm comfortable taking a
feature from design through deployment.

I'd welcome the chance to discuss how I can contribute to your team.

Best regards,
{resume['name']}
{resume['email']} • {resume['github']}"""
    system = ("You are an expert technical resume editor. Keep it truthful, "
              "concrete, and under 200 words. Never add facts or numbers.")
    return llm.polish(draft, job, system)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--company")
    p.add_argument("--match", dest="match_title", help="keyword in job title")
    p.add_argument("--title", help="override role title (manual mode)")
    p.add_argument("--category", default="Software")
    p.add_argument("--grad", choices=["intern", "newgrad"])
    p.add_argument("--jd-file", help="path to pasted job description text")
    p.add_argument("--scrub", action="store_true",
                   help="soften indefensible metrics in the tailored copy")
    p.add_argument("--semantic", action="store_true",
                   help="also rank projects by TF-IDF cosine similarity to the "
                        "role, shown alongside (never replacing) the keyword "
                        "ranking used for the actual output order")
    a = p.parse_args()

    if not config.RESUME_PATH.exists():
        log.error("%s not found. Set JOBENGINE_RESUME or place resume.json "
                  "in the working directory.", config.RESUME_PATH)
        return 1
    resume = json.loads(config.RESUME_PATH.read_text())

    job = find_job(a.company, a.match_title, a.grad)
    if job is None:
        if not (a.company and a.title):
            log.error("No DB match for that company/role, and no --title given "
                      "for manual mode. Run `jobengine build` first, or pass "
                      "--company and --title to tailor against a role not in "
                      "the DB.")
            return 1
        job = {"company": a.company, "title": a.title, "category": a.category,
               "url": "", "sponsor_tier": "unknown"}

    jd_text = ""
    if a.jd_file:
        try:
            jd_text = open(a.jd_file).read()
        except OSError as exc:
            log.error("Could not read --jd-file %s: %s", a.jd_file, exc)
            return 1

    kw = match.jd_keywords(job["title"], job.get("category", ""), jd_text)
    ranked_projects = match.rank_projects(resume, kw)
    ranked_skills = match.rank_skills(resume["skills"], kw)
    strengths = match.matched_strengths(resume, kw)

    flags = audit.audit_resume(resume)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    base = f"{slug(job['company'])}__{slug(job['title'])}"
    resume_md = render_resume(resume, ranked_projects, ranked_skills, scrub=a.scrub)
    cover_md = render_cover_letter(resume, job, strengths)
    (OUTDIR / f"{base}__resume.md").write_text(resume_md)
    (OUTDIR / f"{base}__cover.md").write_text(cover_md)

    # --- report ---
    print(f"Target: {job['company']} — {job['title']}")
    print(f"Sponsorship tier: {job.get('sponsor_tier','n/a')}")
    if job.get("url"):
        print(f"Apply: {job['url']}")
    print("\nProject order (most relevant first, by keyword overlap):")
    for pr in ranked_projects:
        print(f"  - {pr['name']}  (score {match.score_item(pr, kw)})")

    if a.semantic:
        semantic_ranked = semantic_match.rank_projects_semantic(
            resume, job["title"], job.get("category", ""), jd_text)
        print("\nOpt-in: TF-IDF cosine-similarity ranking (not embeddings — "
              "classical IR, shown for comparison only):")
        for pr, score in semantic_ranked:
            print(f"  - {pr['name']}  (cosine {score:.3f})")

    print(f"\nWrote {OUTDIR}/{base}__resume.md and __cover.md")

    high = [f for f in flags if f.severity == "high"]
    if high:
        print(f"\n  METRIC AUDIT — {len(high)} high-severity claim(s) to fix "
              f"{'(scrubbed in this copy)' if a.scrub else 'BEFORE sending'}:")
        for f in high:
            print(f"   • {f.bullet[:64]}...")
            print(f"     {f.suggestion}")
    if not a.scrub and high:
        print("\n  Re-run with --scrub to soften these automatically, or fix in "
              "resume.json once so every future tailor is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

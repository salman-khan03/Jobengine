"""Seed a demo account so a first-time visitor sees a working product.

A live demo that opens on an empty tracker teaches the visitor nothing about
the product. This creates one deterministic demo user whose applications span
every pipeline stage — including the unglamorous ones (rejections, a stalled
OA) — because a tracker showing only offers is obviously fake.

Deterministic by design: same email, same password, same rows every time, so
the demo credentials in the README never go stale and re-running is safe
(existing demo data is replaced, never duplicated).

    jobengine seed-demo
    jobengine seed-demo --reset     # wipe and recreate

Security note: the demo account is a real account with a *published* password.
It is scoped like any other user (it can only ever see its own applications),
and `--reset` is the intended way to clean up whatever visitors do to it. Do
not seed it into an environment where a normal user's data lives.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from . import auth, db, tracker
from .logging_config import get_logger

log = get_logger(__name__)

DEMO_EMAIL = "demo@jobengine.app"
DEMO_PASSWORD = "demo-account-2026"


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


# (company, title, source, status, days_ago, notes)
# A deliberately realistic funnel: 12 applications, 1 offer, 4 rejections.
# The shape matters — an international student's real conversion rate is the
# story this project exists to improve, so inflating it here would undercut
# the whole premise.
_DEMO_APPLICATIONS = [
    ("Stripe", "Backend Engineer, New Grad", "simplify", "offer", 41,
     "Onsite went well — systems design round on idempotent payment retries."),
    ("Datadog", "Software Engineer I", "simplify", "interview", 18,
     "Final round scheduled. Strong H-1B history (tier: strong)."),
    ("Ramp", "Software Engineer, New Grad", "referral", "interview", 22,
     "Referred by classmate. Recruiter call done."),
    ("Cloudflare", "Systems Engineer, New Grad", "simplify", "oa", 9,
     "HackerRank sent, 90 min, expires in 5 days."),
    ("Snowflake", "Software Engineer, University Grad", "company_site", "oa", 12,
     "OA stalled — no follow-up after submission."),
    ("Databricks", "Software Engineer, New Grad", "simplify", "heard_back", 6,
     "Recruiter reached out after application."),
    ("Palantir", "Software Engineer, New Grad", "linkedin", "applied", 4, ""),
    ("Rippling", "Backend Engineer, New Grad", "simplify", "applied", 3, ""),
    ("Plaid", "Software Engineer, New Grad", "simplify", "applied", 2, ""),
    ("Airbnb", "Software Engineer, University Grad", "simplify", "rejected", 30,
     "Rejected at resume screen."),
    ("Netflix", "Software Engineer L4", "company_site", "rejected", 35,
     "No sponsorship for new grads this cycle."),
    ("Robinhood", "Software Engineer, New Grad", "linkedin", "rejected", 27,
     "Rejected after OA."),
    ("Figma", "Software Engineer, New Grad", "simplify", "rejected", 20,
     "Role closed before review."),
    ("Anduril", "Software Engineer, New Grad", "simplify", "withdrawn", 25,
     "Withdrew — role requires US citizenship (ITAR)."),
    ("Notion", "Software Engineer, New Grad", "simplify", "saved", 1,
     "Saved — applications open next week."),
]


def seed(reset: bool = False) -> int:
    """Create/refresh the demo user and its applications. Returns the user id."""
    db.init_db()

    try:
        user = auth.register(DEMO_EMAIL, DEMO_PASSWORD)
        log.info("created demo user %s", DEMO_EMAIL)
    except auth.AuthError:
        # Already exists — the common case on redeploy.
        user = auth.login(DEMO_EMAIL, DEMO_PASSWORD)
        log.info("demo user %s already exists", DEMO_EMAIL)

    existing = tracker.list_applications(user_id=user.user_id)
    if existing and not reset:
        log.info("demo account already has %d applications; pass --reset to rebuild",
                 len(existing))
        return user.user_id

    if existing:
        # status_events cascade via the FK; see db.py.
        with db.get_engine().begin() as conn:
            conn.execute(
                db.applications.delete().where(db.applications.c.user_id == user.user_id)
            )
        log.info("cleared %d existing demo applications", len(existing))

    for company, title, source, status, days, notes in _DEMO_APPLICATIONS:
        # "saved" precedes "applied" in the funnel, so it is the *start* state,
        # not something you transition into. Creating those rows directly
        # avoids a spurious backwards-transition warning from tracker.py.
        start = "saved" if status == "saved" else "applied"
        app_id = tracker.add(
            tracker.Application(
                company=company, title=title, source=source,
                status=start, notes=notes,
                applied_date=_days_ago(days),
            ),
            user_id=user.user_id,
        )
        # Move it to its real status through the normal transition path rather
        # than inserting the end state directly — this populates status_events
        # so the demo history view has something truthful in it.
        if status != start:
            tracker.update_status(app_id, status, note="demo seed",
                                  user_id=user.user_id)

    log.info("seeded %d demo applications for %s", len(_DEMO_APPLICATIONS), DEMO_EMAIL)
    return user.user_id


def main() -> int:
    p = argparse.ArgumentParser(description="Seed the public demo account.")
    p.add_argument("--reset", action="store_true",
                   help="wipe the demo account's applications and recreate them")
    args = p.parse_args()

    seed(reset=args.reset)
    print(f"Demo account ready:\n  email:    {DEMO_EMAIL}\n  password: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

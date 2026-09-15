"""RoleRadar CLI.

    roleradar profile set --resume resume.json --needs-sponsorship
    roleradar decide --company Stripe --match "backend" --jd-file jd.txt --llm
    roleradar rank --grad newgrad --limit 20 --save
    roleradar outcome add --job-key <key> --stage interview
    roleradar evaluate

The CLI is the single-user surface and stays unauthenticated, exactly like
JobEngine's `track` command -- rows it writes carry `user_id = NULL` and are
therefore invisible to the multi-user HTTP API. Same table, two access
surfaces, no migration drama (see jobengine/db.py for the original note).

`decide` defaults to using an LLM when a key is present; `rank` never does.
That asymmetry is the cost model made visible: explaining one role you asked
about is worth an API call, explaining 200 you have not looked at is not.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from sqlalchemy import func, select

from jobengine import config, db
from jobengine.logging_config import get_logger

from . import decision as decision_mod, evidence as ev, outcomes, store
from .models import CandidateProfile, Decision

log = get_logger(__name__)

_VERDICT_MARK = {"apply": "APPLY", "stretch": "STRETCH", "skip": "SKIP",
                 "blocked": "BLOCKED"}


def _load_resume(path: str | None) -> dict:
    p = path or config.RESUME_PATH
    try:
        return ev.load_resume(p)
    except OSError:
        log.error("Could not read resume at %s. Pass --resume or set "
                  "JOBENGINE_RESUME.", p)
        raise SystemExit(1)


def _profile(args, resume: dict) -> CandidateProfile:
    """Saved profile if there is one, overlaid with any flags given now.

    Flags win over the stored profile so a one-off `--no-sponsorship` run
    does not require editing the saved profile and then editing it back.
    """
    stored = store.load_profile()
    base = stored[0] if stored else ev.profile_from_resume(resume)
    overrides = {}
    if getattr(args, "needs_sponsorship", None) is not None:
        overrides["needs_sponsorship"] = args.needs_sponsorship
    if getattr(args, "graduation", None):
        overrides["graduation"] = args.graduation
    if getattr(args, "location", None):
        overrides["location"] = args.location
    if not overrides:
        return base
    return CandidateProfile(**{**base.as_dict(), **overrides})


def _find_jobs(company: str | None, match_title: str | None, grad: str | None,
               tier: str | None, limit: int) -> list[dict]:
    j = db.jobs
    stmt = select(j).where(j.c.active == 1, j.c.is_visible == 1)
    if company:
        stmt = stmt.where(j.c.company_norm.like(f"%{company.lower()}%"))
    if match_title:
        stmt = stmt.where(func.lower(j.c.title).like(f"%{match_title.lower()}%"))
    if grad:
        stmt = stmt.where(j.c.source_repo == grad)
    if tier:
        stmt = stmt.where(j.c.sponsor_tier.in_([t.strip() for t in tier.split(",")]))
    stmt = stmt.order_by(j.c.date_posted.desc()).limit(limit)
    with db.get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]


def _print_decision(d: Decision, verbose: bool = True) -> None:
    print(f"\n{_VERDICT_MARK.get(d.verdict, d.verdict.upper())}  "
          f"{d.score * 100:.0f}/100  (confidence {d.confidence:.2f})  "
          f"{d.company} - {d.title}")
    if not verbose:
        return
    b = d.breakdown
    print(f"  required {b.required_coverage:.2f} | preferred {b.preferred_coverage:.2f} "
          f"| semantic {b.semantic_similarity:.2f} | seniority {b.seniority_fit:.2f} "
          f"| risk -{b.risk_penalty:.2f}")
    print()
    for line in d.explanation.splitlines():
        print(f"  {line}")
    if d.explanation_source == "llm":
        print("\n  (explanation written by an LLM, every claim validated against "
              "cited resume evidence)")


# --- subcommands ------------------------------------------------------------

def cmd_profile(args) -> int:
    store.init()
    if args.action == "show":
        stored = store.load_profile()
        if not stored:
            print("No profile saved. Run: roleradar profile set --resume resume.json")
            return 1
        print(json.dumps(stored[0].as_dict(), indent=2))
        return 0

    resume = _load_resume(args.resume)
    profile = ev.profile_from_resume(
        resume,
        needs_sponsorship=args.needs_sponsorship,
        graduation=args.graduation,
        location=args.location,
        us_citizen=args.us_citizen,
        open_to_relocate=args.open_to_relocate,
        seniority=args.seniority,
    )
    store.save_profile(profile, resume=resume)
    units = ev.extract_evidence(resume)
    print(json.dumps(profile.as_dict(), indent=2))
    print(f"\nSaved. Extracted {len(units)} citable evidence units from "
          f"{args.resume or config.RESUME_PATH}.")
    if profile.needs_sponsorship is None:
        print("\nNote: work authorization is unset, so sponsorship blockers will "
              "be reported as warnings rather than decided. Pass "
              "--needs-sponsorship / --no-needs-sponsorship to resolve them.")
    return 0


def cmd_decide(args) -> int:
    store.init()
    resume = _load_resume(args.resume)
    units = ev.extract_evidence(resume)
    profile = _profile(args, resume)

    jobs = _find_jobs(args.company, args.match_title, args.grad, None, 1)
    if not jobs:
        if not (args.company and args.title):
            log.error("No job matched. Run `jobengine build` first, or pass "
                      "--company and --title to score a role not in the DB.")
            return 1
        jobs = [{"dedup_key": f"manual:{args.company}:{args.title}",
                 "title": args.title, "company": args.company,
                 "sponsor_tier": "unknown", "locations": args.job_location or ""}]

    jd_text = ""
    if args.jd_file:
        try:
            jd_text = open(args.jd_file, encoding="utf-8").read()
        except OSError as exc:
            log.error("Could not read --jd-file %s: %s", args.jd_file, exc)
            return 1
    elif not sys.stdin.isatty() and not sys.stdin.closed:
        # Allows `cat jd.txt | roleradar decide ...`, the shape most people
        # reach for when copying a description out of a browser.
        jd_text = sys.stdin.read()

    d = decision_mod.decide(jobs[0], profile, units, jd_text=jd_text, use_llm=args.llm)
    _print_decision(d)
    if not jd_text:
        print("\n  No job description supplied, so this is scored from the title "
              "and listing metadata only. Pipe one in for a real answer.")
    if args.save:
        store.save_decision(d)
        print(f"\n  Saved prediction for job_key={d.job_key}")
    if args.json:
        print(json.dumps(d.as_dict(), indent=2))
    return 0


def cmd_rank(args) -> int:
    store.init()
    resume = _load_resume(args.resume)
    profile = _profile(args, resume)
    jobs = _find_jobs(args.company, args.match_title, args.grad, args.tier,
                      args.scan)
    if not jobs:
        log.error("No jobs matched those filters. Run `jobengine build` first.")
        return 1

    decisions = decision_mod.decide_many(jobs, resume, profile, use_llm=False,
                                         top_k=args.limit)
    print(f"Scored {len(jobs)} postings for {profile.name or 'you'}; "
          f"showing top {len(decisions)}.\n")
    print(f"{'VERDICT':<8} {'SCORE':>5}  {'REQ':>4}  COMPANY / TITLE")
    for d in decisions:
        print(f"{_VERDICT_MARK.get(d.verdict, ''):<8} "
              f"{d.score * 100:>4.0f}  {d.breakdown.required_coverage:>4.2f}  "
              f"{d.company} - {d.title[:56]}")
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.verdict] = counts.get(d.verdict, 0) + 1
    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if args.save:
        n = store.save_decisions(decisions)
        print(f"Saved {n} predictions. Log outcomes with `roleradar outcome add`.")
    return 0


def cmd_outcome(args) -> int:
    store.init()
    if args.action == "add":
        if args.stage not in outcomes.FUNNEL + outcomes.TERMINAL:
            log.error("Unknown stage %r. Valid: %s", args.stage,
                      ", ".join(sorted(set(outcomes.FUNNEL + outcomes.TERMINAL))))
            return 1
        app_id = store.record_outcome(args.job_key, args.stage, note=args.note or "")
        linked = store.latest_decision(args.job_key)
        print(f"Logged {args.stage} for {args.job_key} (application_id={app_id}).")
        if linked:
            print(f"  Linked to prediction {linked['score'] * 100:.0f}/100 "
                  f"({linked['verdict']}) made {linked['created_at']}.")
        else:
            print("  No stored prediction for this job, so it will count in the "
                  "funnel but not in ranking metrics.")
        return 0
    counts = store.funnel_counts()
    if not counts:
        print("No outcomes logged yet.")
        return 0
    print("Current application status (each job counted once):")
    for stage in outcomes.FUNNEL + tuple(
            s for s in outcomes.TERMINAL if s not in outcomes.FUNNEL):
        if counts.get(stage):
            print(f"  {stage:<14} {counts[stage]}")
    return 0


def cmd_evaluate(args) -> int:
    store.init()
    pairs = store.scored_outcomes()
    report = outcomes.evaluate(pairs, min_sample=args.min_sample)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print(f"Ranking evaluation over {report.n} scored applications")
    print(f"  {report.note}")
    if report.underpowered:
        return 0
    print(f"  NDCG@5  {report.ndcg_at_5:.3f}      NDCG@10 {report.ndcg_at_10:.3f}")
    print(f"  P@5     {report.precision_at_5:.3f}      P@10    {report.precision_at_10:.3f}")
    print(f"  Lift@5  {report.lift_at_5:.2f}x     Lift@10 {report.lift_at_10:.2f}x")
    print(f"  Spearman {report.spearman:.3f}")
    print("  Match scores are not probabilities; Brier score is withheld.")
    print("\n  Observed progression by match-score bucket:")
    for b in report.calibration:
        print(f"    {b['bin']}  n={b['n']:<4} predicted~{b['predicted_mid']:.2f} "
              f"observed {b['observed_rate']:.2f}")
    if report.lift_at_10 and report.lift_at_10 <= 1.0:
        print("\n  Lift at or below 1.0: the ranking is not yet beating random "
              "order on your data. That is a real result, not a bug.")
    return 0


# --- wiring -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="roleradar", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--resume", help="path to resume.json")
        sp.add_argument("--graduation", help='e.g. "May 2027"')
        sp.add_argument("--location", help="your location")
        sp.add_argument("--needs-sponsorship", dest="needs_sponsorship",
                        action="store_true", default=None)
        sp.add_argument("--no-needs-sponsorship", dest="needs_sponsorship",
                        action="store_false")

    pp = sub.add_parser("profile", help="save or show your candidate profile")
    pp.add_argument("action", choices=["set", "show"])
    add_common(pp)
    pp.add_argument("--us-citizen", dest="us_citizen", action="store_true", default=None)
    pp.add_argument("--no-relocate", dest="open_to_relocate", action="store_false",
                    default=None)
    pp.add_argument("--seniority", default=None,
                    choices=["student", "junior", "mid", "senior", "staff"])
    pp.set_defaults(func=cmd_profile)

    dp = sub.add_parser("decide", help="should I apply to this one role?")
    add_common(dp)
    dp.add_argument("--company")
    dp.add_argument("--match", dest="match_title", help="keyword in job title")
    dp.add_argument("--title", help="role title (manual mode)")
    dp.add_argument("--grad", choices=["intern", "newgrad"])
    dp.add_argument("--jd-file", help="job description text file (or pipe on stdin)")
    dp.add_argument("--job-location", help="role location (manual mode)")
    dp.add_argument("--llm", action="store_true",
                    help="let an LLM write the explanation (claims are still "
                         "validated against cited evidence)")
    dp.add_argument("--save", action="store_true", help="store the prediction")
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_decide)

    rp = sub.add_parser("rank", help="rank many postings for you")
    add_common(rp)
    rp.add_argument("--company")
    rp.add_argument("--match", dest="match_title")
    rp.add_argument("--grad", choices=["intern", "newgrad"])
    rp.add_argument("--tier", help="comma-separated sponsor tiers")
    rp.add_argument("--scan", type=int, default=300, help="postings to score")
    rp.add_argument("--limit", type=int, default=20, help="rows to show")
    rp.add_argument("--save", action="store_true")
    rp.set_defaults(func=cmd_rank)

    op = sub.add_parser("outcome", help="log what actually happened")
    op.add_argument("action", choices=["add", "funnel"])
    op.add_argument("--job-key")
    op.add_argument("--stage", help=", ".join(
        sorted(set(outcomes.FUNNEL + outcomes.TERMINAL))))
    op.add_argument("--note")
    op.set_defaults(func=cmd_outcome)

    ep = sub.add_parser("evaluate", help="did the ranking predict outcomes?")
    ep.add_argument("--min-sample", type=int, default=outcomes.MIN_SAMPLE)
    ep.add_argument("--json", action="store_true")
    ep.set_defaults(func=cmd_evaluate)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "outcome" and args.action == "add" and not (
            args.job_key and args.stage):
        print("outcome add requires --job-key and --stage")
        return 1
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

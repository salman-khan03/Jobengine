"""CLI for the application tracker.

Examples:
  jobengine track add --company Stripe --title "Backend Engineer" --source linkedin
  jobengine track add --company Amazon --title "SDE Intern" --source simplify --dedup-key amazon|sde_intern|https://...
  jobengine track list
  jobengine track list --status interview
  jobengine track status 3 oa --note "got the HackerRank link"
  jobengine track edit 3 --notes "recruiter is Jane, follow up Friday"
  jobengine track delete 3
  jobengine track history 3
  jobengine track summary
  jobengine track parse-email --file email.txt
"""
from __future__ import annotations

import argparse
import sys

from . import tracker
from .logging_config import get_logger

log = get_logger(__name__)


def _cmd_add(a) -> int:
    app = tracker.Application(
        company=a.company, title=a.title, source=a.source,
        dedup_key=a.dedup_key, status=a.status, url=a.url or "",
        notes=a.notes or "", contact_email=a.contact_email or "",
    )
    app_id = tracker.add(app)
    print(f"Added application #{app_id}")
    return 0


def _cmd_list(a) -> int:
    rows = tracker.list_applications(status=a.status)
    if not rows:
        print("No applications tracked yet.")
        return 0
    for r in rows:
        print(f"  #{r['app_id']:<4} [{r['status']:11}] {r['company'][:22]:22} | "
              f"{r['title'][:38]:38} | {r['source']:12} | updated {r['last_update'][:10]}")
    print(f"\n{len(rows)} applications")
    return 0


def _cmd_status(a) -> int:
    try:
        tracker.update_status(a.app_id, a.new_status, note=a.note or "")
    except (KeyError, ValueError) as exc:
        log.error(str(exc))
        return 1
    print(f"Application #{a.app_id} -> {a.new_status}")
    return 0


def _cmd_edit(a) -> int:
    fields = {}
    for f in ("company", "title", "url", "notes", "contact_email", "source", "dedup_key"):
        v = getattr(a, f)
        if v is not None:
            fields[f] = v
    if not fields:
        log.error("No fields given to edit. Use --company/--title/--url/--notes/"
                  "--contact-email/--source/--dedup-key.")
        return 1
    try:
        tracker.edit(a.app_id, **fields)
    except (KeyError, ValueError) as exc:
        log.error(str(exc))
        return 1
    print(f"Application #{a.app_id} updated: {', '.join(fields)}")
    return 0


def _cmd_delete(a) -> int:
    try:
        tracker.delete(a.app_id)
    except KeyError as exc:
        log.error(str(exc))
        return 1
    print(f"Deleted application #{a.app_id}")
    return 0


def _cmd_history(a) -> int:
    events = tracker.history(a.app_id)
    if not events:
        print(f"No history for application #{a.app_id} (or it doesn't exist).")
        return 0
    for e in events:
        note = f" — {e['note']}" if e["note"] else ""
        print(f"  {e['occurred_at'][:19]}  {e['status']:11}{note}")
    return 0


def _cmd_summary(a) -> int:
    counts = tracker.summary()
    if not counts:
        print("No applications tracked yet.")
        return 0
    order = ["saved", "applied", "heard_back", "oa", "interview", "offer",
             "rejected", "withdrawn"]
    for s in order:
        if s in counts:
            print(f"  {s:12} {counts[s]:>4}")
    return 0


def _cmd_parse_email(a) -> int:
    if a.file:
        text = open(a.file).read()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        log.error("Provide --file or pipe email text via stdin.")
        return 1
    result = tracker.parse_email_signal(text)
    if result["status"] is None:
        print("No clear status signal detected. Defaulting to manual review.")
        return 0
    print(f"Detected signal: {result['status']}  "
          f"(matched: \"{result['matched_phrase']}\", confidence: {result['confidence']:.1f})")
    if a.app_id:
        tracker.update_status(a.app_id, result["status"],
                              note=f"auto-detected from email: \"{result['matched_phrase']}\"")
        print(f"Applied to application #{a.app_id}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="jobengine track", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("add")
    sp.add_argument("--company", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--source", required=True, choices=sorted(tracker.SOURCES))
    sp.add_argument("--status", default=tracker.Status.APPLIED.value,
                     choices=[s.value for s in tracker.Status])
    sp.add_argument("--dedup-key", dest="dedup_key",
                     help="link to a jobs row (from `jobengine query`) for full provenance")
    sp.add_argument("--url")
    sp.add_argument("--notes")
    sp.add_argument("--contact-email")
    sp.set_defaults(func=_cmd_add)

    sp = sub.add_parser("list")
    sp.add_argument("--status", choices=[s.value for s in tracker.Status])
    sp.set_defaults(func=_cmd_list)

    sp = sub.add_parser("status")
    sp.add_argument("app_id", type=int)
    sp.add_argument("new_status", choices=[s.value for s in tracker.Status])
    sp.add_argument("--note")
    sp.set_defaults(func=_cmd_status)

    sp = sub.add_parser("edit")
    sp.add_argument("app_id", type=int)
    sp.add_argument("--company")
    sp.add_argument("--title")
    sp.add_argument("--url")
    sp.add_argument("--notes")
    sp.add_argument("--contact-email")
    sp.add_argument("--source", choices=sorted(tracker.SOURCES))
    sp.add_argument("--dedup-key", dest="dedup_key")
    sp.set_defaults(func=_cmd_edit)

    sp = sub.add_parser("delete")
    sp.add_argument("app_id", type=int)
    sp.set_defaults(func=_cmd_delete)

    sp = sub.add_parser("history")
    sp.add_argument("app_id", type=int)
    sp.set_defaults(func=_cmd_history)

    sp = sub.add_parser("summary")
    sp.set_defaults(func=_cmd_summary)

    sp = sub.add_parser("parse-email")
    sp.add_argument("--file")
    sp.add_argument("--app-id", dest="app_id", type=int,
                     help="if given, apply the detected status to this application")
    sp.set_defaults(func=_cmd_parse_email)

    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())

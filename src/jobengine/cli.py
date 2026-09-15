"""Unified CLI entrypoint.

Usage:
  jobengine fetch
  jobengine build [--dol-csv PATH]
  jobengine query --summary
  jobengine query --grad newgrad --tier offers,very_high,high --export out.csv
  jobengine tailor --company Amazon --match "software engineer" --grad newgrad
  jobengine audit
  jobengine track add --company Stripe --title "Backend Engineer" --source linkedin
  jobengine track list / status / edit / delete / history / summary / parse-email
  jobengine serve [--port 8765]    # typed HTTP API for frontend integration
  jobengine seed-demo [--reset]    # create the public demo account + sample data
  jobengine radar decide --company Stripe --jd-file jd.txt   # RoleRadar V2

Each subcommand delegates to its module's own argparse-based main(), so
`python -m jobengine.query ...` keeps working unchanged for anyone scripting
against the individual modules.
"""
from __future__ import annotations

import os
import sys
from typing import Callable

# Must run before any of this module's own submodule imports below, not
# inside main(): several modules read secrets from os.environ at IMPORT
# time (auth.py's SECRET_KEY is the concrete example — it is read once,
# module-level, the moment `api` is imported by this file's own import
# line). Loading .env after that point would silently be too late for
# those reads, even though DATABASE_URL and the LLM provider keys (read
# lazily, at call time, not import time) would still pick it up fine —
# the inconsistency between "some vars work late, some don't" is worse
# than just always loading first.
#
# Guarded against pytest on purpose: no test imports this module today,
# but a future one easily could, and cli.py loading real secrets from a
# developer's .env into a test process is exactly how a test accidentally
# talks to a live database instead of the isolated one its fixtures set
# up — a mistake that would not be undone by "the test uses config.DB_PATH",
# since db.py checks the DATABASE_URL env var first regardless of that.
if "PYTEST_CURRENT_TEST" not in os.environ:
    from dotenv import load_dotenv

    load_dotenv()

from . import build, fetch, query, tailor, metrics_audit, track_cli, api, seed_demo, evaluation


def _radar() -> int:
    """Delegate to the RoleRadar CLI (`jobengine radar decide ...`)."""
    from roleradar.cli import main as radar_main

    return radar_main(sys.argv[1:])


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, rest = sys.argv[1], sys.argv[2:]
    sys.argv = [f"jobengine {cmd}"] + rest

    dispatch: dict[str, Callable[[], int]] = {
        "fetch": fetch.main,
        "build": build.main,
        "query": query.main,
        "tailor": tailor.main,
        "audit": metrics_audit.main,
        "track": track_cli.main,
        "serve": api.main,
        "seed-demo": seed_demo.main,
        "evaluate": evaluation.main,
        # RoleRadar has its own argparse tree; hand the rest of argv straight
        # to it rather than mirroring every flag here.
        "radar": _radar,
    }
    handler = dispatch.get(cmd)
    if handler is None:
        print(f"Unknown command: {cmd}\n")
        print(__doc__)
        return 1
    return handler()


if __name__ == "__main__":
    raise SystemExit(main())

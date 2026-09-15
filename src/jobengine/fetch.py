"""Fetch the latest Simplify listings into data/.

Pulls the machine-readable JSON both repos publish on their `dev` branch.
Run before build. Network failures are caught and reported clearly instead of
crashing with a raw traceback; a stale local copy is left untouched on failure
so build.py can still run against last-known-good data.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from . import config
from .logging_config import get_logger

log = get_logger(__name__)

TIMEOUT = 30
RETRIES = 3


def _fetch_one(dest, url: str) -> bool:
    for attempt in range(1, RETRIES + 1):
        try:
            log.info("Fetching %s (attempt %d/%d)", url, attempt, RETRIES)
            with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
                if resp.status != 200:
                    raise urllib.error.HTTPError(
                        url, resp.status, "non-200 response", resp.headers, None)
                data = resp.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            log.info("  -> %s (%s bytes)", dest, f"{len(data):,}")
            return True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("  attempt %d failed: %s", attempt, exc)
    log.error("Failed to fetch %s after %d attempts.", url, RETRIES)
    if dest.exists():
        log.warning("  Keeping existing %s (stale but usable).", dest)
    return False


def fetch_all() -> bool:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for dest, url in config.SOURCES.items():
        ok = _fetch_one(dest, url) and ok
    return ok


def main() -> int:
    if fetch_all():
        log.info("Done. Now run: jobengine build  (or: python -m jobengine.build)")
        return 0
    log.error("One or more sources failed to refresh. "
              "If stale local copies exist, build.py can still run against them.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

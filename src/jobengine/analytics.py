"""Usage analytics: record every API request, aggregate it into the numbers
you actually need to defend the project (traffic, latency percentiles, error
rate, adoption).

Design notes worth defending in a review:

* **Best-effort writes.** `record()` swallows every exception. Analytics is
  never allowed to turn a working request into a 500, and it must not consume
  the last pooled DB connection under load — see `enabled()`.
* **Percentiles are computed in Python, not SQL.** `percentile_disc` exists in
  Postgres but not SQLite, and this project runs on both. The row counts here
  (thousands per window) are small enough that pulling durations and sorting
  costs less than maintaining two query dialects.
* **Route templates, not paths.** The middleware passes the matched route
  pattern, so `/api/applications/41` and `/api/applications/9` aggregate
  together instead of producing one bucket each.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import db
from .logging_config import get_logger

log = get_logger(__name__)


def enabled() -> bool:
    """Analytics off-switch.

    Exists because the honest answer to "what does your instrumentation cost?"
    has to be measurable: the load-test harness runs the same endpoints with
    JOBENGINE_ANALYTICS=0 and =1 to show the overhead rather than assert it.
    """
    return os.environ.get("JOBENGINE_ANALYTICS", "1") not in ("0", "false", "no")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(route: str, method: str, status_code: int,
           duration_ms: float, user_id: int | None = None) -> None:
    """Insert one request event. Never raises."""
    if not enabled():
        return
    try:
        with db.get_engine().begin() as conn:
            conn.execute(db.api_events.insert().values(
                occurred_at=_now(),
                route=route,
                method=method,
                status_code=status_code,
                duration_ms=int(duration_ms),
                user_id=user_id,
            ))
    except Exception as exc:  # pragma: no cover - defensive by design
        # Debug, not warning: under a database outage this fires once per
        # request, and analytics failing is not itself an incident.
        log.debug("analytics write failed (ignored): %s", exc)


def _percentile(sorted_values: list[int], pct: float) -> int:
    """Nearest-rank percentile. Returns 0 for an empty sample."""
    if not sorted_values:
        return 0
    # Nearest-rank: ceil(pct * N) as a 1-based index, clamped into range.
    idx = max(0, min(len(sorted_values) - 1, int(pct * len(sorted_values) + 0.9999) - 1))
    return sorted_values[idx]


def summary(hours: int = 24) -> dict:
    """Traffic/latency/error rollup over the trailing `hours` window."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    engine = db.get_engine()
    ev = db.api_events

    with engine.connect() as conn:
        rows = conn.execute(
            select(ev.c.route, ev.c.status_code, ev.c.duration_ms, ev.c.user_id)
            .where(ev.c.occurred_at >= since)
        ).all()
        total_users = conn.execute(select(func.count()).select_from(db.users)).scalar() or 0

    if not rows:
        return {
            "window_hours": hours, "requests": 0, "registered_users": total_users,
            "active_users": 0, "error_rate": 0.0, "throughput_rps": 0.0,
            "latency_ms": {"p50": 0, "p95": 0, "p99": 0}, "by_route": [],
        }

    durations = sorted(r.duration_ms for r in rows)
    errors = sum(1 for r in rows if r.status_code >= 500)
    # 4xx is excluded from "error rate" on purpose: a 401 on an expired token
    # is the API working correctly. Counting client errors as server failures
    # is the fastest way to make an availability metric meaningless.
    client_errors = sum(1 for r in rows if 400 <= r.status_code < 500)

    per_route: dict[str, list] = {}
    for r in rows:
        per_route.setdefault(r.route, []).append(r)

    by_route = []
    for route, rs in sorted(per_route.items(), key=lambda kv: -len(kv[1])):
        ds = sorted(x.duration_ms for x in rs)
        by_route.append({
            "route": route,
            "requests": len(rs),
            "p50_ms": _percentile(ds, 0.50),
            "p95_ms": _percentile(ds, 0.95),
            "errors": sum(1 for x in rs if x.status_code >= 500),
        })

    return {
        "window_hours": hours,
        "requests": len(rows),
        "registered_users": total_users,
        "active_users": len({r.user_id for r in rows if r.user_id is not None}),
        "error_rate": round(errors / len(rows), 4),
        "client_error_rate": round(client_errors / len(rows), 4),
        "throughput_rps": round(len(rows) / (hours * 3600), 4),
        "latency_ms": {
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
            "p99": _percentile(durations, 0.99),
            "max": durations[-1],
        },
        "by_route": by_route,
    }

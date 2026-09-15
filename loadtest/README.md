# Load testing

## Status

**Recorded 2026-08-13.** Raw k6 summary exports are in `results/`; the analysis,
methodology, and caveats are in [`docs/measurements.md`](../docs/measurements.md).

Nothing in this repository quotes a latency figure, a throughput figure, or a
"before/after" improvement unless it was produced by an actual run of this
harness and the raw summary was checked in under `results/`.

Two scripts:

- `k6/search.js` — the Spring Boot search API (`/api/v1/jobs`). This is what
  the recorded results came from.
- `k6/browse.js` — the Python FastAPI read path (`/api/jobs`). **Not yet run**;
  no numbers are claimed for it.

## Prerequisites

- Docker Desktop running
- [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) — `winget install k6 --source winget`

## Running

```bash
docker compose -f loadtest/docker-compose.yml up -d --build
```

```bash
docker compose -f loadtest/docker-compose.yml exec api jobengine fetch
```

```bash
docker compose -f loadtest/docker-compose.yml exec api jobengine build
```

```bash
k6 run -e BASE_URL=http://localhost:8765 loadtest/k6/browse.js
```

```bash
k6 run -e BASE_URL=http://localhost:8765 -e PROFILE=stress loadtest/k6/browse.js
```

Save every run you intend to cite:

```bash
k6 run --summary-export=loadtest/results/$(date +%Y%m%d-%H%M)-baseline.json -e BASE_URL=http://localhost:8765 loadtest/k6/browse.js
```

## Comparing configurations

The pool bounds are environment variables specifically so a change can be
measured rather than asserted. To reproduce a constrained pool:

```bash
JOBENGINE_DB_POOL_SIZE=5 JOBENGINE_DB_POOL_TIMEOUT=30 docker compose -f loadtest/docker-compose.yml up -d --force-recreate api
```

Then re-run the stress profile and diff the two summary exports. A valid
before/after needs both runs on the same machine, same dataset, same profile —
otherwise the comparison measures your laptop's mood, not the change.

## What each profile is for

| Profile | Peak VUs | Purpose | Thresholds |
|---|---|---|---|
| `baseline` | 50 | Load the service is expected to survive; safe to gate CI on | Hard pass/fail |
| `stress` | 300 | Find the breaking point and confirm it sheds load gracefully | None — failing is the point |

## Reading the results

- `http_req_duration` p(95) — the headline latency number.
- `requests_shed_503` — designed backpressure from pool exhaustion. Non-zero
  under `stress` is expected and *good*; non-zero under `baseline` is a
  capacity problem.
- `http_req_failed` — everything else. Should be ~0 in both.

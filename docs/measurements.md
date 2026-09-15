# Measured results

## Precision evaluation status

Deduplication precision and matching precision remain **unmeasured** until a
human labels a real holdout sample. The reproducible evaluator and CSV schemas
are in [`../evaluation/`](../evaluation/README.md). It reports TP/FP/FN/TN,
precision, and recall and reuses production normalization/tokenization.
Example rows are demonstrations only and must never be reported as results.

## Refresh reliability status

The CloudWatch dashboard computes refresh success rate as
`100 * (Invocations - Errors) / Invocations` per six-hour schedule window.
There is no production percentage yet because the Terraform stack has not been
applied. Missing invocations are covered separately by the 12-hour schedule
alarm; otherwise a stopped schedule could misleadingly appear 100% successful.

Every number here came from a run on the date shown. Methodology and the exact
commands are included so each can be reproduced or disputed. Raw k6 summary
exports are in [`loadtest/results/`](../loadtest/results/).

**Environment for all runs (2026-08-13):** Windows 11 host, Docker Desktop,
WSL2 backend. PostgreSQL 16 (`pgvector/pgvector:pg16`) and Redis 7 in
containers, Spring Boot 3.3.5 on JDK 21 running via `spring-boot:run` (not a
production JVM configuration), k6 in a container on the same Docker network.
All components share one laptop, so the load generator competes with the
service for CPU. **These are single-machine developer-hardware numbers, not
production capacity figures.**

---

## 1. Listings processed per minute

```bash
DATABASE_URL=postgresql+psycopg://... time python -m jobengine.cli build
```

| Measure | Value |
|---|---|
| Raw records read | 32,735 |
| Unique postings written | 32,388 |
| Wall-clock time | 4.99 s |
| **Throughput** | **~393,000 records/minute** |

Fetch (network-bound, downloading 23.2MB from two GitHub raw endpoints) takes a
further 8.8s. End-to-end fetch + build is ~14s, i.e. **~140,000 records/minute**
including the network.

The dedup + normalize + sponsor-annotate stage is not the bottleneck; the
network is. That's worth knowing before optimizing anything.

## 2. Deduplication

| Measure | Value |
|---|---|
| Duplicates removed at ingest | 347 of 32,735 (1.06%) |
| Rows sharing a canonical URL post-ingest | 650 of 32,388 (2.01%) |

Read from `GET /api/v1/jobs/stats`, which measures what is actually stored
rather than trusting the ingest log.

**These are recall-style ratios, not precision.** Precision would require a
hand-labeled sample of listing pairs judged duplicate/not-duplicate, and that
sample does not exist yet. The 2.01% residual means the dedup key and the
canonical URL disagree on ~650 rows — either the key is too strict (same job,
two keys) or the URL canonicalizer is too loose. **Which of those it is, is
currently unknown.** See [known-limitations.md](known-limitations.md).

## 3. Search latency, throughput, and cache effect

```bash
docker run --rm -i --network jobengine-net -v "$PWD/loadtest:/lt" grafana/k6 \
  run -e BASE_URL=http://jobengine-java:8080 -e API_KEY=loadtest-key \
  -e PROFILE=baseline /lt/k6/search.js
```

30 virtual users, 90 seconds, head-heavy filter mix (70% of traffic to 5 popular
filter combinations), 32,388 listings in Postgres.

| | Cache **on** | Cache **off** (`spring.cache.type=none`) | Change |
|---|---|---|---|
| Requests completed | 304,851 | 69,989 | |
| Throughput | **3,387 req/s** | 777 req/s | **4.4×** |
| p50 latency | 5.44 ms | 27.97 ms | 5.1× faster |
| p90 latency | 11.47 ms | 58.70 ms | 5.1× faster |
| **p95 latency** | **14.46 ms** | **71.21 ms** | **4.9× faster** |
| Failed requests | 0 | 0 | |
| Cache hit rate | 99.99% (304,831 / 304,851) | 0% by construction | |

Raw exports: [`java-baseline.json`](../loadtest/results/java-baseline.json),
[`java-nocache.json`](../loadtest/results/java-nocache.json).

### Caveats that materially affect how these should be read

- **The 99.99% hit rate is an artifact of the test, not a prediction.** The
  generator draws from 12 filter combinations. Real traffic has a long tail,
  and the production hit rate will be much lower. What this run legitimately
  shows is the *ceiling*: what the cached path costs when it hits.
- **`max` latency was 4.6s on the cached run.** That is JIT warm-up on the
  first requests, not steady-state behavior. There is no warm-up period in
  these runs, which is a flaw in the harness.
- **`spring-boot:run` is not a production JVM setup** — no tuned heap, no AOT,
  running from a bind-mounted volume.
- The load generator ran on the same machine as the service and database.

## 4. Rate limiting

The first baseline attempt is worth recording because it failed usefully.
Against the development key (600 req/min), k6 pushed 17,580 req/s and received:

| Measure | Value |
|---|---|
| Requests sent | 1,582,021 |
| Rejected with 429 | 1,580,528 (99.90%) |
| Served | 1,493 |
| p95 latency of a 429 | 2.83 ms |

The limiter did exactly what it was built to do, and rejection is cheap — a
throttled caller costs ~2.8ms of CPU, not a database connection. It also meant
the run measured the limiter rather than search, which is why a `loadtest`
Spring profile with effectively unlimited quota now exists.

---

## Two defects found by measuring

**A Y2038 bug in the schema.** Hibernate's `ddl-auto: validate` refused to start
against the real database: `date_posted` was declared `Integer` in
`src/jobengine/db.py`, which Postgres maps to `int4`. The column holds Unix
epoch seconds, so it overflows on 2038-01-19. SQLite's dynamic typing hid this
completely — it only surfaced when a second service with a strict schema
validator was pointed at the same tables. Fixed by moving the column to
`BigInteger` and rebuilding (safe without a migration because `jobs` is derived
data). *This is the strongest argument in the project for the polyglot service
split: the Java service found a Python bug that Python's own test suite could
not.*

**The cache could not be turned off.** Defining `cacheManager` as an explicit
`@Bean` overrode Spring's auto-configuration, so `spring.cache.type=none`
silently did nothing — a benchmark run with caching supposedly disabled still
reported a 99.99% hit rate. Without noticing that, the cached/uncached
comparison in section 3 would have been two identical runs reported as a
speedup. Fixed with `@ConditionalOnProperty` on the configuration class.

---

## Not yet measured

Listed explicitly so their absence isn't mistaken for a good result.

- **Deduplication precision** — needs a hand-labeled sample.
- **Matching precision** — needs a labeled relevance set of (resume, job) pairs.
- **Data refresh success rate** — needs the scheduled pipeline running over time.
- **Availability** — needs a deployment and an uptime monitor.
- **Real-user metrics** (adoption, task completion, time saved) — needs users.
- **API throughput under a realistic long-tail cache profile** — see caveats above.

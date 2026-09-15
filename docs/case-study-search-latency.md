# Case study: making search fast, and three things that went wrong on the way

**Note on what this is.** This is what actually happened, with the numbers that
were actually measured, on the hardware they were measured on. It is not the
"connection pool exhausted at 300 concurrent requests, moved work to SQS,
1.8s → 240ms" story — that would be a better story, and it did not happen here.
Two of the three findings below are bugs I introduced myself and caught by
measuring. That is the honest version, and it is the one I can defend under
questioning.

Raw data: [`measurements.md`](measurements.md),
[`loadtest/results/`](../loadtest/results/).

---

## Context

JobEngine ingests ~32,000 job listings from two public feeds, deduplicates them,
and cross-references each employer against DOL H-1B filings so international
students can filter by who actually sponsors. The read path — filtered search
over the listings table — is what every visitor hits before they ever create an
account, so it is the path whose latency matters.

I split the system: a Python pipeline owns batch ingest, and a new Spring Boot
service owns online search with a Redis cache in front of Postgres. Then I tried
to prove the cache was worth having.

## Finding 1: the Java service found a Python bug that Python could not

The Spring Boot service refused to start:

```
Schema-validation: wrong column type encountered in column [date_posted]
in table [jobs]; found [int4], but expecting [bigint]
```

`date_posted` was declared `Integer` in the Python schema, which SQLAlchemy maps
to Postgres `int4`. The column holds **Unix epoch seconds**. `int4` tops out at
2,147,483,647 — which is 2038-01-19. Every timestamp the pipeline writes was
sitting in a column that silently overflows in twelve years.

**Why nobody caught it.** Local development and the entire Python test suite run
on SQLite, which has dynamic typing and stores whatever you give it. There is no
column-type mismatch to detect, so no test could have failed. The bug was
invisible from inside Python.

It surfaced the moment a second service with a *strict* schema validator
(`ddl-auto: validate`) was pointed at the same tables. Hibernate compared the
declared entity against the live schema and refused to boot.

**Fix.** Moved the columns to `BigInteger` and rebuilt. Safe without a migration
tool because `jobs` is derived data — the pipeline can drop and rebuild it from
upstream in five seconds, which is a property the architecture was designed for
and this is the first time it paid off.

**What I take from it.** I did not add a second service to find schema bugs; I
added it for domain separation, and the polyglot split has real costs I wrote
down in ADR-009. But a second independent reader of a schema finds things one
reader structurally cannot. That is a genuine benefit of the design that I
didn't anticipate and can't claim I planned.

## Finding 2: I measured the rate limiter and thought I was measuring search

First load test, 30 virtual users against the search API:

| | |
|---|---|
| Requests sent | 1,582,021 |
| Rejected with 429 | 1,580,528 (**99.90%**) |
| Actually served | 1,493 |

k6 pushed 17,580 req/s at a development API key rated for 600 req/**minute**.
The token-bucket limiter did exactly its job and rejected essentially
everything. The p95 of 2.83ms in that run is the cost of *saying no*, not the
cost of a search.

Two things worth keeping from this. First, rejection is cheap — a throttled
caller costs ~3ms of CPU and never touches a database connection, which is the
entire point of limiting at the edge. Second, **a load test result that looks
clean can be measuring the wrong thing entirely.** A p95 of 2.83ms would have
looked like a triumph if I hadn't checked the status codes.

**Fix.** A `loadtest` Spring profile with effectively unlimited quota, so the
benchmark exercises search instead of the limiter. It is documented as
never-for-production.

## Finding 3: my cache could not be turned off

To show the cache mattered I needed an uncached baseline. Spring has a standard
switch for this: `spring.cache.type=none`. I set it, re-ran, and got:

```
hits: 307,446    misses: 18
```

With caching "disabled." The cache was still fully operational.

**Cause.** I had defined `cacheManager` as an explicit `@Bean` in my own
configuration class. An explicit bean overrides Spring Boot's auto-configuration
entirely, and `spring.cache.type` only controls the auto-configured path. The
property was being read and quietly ignored.

**Why this one matters most.** If I hadn't noticed, I would have run two
identical cached benchmarks, labelled one "before" and one "after," and reported
a cache speedup of roughly zero — or worse, noise in the favourable direction —
as a real result. The failure mode of this bug is *publishing a false number*.

**Fix.** Gate the configuration class:

```java
@ConditionalOnProperty(name = "spring.cache.type",
                       havingValue = "redis", matchIfMissing = true)
public class RedisCacheConfig { ... }
```

I also deleted a k6 profile I'd written called `cachecold`, which cycled
`(__ITER * 7) % 200` to generate "unique" queries. That expression produces
exactly 200 distinct values, so it warmed the cache within a fraction of a
second and reported a 99.93% hit rate while claiming to measure a cold cache. It
was removed rather than left in the repository as a trap.

## The actual result

30 virtual users, 90 seconds, 32,388 listings, head-heavy filter mix:

| | Cache on | Cache off | Change |
|---|---|---|---|
| Throughput | **3,387 req/s** | 777 req/s | **4.4×** |
| p50 | 5.44 ms | 27.97 ms | 5.1× |
| p95 | **14.46 ms** | 71.21 ms | **4.9×** |
| Failed requests | 0 / 304,851 | 0 / 69,989 | — |

### What these numbers are not

- **The 99.99% hit rate is an artifact of the test, not a forecast.** The
  generator draws from 12 filter combinations. Real search traffic has a long
  tail, and the production hit rate will be materially lower. What the run
  legitimately establishes is the *ceiling*: what a cache hit costs when it hits.
- **Single machine.** Service, Postgres, Redis, and the load generator all
  shared one laptop and competed for CPU.
- **Not a production JVM.** `spring-boot:run` from a bind-mounted volume, no
  heap tuning, no AOT, and no warm-up period — the 4.6s max latency on the
  cached run is JIT warm-up, not steady state.

### The uncomfortable question I'd expect to be asked

*"777 req/s uncached with p95 of 71ms — did you actually need Redis?"*

Honestly: not for correctness or for this load. Postgres was serving an indexed
query over a 32k-row table that fits entirely in shared buffers, and 777 req/s
already exceeds any traffic this project will realistically see. The cache buys
headroom and a 4.9× latency improvement, and it cost a dependency, a failure
mode (which is why it fails open — see `CacheErrorConfig`), and an invalidation
concern.

At this scale that is a defensible-but-optional choice, not a necessary one. It
becomes necessary when the corpus grows past what fits in memory or when the
filter predicates stop being index-friendly — the location filter is already a
`LIKE '%...%'` against a JSON string column and cannot use an index at all, so
that day is closer than the current numbers suggest.

## What I'd do next, in order

1. **Fix the location filter.** Normalize locations into their own table at
   ingest. It is the one filter that cannot use an index, and it is the thing
   most likely to break the latency numbers above as the corpus grows.
2. **Re-run with a long-tail query distribution** to get a hit rate that means
   something.
3. **Add a warm-up period** to the k6 profiles so p-values describe steady state.
4. **Measure on separate machines.** Every number here is contaminated by the
   load generator sharing a CPU with the service.

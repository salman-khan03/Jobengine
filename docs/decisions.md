# Design decisions

Each entry records the decision, the alternatives actually considered, and what
it costs. A decision with no listed cost is a decision that wasn't examined.

---

## ADR-001: SQLAlchemy Core over an ORM or raw SQL

**Decision.** SQLAlchemy Core — table definitions and expression-language
queries — not the ORM, and not `sqlite3`/`psycopg` directly.

**Alternatives.** (a) Raw driver SQL, which the project originally used.
(b) The full ORM with declarative models and a session/identity map.

**Why.** Raw SQL meant two code paths once Postgres entered the picture, since
SQLite and Postgres disagree on parameter style, upserts, and autoincrement.
The full ORM solves a problem this project doesn't have: there is no rich
object graph, the queries are flat filters and aggregates, and the ORM's lazy
loading is a well-known source of N+1 queries in exactly this kind of listing
endpoint. Core gives dialect portability without the identity map.

**Cost.** Queries are more verbose than ORM equivalents, and relationship
traversal is manual. Accepted — the queries are simple enough that verbosity is
cheap and explicitness is worth something.

---

## ADR-002: Lazy engine construction via `get_engine()` + PEP 562 `__getattr__`

**Decision.** No module-level `ENGINE` constant. `db.ENGINE` is a dynamic
module attribute that resolves the current `DATABASE_URL` on each access,
cached per URL.

**Alternatives.** (a) `ENGINE = create_engine(...)` at import time.
(b) Explicit dependency injection of an engine into every function.

**Why.** An import-time engine freezes the database URL at first import, which
breaks two real cases: tests that monkeypatch `config.DB_PATH` for per-test
isolation, and any process that sets `DATABASE_URL` after importing the module.
Dependency injection would solve it properly but requires threading an engine
parameter through every function in five modules.

**Cost.** Module-level dynamic attributes are unusual and can confuse static
analysis and readers who don't know PEP 562. Mitigated by a comment at the
definition explaining exactly why.

---

## ADR-003: TF-IDF cosine similarity, not called "semantic AI"

**Decision.** `semantic_match.py` implements classical TF-IDF vector-space
ranking, opt-in behind `tailor --semantic`. Vector embeddings live separately
in `embeddings.py` + pgvector, and are also opt-in.

**Why the naming matters.** TF-IDF is information retrieval, not semantics —
it cannot tell that "distributed systems" and "microservices" are related. The
project's own `metrics_audit.py` exists to reject resume claims the candidate
can't defend; branding lexical matching as AI would fail the project's own
audit. Naming things accurately is the point.

**Cost.** Less impressive on a feature list. Considerably easier to defend when
someone asks how it works.

---

## ADR-004: Bounded connection pool with fast rejection

**Decision.** `pool_size=10`, `max_overflow=10`, `pool_timeout=5s` on Postgres,
all environment-tunable. Pool exhaustion surfaces as `503 + Retry-After`.

**Alternatives.** (a) SQLAlchemy defaults with a 30s timeout. (b) An unbounded
pool. (c) Raising Postgres `max_connections` instead.

**Why.** `pool_size + max_overflow` is the ceiling *per API process*, so the
real budget is that sum times the worker count. At 4 workers this is 80
connections against a stock 100-connection Postgres, leaving headroom for the
refresh job and a psql session. An unbounded pool moves the failure from the
app (recoverable, one request fails) to the database (everything fails, and
recovery needs an operator). Raising `max_connections` costs ~10MB of server
memory per connection and postpones the problem rather than bounding it —
PgBouncer is the real answer at that scale.

**Cost.** Under sustained overload some requests are rejected that a longer
queue might eventually have served. That's the intended trade: bounded latency
for served requests beats unbounded latency for all of them.

---

## ADR-005: Analytics in the application database

**Decision.** `api_events` is a table in the same PostgreSQL database, written
by middleware, aggregated in Python.

**Alternatives.** (a) Prometheus + Grafana. (b) A hosted APM. (c) CloudWatch
custom metrics. (d) A separate analytics database.

**Why.** At this scale the entire dataset is a table Postgres aggregates in one
query. Prometheus is the right answer for time-series at scale but means
operating two more services, and its counters can't answer "which *users* were
active" without a cardinality explosion. Keeping events joinable against
`users` is what makes adoption measurable at all.

**Cost.** A write-heavy table shares the app's connection pool — which is why
writes are best-effort and never block a request — and there's no retention
policy yet, so the table grows without bound. Both are recorded as limitations.
This decision does not scale past roughly a million events; at that point the
right move is partitioning by month, then a real time-series store.

---

## ADR-006: Percentiles computed in Python, not SQL

**Decision.** Pull durations for the window, sort, index by nearest rank.

**Why.** `percentile_disc` is a Postgres window function with no SQLite
equivalent, and this project must run identically on both. At thousands of rows
per window, transferring and sorting costs less than maintaining two query
dialects and testing both.

**Cost.** Memory grows linearly with window size, and a 30-day window would be
a bad idea. The dashboard offers 1h/24h/7d for this reason. Beyond that,
pre-aggregating into hourly buckets is the fix.

---

## ADR-007: Batch ingest, not request-time fetching

**Decision.** A scheduled pipeline writes `jobs`; the API only reads it.

**Why.** Upstream updates a few times a day. Per-request fetching would make
p95 latency a function of GitHub's CDN and the API's availability a function of
GitHub's, for identical results.

**Cost.** Data is stale by up to one refresh interval. Correct trade for daily
data; wrong for anything real-time.

---

## ADR-008: One database, two access surfaces (CLI unauthenticated)

**Decision.** CLI rows have `user_id = NULL`; API rows always have a real
`user_id`. Same table.

**Why.** The CLI runs on the user's own machine against their own data — adding
a login to it would be security theatre. Two tables would need a merge
migration the day someone wants their CLI data in the web app.

**Cost.** Ownership is enforced in application code rather than by a `NOT NULL`
constraint. Centralized in `tracker._owned()` and regression-tested, but it is
a weaker guarantee than the schema enforcing it.

---

## ADR-009: Spring Boot owns the online serving tier; Python keeps ingest

**Decision.** Spring Boot (`services/core-api`) owns job **search** — filters,
pagination, Redis caching, rate limiting, API keys, application tracking,
explainable lexical matching, and deduplication diagnostics. The Python service
keeps ingest, normalization, deduplication decisions, sponsorship annotation,
embeddings, and credential issuance. Spring validates the same HS256 bearer
token, so tracker ownership is consistent across both APIs.

*Superseded ADR-009a:* an earlier version of this decision gave Spring Boot only
the tracker. The split moved to serving-vs-ingest because it draws a cleaner
line: one side is batch, CPU-bound, and data-science-shaped; the other is
online, IO-bound, and request-shaped.

**Why.** The two sides differ in shape: ingest is a batch pipeline that runs a
few times a day and is judged on throughput; serving is online, judged on p95
latency, and needs connection pooling, caching, and quota enforcement — all
things the Spring ecosystem supplies as configuration rather than code.

**Deduplication deliberately did NOT move.** It depends on `normalize.py`'s
company/title/URL canonicalization, tuned against real messy data and covered by
tests. Reimplementing it in Java would create two normalizers that must agree
forever — the classic way a polyglot system develops a silent correctness bug.
Java serves deduplicated data and reports dedup statistics; Python decides what
"duplicate" means.

**Cost, stated plainly.** One service would be simpler. The split adds a second
deployment, a second dependency tree, a second connection pool against the same
database, and a shared JWT secret between the issuer and verifier. Python owns
credential checks and issuance; Java verifies tokens and scopes every tracker
query by `sub`. It was justified by domain separation and by the
value of demonstrating a polyglot boundary, not by a measured performance need.

**What the split actually bought, measured.** Pointing a second service with a
strict schema validator at the shared database immediately surfaced a Y2038
`int4` timestamp bug that SQLite's dynamic typing had hidden from Python's own
test suite (see [measurements.md](measurements.md)). That was not the
justification for the split, but it is the strongest evidence for it — a second
independent reader of a schema finds things one reader cannot.

---

## ADR-010: JWT in `localStorage` via NextAuth, not httpOnly cookies

**Decision.** The backend issues a bearer token; NextAuth holds it client-side.

**Alternatives.** httpOnly, `SameSite=Strict` session cookies.

**Why.** Bearer tokens keep the API stateless and usable from the CLI, curl,
and any client — a cookie-session API is awkward for non-browser consumers.

**Cost.** A token reachable from JavaScript is stealable by any XSS. httpOnly
cookies are strictly safer against XSS at the price of CSRF handling and a
browser-shaped API. For an app storing job applications this is an acceptable
trade; for anything holding money it would not be. Recorded in the threat model
as T6.

---

## ADR-011: Hard constraints gate the decision instead of contributing a score

**Decision.** Eligibility (sponsorship, citizenship, clearance, graduation
window, enrollment, location) is evaluated in its own stage that can *veto* a
role, before any similarity or coverage scoring runs.

**Alternatives.** Treat each constraint as one more weighted feature in the
ranker — the conventional design, and a much smaller amount of code.

**Why.** Eligibility is not continuous. A role that cannot sponsor is not "a
slightly worse match" for a candidate who needs sponsorship; it is a zero.
Averaging a hard disqualifier with a 0.9 skill overlap produces a confident,
expensive lie, and the cost lands on the user as a wasted application rather
than on the system as a bad metric. Sorting also respects the veto: a blocked
role with a 0.9 match ranks below an eligible 0.6, because the user cannot
accept the first one.

**Cost.** Two scoring paths to reason about instead of one, and a three-way
verdict (`blocked` / `risk` / `ok`) where a single number would be simpler to
display. The `risk` tier exists precisely because a two-way gate would be too
blunt — "on-site in another city" must not veto the way "cannot sponsor" does.

---

## ADR-012: The LLM writes explanations only, and its claims are validated

**Decision.** The verdict, score and every coverage row are computed by
deterministic code. A model is invoked last, receives the already-final result
plus the candidate's verbatim evidence, and returns claims that each cite
evidence ids. `explain.validate_grounding` then deletes any claim that cites
nothing, cites an unknown id, or states a number absent from the evidence it
cites. If nothing survives, the deterministic template is published instead.

**Alternatives.** (a) Let the model judge fit directly from resume + JD — the
standard "AI job matcher". (b) Let it write freely over structured input with
no post-check.

**Why.** (a) makes the product unauditable and non-reproducible: the same input
yields different advice, and no part of the answer can be traced to anything.
(b) fails on the specific, predictable failure mode — a model asked to sell a
candidate invents experience, and "3 years of Python" is exactly the kind of
sentence a reader believes. Validating against cited text catches it
mechanically rather than hoping the prompt holds.

**Cost.** The prose is more constrained and occasionally more clipped than an
unconstrained model would produce, and one extra prompt-engineering surface
(claims must come back as structured JSON). Dropped claims are returned to the
caller rather than swallowed, so the rejection rate is measurable — a grounding
checker whose rejections are invisible is indistinguishable from one that never
rejects anything.

---

## ADR-013: Ship hand-set ranking weights plus an evaluation harness, not a learned model

**Decision.** `ranking.WEIGHTS` is a hand-set linear model, published at
`GET /api/v2/model`. Every decision is persisted with the `model_version` that
produced it, and `outcomes.py` scores the ranking against real application
outcomes (NDCG, precision/lift@k, Brier, calibration, Spearman).

**Alternatives.** Fit a ranker immediately; or ship the scorer with no
evaluation at all.

**Why.** A learned ranker needs labelled outcomes and on day one there are
none — fitting on nothing produces a model that is merely opaque rather than
merely arbitrary. A transparent prior can be argued with, and the harness is
what would later prove a fitted model is actually better. Storing the
prediction *as made at the time* matters: re-scoring six months later would use
today's weights and today's resume, measuring whatever the ranker currently is
rather than what the user acted on.

**Cost.** The weights are currently justified by judgement, not data, and the
repo says so. Metrics are withheld below a minimum sample rather than reported
from a handful of applications, and lift at or below 1.0 is reported plainly as
"not yet beating random order" — an unflattering result the harness is designed
not to hide.

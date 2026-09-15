# Known limitations

Written to be read by someone evaluating this project critically. Every item
here is something I'd rather say first than be caught not knowing.

## Data and correctness

**Sponsorship is a signal, not a guarantee.** The tier comes from historical
DOL LCA filings: it says an employer *has* sponsored, not that they *will*
sponsor this role. A company that filed 400 LCAs last year can still post a
citizens-only role. The UI shows the match count so the evidence is visible,
but a user who reads "very_high" as "guaranteed" will be disappointed.

**Employer matching is fuzzy and sometimes wrong.** DOL filings use legal
entity names ("GOOGLE LLC"); job postings use brand names ("Google"). The
normalizer handles common cases, but subsidiaries, acquisitions, and staffing
agencies filing on a client's behalf all produce mismatches in both directions.
There is no ground-truth dataset to measure the error rate against, so **the
accuracy of this matching is unmeasured** — that is a real gap, not a small one.

**Coverage is limited to what SimplifyJobs lists.** Roles posted only on a
company's own careers page are invisible. The pipeline inherits every gap and
every error in the upstream feeds.

**The DOL dataset lags by a quarter.** A company that started sponsoring last
month looks like a non-sponsor.

## Engineering

**No database migration tool.** `create_all()` creates missing tables and
ignores existing ones, so any column change today needs a hand-written
`ALTER TABLE`. Survivable only because `jobs` is rebuildable derived data.
Alembic is the fix and it isn't done.

**No rate limiting.** `/api/auth/login` accepts unlimited attempts. bcrypt
makes each attempt expensive, which also makes the endpoint a CPU-exhaustion
vector. This is the most serious open security item (threat model T1).

**CORS defaults to `*`.** Correct for a local tool, dangerous in production.
`JOBENGINE_CORS_ORIGINS` fixes it, but a permissive *default* fails silently
when someone forgets.

**`max` is not clamped.** `?max=100000` will try to serve every row and hold a
connection while doing it.

**No analytics retention policy.** `api_events` grows forever. At current
volumes that's years away; the design (ADR-005) stops being right at roughly a
million rows.

**No token revocation.** "Sign out everywhere" doesn't exist. A stolen token is
valid until it expires.

**Single region, single database, no read replica.** No failover story. If the
database is down, the product is down.

**No frontend tests.** Types and build are verified; behavior is not. A
Playwright smoke test of the core flow is the obvious first addition.

## Measurement

**Load-test results are single-machine developer-hardware numbers.** See
[measurements.md](measurements.md). The service, database, Redis, and the k6
generator all shared one laptop, and the Spring service ran under
`spring-boot:run` rather than a tuned JVM. The measured 99.99% cache hit rate
is an artifact of a 12-query test mix, not a prediction of production behavior;
real traffic has a long tail and the real hit rate will be materially lower.

**No real users yet.** No adoption, task-completion, or time-saved figures
exist. Any such number will come from an actual usage log or an actual
interview, and will say how it was measured.

**Analytics only counts what reaches the API.** The Next.js app renders some
pages statically; page views that don't call the backend aren't recorded, so
"requests" undercounts "visits."

## Product

**Tailoring runs only from the CLI.** It reads a local resume file and writes
local documents, so the web app can't do it. That splits the product across two
interfaces.

**The metrics audit is rule-based, not intelligent.** It flags claims matching
patterns it knows about. It will miss a novel indefensible claim and will
occasionally flag a true one.

**Single-user mental model in a multi-user app.** There's no sharing, no team
view, and no way to compare your funnel against anyone else's — which is
arguably the most useful thing a tracker with many users could offer.

**Vector search requires Postgres.** On the SQLite backend it returns a clear
"unavailable" error rather than degrading to lexical search. Degrading would be
friendlier; failing loudly was chosen so nobody mistakes lexical results for
vector results.

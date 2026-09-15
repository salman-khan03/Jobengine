# RoleRadar (built on JobEngine)

**Evidence-Grounded AI Job Intelligence Platform.** RoleRadar answers
*"should I apply to this role, and why?"* with inspectable resume evidence,
eligibility checks, requirement coverage, and a transparent match score.
It extends JobEngine's existing ingest pipeline into one product.

```
resume evidence  +  job requirements
              |
      structured extraction        verbatim units, each tagged with its source
              |
       hard-constraint gate        sponsorship / grad window / auth  -> can VETO
              |
         skill matching            taxonomy + graded, cited evidence
              |
       semantic ranking            bounded to 20% of the score
              |
        AI explanation             model writes prose; uncited claims deleted
              |
        Should I Apply?  ->  outcome funnel  ->  ranking evaluation
```

The AI differentiator is deliberately **not** "chat with your resume". The
model never decides anything: the verdict and score are computed by
deterministic, published code, and the model only writes prose about an
already-final result. Any sentence it produces that cites no evidence — or
states a number absent from the evidence it cites — is deleted before a human
sees it. Full design rationale: [`docs/roleradar.md`](docs/roleradar.md).

Citation and numeric checks are safeguards, not proof of semantic truth.
The deterministic verdict, blockers, and gaps remain visible alongside optional
AI prose. Match scores are not hiring probabilities.

Try it with no account: `POST /api/v2/decide` with an inline resume and job
description, or the `/radar` page.

## Run the complete product locally

```bash
docker compose up --build -d
```

Open [RoleRadar](http://localhost:3000/radar). The bundled sample works without
an account or AI key. Register to save evidence snapshots and record application
outcomes. See the [five-minute demo and engineering guide](docs/roleradar-demo.md).

The compose stack runs Next.js → Spring Boot `/api/v2` → Python decision workers,
with PostgreSQL/pgvector and Redis. Existing authentication and legacy workflow
routes continue to use Python. All exposed ports bind to localhost; the included
credentials are development defaults. Optional Gemini/Groq settings are listed
in `.env.example`. Stop containers with `docker compose stop`; data stays in the
PostgreSQL volume.

---

## JobEngine: the ingest layer underneath

A production-oriented, sponsor-aware job discovery and application workflow
built on
the **SimplifyJobs** [Summer 2026 Internships](https://github.com/SimplifyJobs/Summer2026-Internships)
and [New-Grad Positions](https://github.com/SimplifyJobs/New-Grad-Positions)
feeds. Deduplicates ~35k listings into one database, attaches a data-backed
H-1B sponsorship signal Simplify itself doesn't provide, and generates
per-role tailored resumes and cover letters — gated by an automated audit that
catches resume claims you can't actually defend in an interview. The deployed
architecture uses PostgreSQL, FastAPI, a separate Spring Boot/Redis search
service, a responsive Next.js dashboard, and an AWS scheduled refresh design.

## Why this exists

Simplify's own `sponsorship` field is `"Other"` (i.e. unknown) on ~99% of
listings — it can't tell an international candidate which employers actually
sponsor. JobEngine cross-references each employer against historical DOL H-1B
LCA filings instead, so shortlists can be ranked by *who really sponsors*, not
guesswork.

## Architecture

```
src/roleradar/          Decision engine: evidence + requirement extraction,
                        constraint gate, cited skill matching, ranking,
                        grounded LLM explanation, outcome evaluation
src/jobengine/          Python ingest, FastAPI workflow API, analytics, matching
services/core-api/      Spring Boot 3 / Java 21 cached public search API
web/                    Next.js 16 responsive jobs, tracker, and metrics dashboard
infra/                  EventBridge → Lambda → SQS plus CloudWatch Terraform
loadtest/               k6 baseline and 300-VU stress profiles + raw exports
docs/                   Architecture, ERD, contract, threat model, ADRs, costs
tests/                  Python unit/integration tests; Java tests live with the service
```

PostgreSQL is the production system of record. SQLite remains a zero-setup
local/test fallback, not the only supported database. See the
[architecture](docs/architecture.md) and [database diagram](docs/database.md)
for the service boundaries and data ownership.

## Install

```bash
pip install -e ".[dev]"     # editable install + test/lint/type-check tooling
```

For PostgreSQL use `pip install -e ".[postgres,dev]"`. The `postgres` extra adds
the psycopg driver; `dev` adds pytest, mypy, ruff, and HTTP test tooling.

## Usage

```bash
jobengine fetch                                          # pull latest listings
jobengine build                                          # dedup + sponsor-annotate -> jobengine.db
jobengine query --summary                                # sponsorship-tier breakdown
jobengine query --grad newgrad --tier offers,very_high,high --export shortlist.csv
jobengine tailor --company Amazon --match "software" --grad newgrad
jobengine audit                                           # check resume.json for indefensible claims
```

### RoleRadar: should I apply?

```bash
roleradar profile set --resume resume.json --needs-sponsorship
cat jd.txt | roleradar decide --company Stripe --title "Backend Engineer" --save
roleradar rank --grad newgrad --tier offers,very_high --limit 20 --save
roleradar outcome add --job-key <key> --stage interview
roleradar evaluate                                       # did the ranking predict outcomes?
```

Also available as `jobengine radar <subcommand>`, and over HTTP at `/api/v2`
(`POST /api/v2/decide` works signed-out with an inline resume). A real run:

```
$ cat jd.txt | roleradar decide --company Acme --title "Software Engineer Intern"

BLOCKED  64/100  (confidence 0.63)  Acme - Software Engineer Intern
  required 0.88 | preferred 0.18 | semantic 0.13 | seniority 1.00 | risk -0.00

  Do not apply. Match score 64/100 for Software Engineer Intern at Acme.

  Blocking:
  - You need visa sponsorship and this employer states it is not available.
    Applying cannot lead to an offer you can accept.

  What backs you up:
  - python: Satisfied via python. Demonstrated in JobEngine. (JobEngine - projects[0])
  - sql: Implied by JobEngine, which uses a technology that requires sql.
    (JobEngine - projects[0])
```

Note what that output is doing: it scores the role as an **88% required-skill
match and still refuses to recommend it**, because eligibility is a gate rather
than a weighted feature — and every positive claim points at the resume line
behind it. See [`docs/roleradar.md`](docs/roleradar.md).

`make check` runs everything CI runs (lint, type-check, tests) in one command.

### Sample run

```
$ jobengine query --grad newgrad --tier offers,very_high,high --max 5
5 matching roles
  [very_high] Microsoft                | Software Engineer - Ctj - Poly             | MD
  [very_high] Amazon                   | Data Scientist 1 - SCOT-Inbound - Planning | NYC
  [very_high] Google                   | Software Engineer 3 - Infrastructure       | Irvine, CA
  ...
```

Measured on 2026-08-13 against the live feeds: **32,735 raw records → 32,388
deduplicated** (347 duplicates removed) in 4.99s, of which **4,502 are active
and visible**. Of those, 404 carry a `very_high`/`high`/`offers` sponsorship
tier from the seed index and 28 are correctly excluded as citizen-only or
explicit non-sponsors. Counts move with the upstream feeds; re-run
`jobengine build` for current figures.

## Sponsorship index: seed vs. full DOL load

Ships with a curated seed of established high-volume sponsors (`tier`
approximate, `sponsor_lca_count = 0`, `sponsor_match = "index:seed"`) so it
works offline with zero setup.

For real per-employer filing counts, download a DOL OFLC LCA disclosure CSV
(from dol.gov) and load it — this overrides the seed with actual data:

```bash
jobengine build --dol-csv data/LCA_Disclosure_FY2025.csv
```

A company **absent** from the index is `unknown`, never "does not sponsor" —
that distinction is load-bearing and is enforced in code and tests
(`test_unknown_company_is_unknown_not_no`).

## Tailoring engine

`resume.json` is the structured source of truth. `tailor.py` selects and
reorders existing resume content by relevance to the target role — **it never
invents a bullet, number, or claim**. Paste a job description with `--jd-file`
for sharp keyword-driven ranking; without one, ranking falls back to
title/category signal only (and is honest about being thin in that case).

The **metric audit runs on every tailor invocation** and is a gate, not a
footnote: it flags implausible accuracy percentages, unverifiable user counts,
and baseline-free improvement claims, with a specific suggested fix for each.
`--scrub` replaces high-severity claims with an explicit
`[INSERT REAL METRIC]` marker rather than silently deleting the number —
so a broken or indefensible claim can never ship by accident. Fix a flag once
in `resume.json` and every future tailored copy is clean.

```bash
jobengine tailor --company Stripe --title "Backend Engineer" --jd-file jd.txt --scrub
```

`llm.py` optionally polishes the cover letter's tone via OpenRouter/Grok
(`OPENROUTER_API_KEY`) for flow only — it's instructed never to add facts, and
any failure falls back to the deterministic template untouched.

## Application tracker

The post-application half: what you applied to, where you applied from, and
what's happened since. Lives in the same `jobengine.db` as the job pipeline —
`dedup_key` links a tracked application straight back to the posting it came
from when it originated in `jobengine query`, with full provenance.

```bash
jobengine track add --company Stripe --title "Backend Engineer" --source linkedin
jobengine track add --company Amazon --title "SDE Intern" --source simplify \
  --dedup-key "amazon|sde_intern|https://..."          # links back to the jobs table

jobengine track list                                    # all applications
jobengine track list --status interview                 # filtered
jobengine track status 1 oa --note "HackerRank link"     # status pipeline + audit trail
jobengine track history 1                                # full event timeline
jobengine track edit 1 --notes "recruiter is Jane"
jobengine track delete 1
jobengine track summary                                  # counts by status
```

Status pipeline: `saved → applied → heard_back → oa → interview → offer`, with
`rejected`/`withdrawn` reachable from any stage. Every transition is logged to
a `status_events` table — `jobengine track history` shows the full timeline,
not just the current state. Unusual transitions (e.g. `offer → applied`) are
flagged in the logs rather than blocked, since real pipelines aren't always
linear.

**Email signal detection** — paste a recruiter email, get back the status it
signals:

```bash
jobengine track parse-email --file email.txt --app-id 3
```

This is a deliberately simple, auditable regex classifier (offer / rejection /
interview / OA / heard-back phrase patterns), not an opaque "AI" black box —
it returns the exact phrase it matched and a confidence of `1.0` or `0.0`
rather than a manufactured score. Good enough for routine recruiter emails;
ambiguous ones fall through to manual status updates by design.

## APIs and dashboard

```bash
jobengine serve --port 8765
```

FastAPI serves authentication, per-user applications, analytics, and semantic
matching. Interactive docs are generated at `/docs`; the checked-in contract is
[`docs/openapi.json`](docs/openapi.json). The separate Spring Boot service owns
the high-volume public search path at `/api/v1/jobs`, exposes Swagger UI at
`/api/v1/docs`, validates the shared Postgres schema at startup, and uses a
bounded Hikari connection pool plus Redis read-through caching.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/jobs?grad=&tier=&location=&max=` | Sponsor-ranked, filtered postings |
| GET | `/api/jobs/summary` | Sponsorship-tier breakdown |
| GET | `/api/applications?status=` | Tracked applications |
| POST | `/api/applications` | Add an application |
| PATCH | `/api/applications/{id}` | Edit company/title/url/notes/source |
| POST | `/api/applications/{id}/status` | Status transition (logged) |
| DELETE | `/api/applications/{id}` | Remove |
| GET | `/api/applications/{id}/history` | Status timeline |
| GET | `/api/applications/summary` | Counts by status |
| POST | `/api/parse-email` | Email -> detected status signal |

Every write route validates input and returns a proper 400/404/503 with a clear
message. Pool exhaustion becomes a bounded `503 Retry-After` response rather
than unbounded request queueing. Set `JOBENGINE_CORS_ORIGINS` to the deployed
frontend origin before public deployment.

The React dashboard at `/dashboard` reports measured requests, active and
registered users, p50/p95/p99 latency, throughput, 4xx rate, 5xx error rate,
and route-level breakdowns. It never seeds traffic metrics; an empty deployment
shows an explicit no-data state.

## Evidence and production status

| Requirement | Implementation / evidence | Status |
|---|---|---|
| PostgreSQL | SQLAlchemy portable schema, psycopg extra, JPA validation, pgvector | Implemented and locally measured |
| Separate Spring API | `services/core-api`, bounded Hikari pool, Redis cache, Actuator, OpenAPI | Implemented and locally load-tested |
| Scheduled AWS refresh | Terraform EventBridge → Lambda → SQS → worker/DLQ | Implemented as IaC; not applied |
| CloudWatch monitoring | Dashboard, retained logs, missing-run/error/backlog/DLQ alarms, SNS | Implemented as IaC; not applied |
| React dashboard | Next.js/React jobs, tracker, auth, analytics dashboard | Implemented; local build verified |
| Load testing | k6 baseline + 300-VU stress profiles, raw JSON exports | Measured locally |
| Usage analytics | Request events, active users, latency/error/throughput rollups | Implemented; awaiting live traffic |
| Live app and availability | Deployment guide, Docker images, health probes | Requires cloud accounts and URL |
| Evidence-grounded decisions | `src/roleradar/`: provenance-tagged extraction, constraint gate, cited coverage | Implemented; 133 tests |
| Grounding validation | Claims lacking a supporting citation are dropped and counted, not trusted | Implemented and unit-tested |
| Ranking evaluation | NDCG / precision / lift@k / Brier / calibration over logged outcomes | Harness implemented and tested; **never run on real outcomes** |
| Real users | 5–15 person protocol and evidence table | Not yet run; no users invented |
| Public communication | Demo script, article outline, architecture copy, LinkedIn draft | Drafted; not published |

Measured local search result: **3,387 req/s at 14.46 ms p95 with cache** versus
**777 req/s at 71.21 ms p95 without cache**, using the workload and hardware
documented in [`docs/measurements.md`](docs/measurements.md). Raw k6 summaries
are checked in under `loadtest/results/`.

The engineering failure story is the evidence-backed
[`search-latency case study`](docs/case-study-search-latency.md). The suggested
“300 concurrent requests, 1.8s → 240ms” wording is deliberately not claimed:
those numbers were not produced by this repository's runs. The AWS/SQS split is
real code, but its production effect remains unmeasured until deployment.

Production setup, demo seeding, health checks, environment variables, and
rollback steps are in [`DEPLOY.md`](DEPLOY.md). The full documentation index is
[`docs/README.md`](docs/README.md); recruitment and metrics collection are in
[`docs/user-study.md`](docs/user-study.md); publication drafts are in
[`docs/public-launch-kit.md`](docs/public-launch-kit.md).



```bash
pytest -q          # 283 tests (2026-09-11). JobEngine: normalization, dedup,
                   # sponsorship tiers, auth, metric audit, JD-keyword ranking,
                   # analytics rollups, demo seeder, AWS Lambda adapters,
                   # tracker CRUD + status pipeline + email parser.
                   # RoleRadar: skill taxonomy and implication graph, resume
                   # evidence provenance, requirement/constraint extraction
                   # (incl. every contraction of "cannot sponsor"), the
                   # eligibility gate, cited coverage scoring, ranking
                   # composition, LLM grounding validation, persistence, and
                   # the /api/v2 surface -- including the recommendation ->
                   # decision -> application -> outcome -> feedback loop:
                   # idempotent decisions/applications, immutable application
                   # events, the terminal-stage and "planned" transition
                   # guards, ownership checks, and no-double-counted analytics
                   # on retried requests.
                   # The whole suite runs with no API key and no network.
```

## Five decisions worth defending in an interview

**1. Why recommendation, decision, and outcome are different rows in
different tables, not one row with fields.** `rr_decisions` is what the
system predicted; `job_decisions` is what the user chose to do about it
(APPLY/SAVE/SKIP/DEFER); `rr_applications`/`rr_application_events` is what
actually happened. Collapsing any two loses information the other two
depend on: overwrite the recommendation with the outcome and you can never
again ask "was the *prediction* any good?" — which is exactly what
[§5's evaluation harness](docs/roleradar.md#5-closing-the-loop-outcome-based-evaluation)
exists to answer. `job_decisions.recommendation_id` is set once and frozen —
a later re-score of the same job cannot silently re-point an old decision at
a new scoring run (`store.save_job_decision`, "editing SAVE -> APPLY cannot
quietly re-point the decision at a newer, different scoring run"). The
dataclass in `models.py` is confusingly named `Decision` for what this README
calls a recommendation — a naming collision that predates this feature and
was deliberately not renamed (it would ripple through `ranking.py`,
`explain.py`, and every existing test for no behavioral gain), but it is
exactly the trap the rest of the schema is built to avoid repeating.

**2. Why application events are immutable.** `rr_application_events` has no
`update` or `delete` function anywhere in `store.py` — enforced by a test
that asserts those functions don't exist. An audit trail a client can edit
after the fact is not an audit trail. Two rules are enforced at the moment a
transition is requested, not trusted to callers: a terminal stage
(rejected/withdrawn/ghosted/offer) can never be advanced past
(`store.InvalidTransition`, surfaced as HTTP 409), and re-posting the stage
an application is already on is a no-op rather than a duplicate row —
required for idempotency under retry, and covered by tests that POST the
same transition three times and assert exactly one event resulted.

**3. Why the recommendation/model version is persisted with every
prediction.** `store.model_version()` fingerprints the exact ranking weights
and threshold in force and is stored on every `rr_decisions` row. Re-scoring
a job six months later would use today's weights and today's resume — which
measures whatever the ranker currently is, not what the user actually acted
on. Without the version pinned at prediction time, an evaluation run months
later silently mixes predictions from two different rankers and attributes
the blended result to neither.

**4. Why AI does not determine the whole score.** The verdict is computed by
deterministic code — a hard-constraint gate, graded/cited skill matching, and
published weights (`GET /api/v2/model`) — before the LLM ever runs. The model
only writes prose about an already-final result, and `explain.validate_grounding`
deletes any sentence that cites no evidence, cites an evidence id it was never
given, or states a number absent from the evidence it cites. This is a direct
response to the standard failure mode of "AI job matchers": an eligibility
question scored instead of gated (a role that can't sponsor still shows a
0.82 "strong match"), and a model free to invent "3 years of experience" the
resume never claims. See [§1 of the design doc](docs/roleradar.md#1-why-this-is-not-chat-with-your-resume).

**5. How offline evaluation differs from real-user outcome evaluation.**
The benchmarks under `/evaluation` and `outcomes.py`'s NDCG/precision/lift/
Brier/calibration functions are unit-tested against synthetic and hand-built
cases — that proves the *metric code* is correct, not that the *ranker* is
good. Real evaluation requires real applications with real logged outcomes
joined back to the prediction that was live when the user acted
(`store.scored_outcomes`), and none have been collected yet — stated plainly
in [`docs/roleradar.md` §5](docs/roleradar.md#5-closing-the-loop-outcome-based-evaluation)
rather than papered over with a synthetic number. The harness also encodes
choices that only matter once real data exists: furthest stage reached (not
latest — a rejection after an onsite is a ranking success, not a failure),
metrics withheld below `MIN_SAMPLE = 10`, and NDCG over an all-zero outcome
list returning `0.0` rather than the technically-correct `1.0`, because
reporting "perfect" to a user who has heard from nobody would be a lie.

## Roadmap

**RoleRadar V2 is the consolidation, not a second product.** JobEngine's ingest,
dedup, sponsorship index and search remain the foundation; the decision layer
was added on top rather than started as a parallel app. The next step is not
more features — it is *data*: the ranking evaluation harness exists and is
tested, but until real applications produce real outcomes, no metric from it
can be published. See [`docs/roleradar.md`](docs/roleradar.md) §5.

**Autofill assist** — fills the candidate's saved details into a form *they*
opened; they review and submit. Human-in-the-loop by design. The tracker and
API above already cover the "where did I apply, what happened" half; this is
the one remaining piece.

### What this deliberately does not do

No automated mass-submission on LinkedIn or company ATS portals. LinkedIn's
User Agreement bars automated access/actions, and there's no public
job-application API endpoint to use legitimately — building that risks the
account a candidate needs to actually get hired. Autofill stays
human-in-the-loop instead, and cold mass-apply is the lowest-yield channel in
this market regardless.

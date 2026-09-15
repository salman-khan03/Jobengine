# RoleRadar V2 — evidence-grounded job intelligence

JobEngine answers *"which roles exist, and who sponsors?"*
RoleRadar answers *"should **I** apply to **this** role, and why?"* — with every
claim traceable to a line of the candidate's own resume or a line of the posting.

This document covers the decision layer (`src/roleradar/`). The ingest pipeline,
deduplication, sponsorship index and HTTP/Spring services are in
[architecture.md](architecture.md).

---

## 1. Why this is not "chat with your resume"

The common shape of an AI job tool is: embed the resume, embed the job, take a
cosine similarity, and ask a model to write an encouraging paragraph. Three
things go wrong with that, and all three matter more for a *decision* than for a
search result:

| Failure | Consequence |
| --- | --- |
| Eligibility is scored, not gated | A role that cannot sponsor gets a 0.82 "strong match". The candidate spends an application they can never convert. |
| Similarity has no notion of evidence | "Postgres" in a skills list scores the same as three years of shipped Postgres work. The tool rewards keyword stuffing. |
| The model writes the verdict | Nothing stops it inventing "3 years of Python experience". The user cannot tell which sentences are grounded. |

RoleRadar inverts all three: **eligibility can veto**, **evidence is graded and
cited**, and **the model never decides anything** — it writes prose about an
already-final structured result, and unsupported sentences are deleted before
a human sees them.

---

## 2. The pipeline

```
resume.json                              job posting (+ JD text)
     |                                              |
     v                                              v
evidence.py                                  requirements.py
 verbatim units, each tagged with            hard constraints  +  gradable
 the JSON path it came from                  requirements, each tagged with
 (projects[0].bullets[2])                    the line it came from (jd:L42)
     |                                              |
     |                    +-------------------------+
     |                    v
     |            constraints.py  --- blocked? ---> decision short-circuits
     |                    | ok / risk
     v                    v
skills_match.py   requirement x evidence -> coverage rows, each citing
                  the evidence ids that back it (or explicitly "missing")
                          |
                          v
                   ranking.py   weighted, bounded, published weights
                          |
                          v
                   explain.py   LLM writes prose; validate_grounding deletes
                                any claim without a supporting citation
                          |
                          v
                      Decision  -> store.py -> outcomes.py -> ranking evaluation
```

Stage order is load-bearing:

- The **gate runs before scoring**, so a blocked role costs almost nothing to
  evaluate — which is what makes scoring a whole 32k-row result set practical.
- The **LLM runs last**, over a finished result, so it cannot influence the
  verdict even if it wanted to.
- **Evidence is extracted once per candidate**, not once per job, so batch
  ranking is linear in postings rather than in postings x resume bullets.

---

## 3. The grounding contract

This is the part worth defending in an interview.

### Candidate side — nothing is rewritten

An `EvidenceUnit` is a *verbatim* slice of `resume.json` plus the JSON path it
came from. No paraphrasing, no LLM "enhancement" of bullets. The moment text is
rewritten, provenance becomes a lie: the citation would point at a bullet the
candidate never wrote. (JobEngine's `metrics_audit.py` exists to *catch*
inflated resume claims — it would be incoherent for RoleRadar to generate them.)

Evidence ids are content-addressed (`ev_proj_5a63a93e`), not positional, so
reordering projects does not invalidate citations stored in decisions months
earlier.

### Job side — provenance per line

Every `HardConstraint` and `Requirement` records `source="jd:L42"`, so the UI can
highlight the exact sentence behind a blocker rather than asserting it.

### Model side — cite or be deleted

`explain.validate_grounding` drops a claim when it:

1. cites no evidence at all,
2. cites an `evidence_id` that was never supplied, or
3. contains a **number that appears nowhere in the evidence it cites**.

Rule 3 is the one that catches the realistic failure. A model asked to sell a
candidate will write *"you have 3 years of Python experience"* from a resume
that never says so. Here the sentence cites an id, the validator scans that
evidence text for "3", does not find it, and drops the sentence. The unvalidated
`summary` field is held to the same numeric standard against the union of all
supplied evidence, because one unchecked sentence is exactly where a fabricated
number would survive.

Dropped claims are **returned, not swallowed**, so the rejection rate is
measurable. A grounding checker whose rejections are invisible is
indistinguishable from one that never rejects anything.

If nothing survives — or there is no API key at all — the deterministic template
is used. That template is not a degraded mode; it is the floor the LLM has to
beat, and it is what CI exercises (the whole test suite runs with no key and no
network).

---

## 4. Scoring

### Hard constraints: three-way, never two-way

```
blocked -> disqualifying, verdict short-circuits
risk    -> real but survivable, scored as a capped penalty
ok      -> satisfied, shown green so the user sees it was checked
```

`unknown` is never promoted to `ok`. If the candidate has not stated their work
authorization, a no-sponsorship posting yields a **risk** plus "tell us your
status for a definite answer". Guessing "blocked" hides real opportunities;
guessing "ok" wastes real applications. The system declines to guess.

Work authorization is also never *inferred* — not from name, not from school.
Unreliable and discriminatory, in that order.

Notable judgement calls, all encoded as tests:

| Constraint | Behaviour | Why |
| --- | --- | --- |
| "must be authorized to work" | risk, not block, for an F-1 candidate | CPT/OPT *is* work authorization; only a sponsorship ban disqualifies |
| "active TS/SCI clearance" | block | cannot be obtained by applying |
| "ability to obtain a clearance" | risk | employer-sponsorable |
| "Master's degree required" | risk | postings routinely over-state degree bars |
| on-site elsewhere, open to relocating | risk | a cost, not a blocker |

Risk penalties cap at 0.30 — risks are correlated, and letting four soft flags
sum to a veto would quietly re-create the blocking behaviour this stage exists
to separate out.

### Evidence grading

| Evidence | Score | Example |
| --- | --- | --- |
| Demonstrated, named outright | 1.00 | "Built X in Postgres" vs a Postgres requirement |
| Demonstrated, implied | 0.75 | "Built X with pgvector" vs a Postgres requirement |
| Listed in a skills section | 0.55 | "Databases: Postgres" |
| Listed, implied | 0.40 | |
| Absent | 0.00 | cites nothing, by construction |

The 1.00 / 0.55 gap is the honesty mechanism: a skills-section keyword is a
claim, not proof. The UI surfaces it as *"listed, not demonstrated"*, which is
also the most actionable feedback the product gives.

**Implication graph.** `IMPLIES` encodes only relationships true by construction
— you cannot have used Next.js without React — never co-occurrence (Docker does
not imply Kubernetes). Implied matches are discounted relative to a skill named
outright and the rationale says which.

**Disjunctions.** "Python or Go" is **one** requirement with two acceptable
answers. Scoring it as two requirements is how a matcher concludes a Python
developer is a 50% fit for a Python job. Detection is conservative — an explicit
disjunction token with no conjunction in the line — because a false positive
merges two genuine requirements and forgives a real gap.

### Composition

```
score = 0.50 * required_coverage
      + 0.15 * preferred_coverage
      + 0.20 * semantic_similarity
      + 0.15 * seniority_fit
      - risk_penalty                     (clamped to 0..1)
```

Published live at `GET /api/v2/model`. A scoring system users are asked to act
on should not be a black box.

Why hand-set weights: a learned ranker needs labelled outcomes, and on day one
there are none. The honest move is to ship a transparent prior, log every
decision, and let §5 measure whether the ordering actually predicts interviews.
These weights are exactly what a fitted model would replace, and the evaluation
harness is already the thing that would prove the replacement better.

Semantic similarity is capped at 20% because the embedding is a hashing-trick
vector (`jobengine/embeddings.py`), not a trained sentence encoder — good for
tie-breaking between two plausible roles, not for overriding a missing required
skill.

### Verdict

```
gate failed                                       -> blocked
score >= 0.70 AND required_coverage >= 0.60       -> apply
score >= 0.45                                     -> stretch
otherwise                                         -> skip
```

The `required_coverage >= 0.60` floor exists because a strong average hides
fatal holes: 0.9 on nine requirements and 0.0 on the tenth still averages well.

**Confidence is reported separately and never feeds the score.** A listing with
no description can be a genuine 0.8 match on title alone, but the user deserves
to know the system worked from three extracted requirements rather than
twenty-five.

---

## 5. Closing the loop: outcome-based evaluation

```
predicted match -> application -> OA -> interview -> offer/reject
                                              |
                                     ranking evaluation
```

A recommender never scored against reality is a decorated guess. Decisions are
persisted **as predicted at the time** (`rr_decisions`, including the
`model_version` that produced them) because re-scoring a job six months later
uses today's weights and today's resume — which measures whatever the ranker
currently is, not what the user acted on.

| Metric | Question it answers |
| --- | --- |
| **NDCG@k** | Is the *ordering* right? The headline number, because the core claim is "the right roles rank first". |
| **Precision@k / lift@k** | Of the k roles recommended, how many progressed — and is that better than applying in random order? Lift is the honest framing: precision 0.30 sounds mediocre until the base rate is 0.08. |
| **Brier + calibration** | When the system says 0.8, do 80% progress? A model can rank perfectly and be badly calibrated; calibration is what makes a number safe to *show*. |
| **Spearman** | Rank correlation across the whole list, not just the top. |

Design decisions that keep the numbers honest:

- **Positive = reached an OA or beyond.** A plain rejection tells you almost
  nothing (headcount, timing, noise); an OA means the resume cleared a filter.
- **Furthest stage, not latest stage.** Nearly every application ends in
  "rejected". An application rejected *after an onsite* is a ranking success.
- **One row per job, not per event.** Otherwise a chatty user's single lucky
  application dominates every metric.
- **Metrics are withheld below `MIN_SAMPLE = 10`**, with the reason stated,
  rather than printing a confident number computed from four applications.
- **NDCG over an all-zero outcome list returns 0.0, not 1.0.** The
  technically-correct "perfect match to an all-zero ideal" would report success
  to a user who has heard back from nobody.
- Lift at or below 1.0 is **reported as such**: "the ranking is not yet beating
  random order on your data. That is a real result, not a bug."

> **No evaluation numbers are published anywhere in this repo.** The harness is
> built and tested against synthetic and hand-built cases; real metrics require
> real applications with real outcomes, and none have been collected. Any figure
> quoted before that happens would be fabricated.

---

## 6. Surfaces

### CLI

```bash
roleradar profile set --resume resume.json --needs-sponsorship
roleradar decide --company Stripe --match backend --jd-file jd.txt --llm --save
cat jd.txt | roleradar decide --company Acme --title "SWE Intern"
roleradar rank --grad newgrad --tier offers,very_high --limit 20 --save
roleradar outcome add --job-key <key> --stage interview
roleradar evaluate
```

Also reachable as `jobengine radar <subcommand>`. Like JobEngine's `track`, the
CLI is unauthenticated and writes `user_id = NULL` rows, invisible to the
multi-user HTTP API.

`decide` uses an LLM when a key is present; `rank` never does. That asymmetry is
the cost model made visible: explaining one role you asked about is worth an API
call, explaining 200 you have not opened is not.

### HTTP (`/api/v2`, mounted on the existing FastAPI app)

| Route | Auth | Notes |
| --- | --- | --- |
| `POST /decide` | **optional** | Anonymous when the body carries its own resume. Nothing stored. |
| `POST /rank` | required | Batch; never calls an LLM regardless of request. |
| `GET/POST /profile` | required | |
| `GET /evidence` | required | Every citable unit — citations are only trustworthy if the corpus is inspectable. |
| `POST /outcomes`, `GET /outcomes/funnel` | required | Legacy convenience: log a stage for a job_key directly, no decision required first. Backed by the same tables as the routes below. |
| `POST /jobs/{job_key}/decisions` | required | APPLY / SAVE / SKIP / DEFER. Idempotent by (user, job) — a retried POST upserts, never duplicates. |
| `PATCH /decisions/{id}` | required | Edit an existing decision (e.g. SAVE → APPLY). 404s, not 403s, for another user's id. |
| `POST /applications` | required | Converts an APPLY decision into a tracked application. 400 if the linked decision is not APPLY. Idempotent by (user, job). |
| `GET /applications`, `GET /applications/{id}` | required | |
| `GET /applications/{id}/events` | required | The full immutable stage history. |
| `PATCH /applications/{id}/stage`, `POST /applications/{id}/events` | required | Append a stage transition. 409 once the application is terminal (rejected/withdrawn/ghosted/offer); re-posting the current stage is a no-op, not a new event. |
| `POST /recommendations/{id}/feedback` | required | Relevant (bool) + reason enum. One active row per (user, recommendation) — a repeat POST upserts. |
| `GET /evaluation` | required | |
| `GET /model`, `GET /taxonomy` | public | The weights and the skill graph, published. |

v2 sits beside v1 rather than replacing it: the v1 endpoints already have a
frontend and a Spring Boot consumer.

### The decision / application / feedback loop, kept apart on purpose

Four concepts share this loop and are deliberately never collapsed into one
row or one table:

```
rr_decisions          RoleRadar's prediction ("recommendation" -- yes, the
                       dataclass is confusingly named Decision; see the note
                       at the top of store.py)
job_decisions          the user's APPLY / SAVE / SKIP / DEFER choice
rr_applications         whether they actually applied, and to what stage
rr_application_events   immutable history of what happened after
recommendation_feedback whether the recommendation itself was useful
```

Overwriting a recommendation with what the user did with it would make it
impossible to later ask "was the *prediction* any good?" — exactly the
question §5's evaluation harness exists to answer. So `rr_decisions` rows are
never edited by anything below this line; `job_decisions` links to one by
`recommendation_id` and freezes that link the first time it is set (a later
re-score cannot silently re-point an existing decision at a newer, different
scoring run); `rr_applications` denormalizes that same id again at the moment
the application is actually created, so it keeps pointing at the prediction
that was live when the candidate applied, not whatever `rr_decisions` holds
today.

`rr_application_events` is append-only: no function in `store.py` updates or
deletes a row in it. Two integrity rules are enforced at the point a stage
transition is requested, not left to callers: a terminal stage (rejected,
withdrawn, ghosted, offer) can never be advanced past, and `"planned"` — the
bootstrap stage a fresh application starts in — can never be re-entered later,
since that would erase apparent progress from the current-stage summary while
the event history underneath it kept disagreeing. Both a repeated POST of the
same stage and a repeated POST of the same decision are idempotent no-ops
rather than new rows — verified by tests that POST the same thing three times
and assert exactly one row/one analytics event resulted.

### Web

`/radar` — paste a JD, get the verdict, expand any requirement row to see the
verbatim resume text and JSON path behind it, plus the score arithmetic as a
table. Runs signed-out.

---

## 7. LLM provider

Provider-agnostic over Gemini / Groq / OpenRouter (`ROLERADAR_LLM_PROVIDER`, or
auto-detected from whichever key is present), via `urllib` rather than three
vendor SDKs — zero added dependencies, uniform failure modes.

Every entry point returns `None` instead of raising on *any* failure: no key, no
network, timeout, rate limit, malformed body. Callers treat `None` as "write the
deterministic version". Retries only on transient classes (429/5xx); a 400 means
the request is wrong and retrying burns quota twice. Responses are
content-addressed and cached on disk so iterating on prompts does not re-bill
the same tokens.

---

## 8. Known limitations

- **Most aggregated listings ship no description.** Without JD text the
  extractor degrades to title + listing metadata; `confidence` drops accordingly
  and the CLI says so explicitly.
- **The taxonomy is hand-curated (~90 skills).** It covers the SWE intern /
  new-grad postings this pipeline ingests. A scraped 10,000-skill ontology would
  look more impressive and be less defensible.
- **Years-of-experience matching uses coarse seniority bands**, not dates parsed
  from the resume. Overlapping internships make a precise figure spurious, and
  fake precision invites treating noise as signal.
- **Semantic similarity is feature hashing, not a trained encoder.** Deliberate
  (offline, no key, explainable) and the reason its weight is capped at 0.20.
- **The ranker is unvalidated.** No outcome data exists yet. The evaluation
  harness is built and tested; it has not been *run on reality*.
- **Constraint extraction is regex over prose.** It is tested against many real
  phrasings — including every contraction of "cannot sponsor" — but a posting
  that states a restriction in an unusual way will be missed. The gate degrades
  to "no constraint found", which is why sponsorship is *also* sourced from H-1B
  filing history rather than from JD prose alone.

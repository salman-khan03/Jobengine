# Public communication drafts

**Status: drafts. Nothing here has been published.** Every number is a
placeholder marked `[MEASURED: ...]` pointing at where the real figure comes
from, or `[NOT YET MEASURED]` where none exists. Publishing any of this with a
placeholder still in it would be exactly the failure
`metrics_audit.py` exists to prevent.

---

## 1. Demo video script (60–90 seconds)

Record at 1280×800. No music, no intro card — get to the product in five
seconds.

**0:00–0:10 — The problem, concretely.**
> "Simplify lists about 32,000 internship and new-grad roles. For an
> international student, the only question that matters first is: does this
> employer sponsor? Simplify's own sponsorship field says 'Other' on about 99%
> of listings. So you're applying blind."

*Screen: the raw listings feed, scrolling. Highlight the `Other` field.*

**0:10–0:25 — What it does.**
> "JobEngine cross-references every employer against public Department of Labor
> H-1B filings and attaches a sponsorship tier the source data doesn't have."

*Screen: `/jobs`, filter to `very_high`. Show the LCA match count on a card.*

**0:25–0:45 — The honest bit. Do not cut this.**
> "This is a signal, not a promise. It tells you a company has sponsored
> before — not that they'll sponsor this role. The match count is on every
> card so you can judge the evidence yourself."

*Screen: a card showing tier plus filing count.*

**0:45–1:05 — The engineering.**
> "Python runs the ingest pipeline: 32,000 records deduplicated and annotated
> in about five seconds. A Spring Boot service serves search behind a Redis
> cache. Adding the second service immediately caught a bug the first one
> couldn't see — a timestamp column that overflows in 2038."

*Screen: the architecture diagram, then the Hibernate validation error.*

**1:05–1:20 — Close.**
> "Live demo and full engineering docs, including everything that's still
> wrong with it, are linked below."

*Screen: `/dashboard` showing real request metrics.*

**Do not say:** "AI-powered," "revolutionizes," or any adoption number until
the user study in [`user-study.md`](user-study.md) has actually run.

---

## 2. Technical article outline

**Working title:** *The second service found a bug the first one couldn't see*

Not "How I built a job board." The bug story is the only genuinely interesting
thing here, and it is true.

**Structure:**

1. **The setup** (200 words). Sponsor-aware job search, one Python service,
   SQLite locally and Postgres deployed. Everything passing.
2. **The split** (300 words). Adding Spring Boot for the read path. Be honest
   that the motivation was partly to work in a second stack — ADR-009 already
   says so — and lay out the real costs: two deployments, two dependency trees,
   a network hop, and an unresolved question about which service owns auth.
3. **The refusal to boot** (400 words). The Hibernate error verbatim. Why
   `int4` versus `bigint` matters when the column holds epoch seconds. Why
   SQLite's dynamic typing meant no Python test could ever have caught it.
4. **The wider point** (300 words). A schema is a contract, and a contract with
   one reader is not being checked. `ddl-auto: validate` is a second reader.
   This generalizes beyond Java: any strict consumer of a loose schema does it.
5. **The two bugs I put in myself** (400 words). The rate limiter I benchmarked
   instead of the search path; the cache that couldn't be turned off because an
   explicit `@Bean` silently overrode `spring.cache.type=none`. Emphasize that
   the second one's failure mode is *publishing a false number*.
6. **Numbers, with caveats** (200 words). The measured table, then the caveats
   in the same breath — single laptop, untuned JVM, 12-query test mix.
7. **Would I do it again?** (200 words). For the bug, yes. For the throughput,
   no — Postgres alone served 777 req/s on this dataset, which is more than
   this project will ever need.

**Target:** ~2,000 words. Publish on a personal blog and cross-post to
dev.to. Link the repository and `docs/measurements.md` so claims are checkable.

---

## 3. Short architecture explanation (for a README header or a talk)

> JobEngine has three parts with deliberately different shapes.
>
> A **batch pipeline** in Python fetches two public job feeds, canonicalizes
> company names and URLs so the same posting from two sources collapses into
> one row, and cross-references each employer against Department of Labor H-1B
> filings. It's judged on throughput: about 32,000 records in five seconds.
>
> An **online API** in Spring Boot serves filtered search behind a Redis
> read-through cache, with a bounded connection pool, token-bucket rate
> limiting, and API keys. It's judged on p95 latency.
>
> A **Next.js frontend** talks to both.
>
> The split runs along the batch/online line rather than by feature, because
> those two halves fail differently, scale differently, and are measured
> differently. Deduplication deliberately stayed in Python: it depends on
> normalization logic tuned against real messy data, and two normalizers that
> must agree forever is how a polyglot system develops a silent correctness bug.

---

## 4. LinkedIn post draft

> Most job boards can't answer the first question an international student has:
> will this employer sponsor me?
>
> Simplify lists ~32,000 internship and new-grad roles. Its own sponsorship
> field reads "Other" on roughly 99% of them.
>
> So I built JobEngine. It cross-references every employer against public DOL
> H-1B filings and attaches the sponsorship signal the source data is missing.
> Python handles ingest — 32,000 records deduplicated and annotated in about
> five seconds. A Spring Boot service serves search behind Redis.
>
> The most useful thing I learned had nothing to do with the feature list.
> Adding the second service caught a bug the first one structurally couldn't:
> a timestamp column typed as a 32-bit int, holding Unix epoch seconds,
> overflowing in 2038. SQLite's dynamic typing hid it from every Python test.
> Hibernate's schema validator refused to start and pointed straight at it.
>
> A schema with one reader isn't being checked.
>
> I also found two bugs I'd introduced myself, both while trying to benchmark
> honestly — including a cache that ignored its own off-switch, which would
> have turned a "before/after" comparison into two identical runs.
>
> Everything is documented, including the parts that don't work yet: the
> sponsorship match accuracy is unmeasured, there's no rate limiting on the
> Python auth endpoint, and the load-test numbers come from a single laptop.
>
> Repo and full engineering docs: [link]
>
> #softwareengineering #java #python #opensource

**Before posting, confirm:** no adoption numbers (the study hasn't run), the
2038 bug is described accurately, and the limitations paragraph stays in. It is
the paragraph that makes the rest credible.

---

## Publication checklist

- [ ] Every `[MEASURED: ...]` placeholder replaced with a real figure and its source
- [ ] Every `[NOT YET MEASURED]` either measured or the claim deleted
- [ ] Live demo URL responding, demo account working, seeded data present
- [ ] `docs/measurements.md` linked from anywhere a number appears
- [ ] Limitations paragraph present in every public artifact
- [ ] `JOBENGINE_SECRET_KEY` and `JOBENGINE_CORS_ORIGINS` set on the deployment
- [ ] No credentials in the repository (`infra/terraform.tfvars` is gitignored)

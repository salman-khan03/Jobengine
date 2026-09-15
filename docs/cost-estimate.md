# Cost estimate

Figures are **list prices as published by each provider, not invoices I have
paid.** Nothing here has been billed yet. Where a price depends on usage I've
stated the assumed usage. Verify against current pricing pages before relying
on any of it — cloud pricing changes and these numbers will age.

Assumed workload for every scenario below:

- ~35,000 job rows, rebuilt daily (~50MB of data, ~200MB with indexes)
- 4 data-refresh runs per day, ~2 minutes each
- 50–500 requests/day at portfolio scale; 50k/day at the "real traffic" scale
- Fewer than 100 registered users

---

## Option A — Railway / Render / Fly.io (recommended, and what DEPLOY.md targets)

| Item | Spec | Monthly |
|---|---|---|
| API service | 512MB RAM, shared CPU | $5 |
| PostgreSQL | 1GB storage, 256MB RAM | $5 |
| Frontend (Vercel Hobby) | Static + edge | $0 |
| Scheduled refresh | Cron on the same instance | $0 |
| **Total** | | **~$10/mo** |

Free tiers cover this entirely at portfolio traffic on Fly.io and Render's free
plan (which sleeps after inactivity — fine for a demo, visibly bad in an
interview when the first page load takes 30 seconds; worth the $5 to avoid).

**Why this is the recommendation.** The workload is one small stateful service
plus one small database. Everything AWS adds below is operational surface this
workload does not need.

---

## Option B — AWS, minimal (what the IaC in `infra/` provisions)

| Service | Spec | Monthly | Free tier? |
|---|---|---|---|
| RDS PostgreSQL | `db.t4g.micro`, 20GB gp3, single-AZ | ~$13 | 750h free for 12 months |
| ECS Fargate | 0.25 vCPU, 0.5GB, always on | ~$9 | No |
| Application Load Balancer | 1 ALB, minimal LCUs | ~$18 | No |
| EventBridge Scheduler | 4 invocations/day | ~$0 | Effectively free |
| Lambda (refresh job) | 120 invocations/mo, 2 min, 512MB | ~$0.10 | 1M requests free |
| CloudWatch Logs | ~1GB ingest, 7-day retention | ~$0.55 | 5GB free |
| CloudWatch alarms | 5 alarms | ~$0.50 | 10 free |
| Secrets Manager | 2 secrets | ~$0.80 | No |
| Data transfer | ~10GB out | ~$0.90 | 100GB free |
| **Total (year 1, with free tier)** | | **~$29/mo** | |
| **Total (steady state)** | | **~$43/mo** | |

**The ALB is the single largest line item** — more than the database and
compute combined. At this traffic it exists purely to terminate TLS and provide
a stable hostname. Alternatives: API Gateway HTTP API (~$1/mo at this volume,
but no persistent connections), or a Fargate task with a public IP and TLS
terminated in-process (cheaper, no health-check-driven replacement).

**Cost-reduction levers, in order of impact:**

1. Drop the ALB for API Gateway HTTP API: **−$17/mo**
2. Aurora Serverless v2 scaling to zero instead of always-on RDS: **−$8/mo**
   at this duty cycle (but adds cold-start latency on the first request)
3. Fargate Spot for the API: **−~65% of compute**, at the cost of interruptions
4. CloudWatch log retention 7 days instead of never-expire: already assumed;
   the default of "never expire" is a slow, silent cost leak

---

## Option C — AWS, production-shaped

What this would cost if it needed to actually stay up. Listed to show the
difference is understood, **not** as something to build now.

| Change | Added monthly |
|---|---|
| Multi-AZ RDS (automatic failover) | +$13 |
| Second Fargate task (no single point of failure) | +$9 |
| RDS read replica | +$13 |
| Automated backups, 7-day PITR | +$2 |
| CloudWatch Container Insights | +$8 |
| **Total** | **~$88/mo** |

Roughly 3× the minimal setup and 9× Railway, for availability guarantees a
portfolio project does not need. Knowing where that money goes is the point.

---

## Non-infrastructure costs

| Item | Cost | Notes |
|---|---|---|
| Domain | ~$12/yr | |
| OpenRouter (optional LLM polish) | ~$0.001–0.01 per cover letter | Opt-in; the pipeline runs fully offline without it |
| Embeddings | $0 | Computed locally, not via a paid API |
| DOL + SimplifyJobs data | $0 | Public |
| GitHub Actions CI | $0 | Free for public repositories |

## Recommendation

Run the live demo on **Option A (~$10/mo)**. Keep the AWS IaC in the repository
as the deployable-but-not-deployed path, because the interesting part is the
scheduled pipeline and the CloudWatch alarms, and those are worth being able to
show and explain regardless of where the demo actually runs.

Deploying Option B just to say "it's on AWS" would cost 3–4× more for a
strictly worse demo experience. Being able to explain *that* tradeoff is worth
more than the AWS logo.

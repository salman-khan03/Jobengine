# OPT Job Search & Interview Prep — Salman Khan

## 1. JobEngine: Targeting Confirmed-Sponsorship Roles

Use your existing pipeline — just filter on the sponsorship field instead of building anything new.

```bash
jobengine fetch --source simplify --refresh
jobengine query --sponsorship=confirmed --role="software engineer,AI engineer,backend engineer" --grad-year=2027
```

**If `--sponsorship` flag doesn't exist yet:**
Add a filter step before role/grad-year filtering:
```python
df = df[df['sponsorship_status'] == 'confirmed']  # or your DOL-matched field name
```

**Before sending any application:**
Run your audit harness on `tailor` output — same no-fabrication gate already built into JobEngine.

**Verification sources for any company not in your pipeline yet:**
- MyVisaJobs.com — sponsorship history by employer
- H1BData.info — salary + approval data
- USCIS H-1B Employer Data Hub — official approval counts

---

## 2. Capital One Workshop Prep (July 6–7)

**30-second intro:**
"Hi, I'm Salman — CS major at North American University, graduating May 2027. I've spent this year building production systems rather than chasing internships: an AI job-tracking pipeline that cross-references 35k listings against DOL H-1B sponsorship data, and a full-stack fitness app with a RAG-based AI coach. I'm here to understand how your assessments actually evaluate candidates so I can prepare the right way."

**Lead project if asked:** JobEngine (most relevant to fintech audience — data pipelines, decision-support logic, "don't trust the obvious signal" problem-solving).

**Day 1 (Coding Assessment) questions:**
- "What's the most common reason a technically correct submission still doesn't pass review?"
- "Do you weight problem-solving approach or final runtime more heavily?"

**Day 2 (Recruiter Q&A) questions:**
- "What does a strong application look like from someone without a prior internship?"
- "Anything CodePath students specifically should do to stand out when applications open this fall?"

**Skip:** sponsorship questions — Capital One and Mutual of Omaha both confirmed no international sponsorship. Don't ask; it signals you didn't read the materials.

---

## 3. General Big-Tech New-Grad Interview Script

**"Tell me about yourself":**
CS major, May 2027, Houston-based, open to relocation. Lead with what you've shipped, not coursework: "Most of my experience comes from building and deploying full-stack systems on my own — JobEngine, FitForge, DevScout — rather than a traditional internship."

**"Why this company?"**
Reference something specific and recent (blog post, eng podcast, stack choice) — not generic culture language.

**"Tell me about a challenge":**
The SimplifyJobs 97%-unknown-sponsorship-data problem from JobEngine — identifying a flawed data assumption and redesigning around it.

**Technical — be ready to defend your own architecture decisions:**
- Async SQLAlchemy 2.0 + `selectinload` (avoiding lazy-load failures)
- Direct bcrypt over passlib (known compatibility issue)
- Stripe webhooks as sole source of subscription truth
- Server-authoritative pricing

Practice explaining *why X over Y*, not just what was built — interviewers probe tradeoffs more than features.

**Visa question — when it comes up, not if:**
"I'm on F-1 OPT with STEM extension eligibility, so I can work full-time for up to 3 years before any H-1B sponsorship is needed." Short, confident, signals zero short-term cost.

**Closing questions to ask them:**
- "What does the path from new grad to senior engineer look like on this team?"
- "What's a recent technical decision you wish you'd made differently?"

---

## Quick Pre-Session Checklist
- [ ] Resume tailored to company stack, audit-harness checked
- [ ] 2–3 specific things noticed about their engineering (blog, GitHub, talk)
- [ ] FitForge / DevScout live URLs ready to share if asked
- [ ] One architecture tradeoff story rehearsed out loud
- [ ] Visa answer rehearsed — short and confident, not apologetic

# User study protocol

**Status: not yet run. No participants, no results, no numbers.**

This document is the plan and the recording template. It exists so that when
the study happens, the numbers come out of a defined procedure instead of being
reconstructed afterwards from memory — which is how "8 out of 10 users said it
saved them time" gets written by someone who spoke to three friends.

Target: **5–15 participants**, international CS students facing the same
sponsorship-filtering problem the tool addresses.

---

## Why this design

The tempting version of this study asks people "was this useful?" and records
that they said yes. That measures politeness. Everything below is built around
two rules:

1. **Measure behavior, not opinion.** Task completion and time-on-task are
   observable. "Would you use this?" is not evidence.
2. **The comparison has to be fair.** Time saved is meaningless without a
   baseline measured the same way, on the same task, by the same person.

## Participants

| Criterion | Requirement |
|---|---|
| Status | Currently applying to SWE internships or new-grad roles |
| Visa | Requires sponsorship (F-1/OPT or equivalent) — the tool's actual audience |
| Exclusion | Anyone who has contributed to or previously seen this project |

Recruit through campus CS organizations and international student groups.
Recruiting only friends produces a biased sample; say so in the write-up if
that is what ends up happening.

## Session structure (~30 minutes)

**1. Consent and framing (3 min).** Tell them plainly: this is a course/portfolio
project, participation is voluntary, they can stop at any time, and no personal
data leaves the session. Explicitly say *"I want to find out where this fails,
so please don't be nice to it."* Without that sentence people report problems as
their own fault.

**2. Baseline task (10 min, timed).** Before showing them JobEngine:

> "Using whatever you normally use, find five new-grad software roles you'd
> actually apply to, where the employer has a history of sponsoring H-1B."

Record: wall-clock time, how many of the five they completed, what tools they
used, and where they gave up if they did.

**3. JobEngine task (10 min, timed).** Same task, same wording, using the tool.
Do not demo it first — hand them the URL and the demo account. Watching an
unguided first-run is where the real usability problems appear.

**4. Debrief (7 min).** Open questions only:

- Where did you get stuck?
- What did you expect to happen that didn't?
- What would stop you using this again?
- Was anything about the sponsorship information confusing or misleading?

The last one matters most: the product's core claim is a *signal*, not a
guarantee, and if users read "very_high" as "they will sponsor me," that is a
product defect regardless of how accurate the underlying data is.

## What gets recorded

Per participant, in `docs/user-study-results.md` (to be created when the study
runs):

| Field | Type | Notes |
|---|---|---|
| Participant ID | `P01`–`P15` | No names |
| Baseline task completed | yes / partial / no | "Partial" = fewer than 5 roles |
| Baseline time | mm:ss | Stop at 10 min |
| JobEngine task completed | yes / partial / no | |
| JobEngine time | mm:ss | Stop at 10 min |
| Errors encountered | count + description | Anything that blocked them |
| Misread sponsorship signal | yes / no | Did they treat tier as a guarantee? |
| Would use again | yes / no / unsure | Recorded, but weighted least |
| Verbatim quotes | text | Especially negative ones |

## Metrics derived from it

| Metric | Definition | Honest caveat to publish alongside |
|---|---|---|
| Task-completion rate | Completed ÷ attempted | Small n; report as a fraction ("7/9"), never as a percentage — "78%" implies a precision 9 people cannot support |
| Time saved | Median baseline − median JobEngine | Order effects: everyone does the baseline first, so they are more practiced at the task by the second run, which *understates* the tool's benefit. It also assumes both attempts are equally good, which is why completion rate is reported next to it |
| Error rate | Sessions with ≥1 blocking error ÷ total | |
| Signal misread rate | The comprehension failure above | The most important number here, and the one a demo would never surface |

**Report n every single time.** "Median time fell from 8:40 to 3:10 (n=9)" is a
finding. "60% faster" without n is marketing.

## Threats to validity, stated up front

- **Order effect.** Baseline always runs first. Counterbalancing needs two task
  variants and twice the participants; with n≤15 that trade isn't worth it, so
  the bias is documented instead of eliminated.
- **Experimenter presence.** I am in the room and I built the tool. People are
  measurably kinder in that situation.
- **Self-selection.** Volunteers from CS clubs are more technical than the
  general audience.
- **Novelty.** A 10-minute first impression says nothing about whether anyone
  uses it in week three.

## What would make me stop and rebuild

Defined in advance so the result can't be rationalized afterwards:

- If **more than a third** of participants read the sponsorship tier as a
  guarantee, the presentation is wrong and must change before anything ships.
- If JobEngine's completion rate is **not better** than baseline, the tool does
  not solve the problem it claims to, and that goes in the README.

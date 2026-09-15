"use client";

/**
 * RoleRadar — "Should I apply?", with the reasoning shown.
 *
 * The page is built around one claim: every statement about the candidate is
 * traceable to a line of their own resume. So the UI is not a score with a
 * paragraph under it — each requirement row expands into the exact evidence
 * that covered it, including the JSON path it came from. If a row cannot cite
 * anything, it renders as a gap rather than as a soft positive.
 *
 * It runs signed-out on purpose. The request carries its own resume, the
 * backend stores nothing, and a reviewer can see the full pipeline work
 * without creating an account.
 */

import { useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import DecisionJournal from "@/components/DecisionJournal";
import {
  api,
  Decision,
  EvidenceUnit,
  ModelInfo,
  SkillCoverage,
} from "@/lib/api";

const SAMPLE_RESUME = {
  name: "Sample Candidate",
  location: "Houston, TX",
  education: {
    school: "North American University",
    degree: "B.S. Computer Science",
    graduation: "May 2027",
    coursework: ["Data Structures", "Algorithms", "Databases"],
  },
  skills: {
    Languages: ["Python", "TypeScript", "Java", "SQL"],
    Frameworks: ["FastAPI", "Next.js", "Spring Boot"],
    Infrastructure: ["Docker", "AWS", "PostgreSQL", "Redis"],
  },
  projects: [
    {
      name: "JobEngine",
      stack: ["Python", "FastAPI", "PostgreSQL", "pgvector"],
      dates: "Jul 2026 - Present",
      bullets: [
        "Built an ingest pipeline that deduplicated 36912 raw listings into 36541 unique rows",
        "Added a Redis cache layer and cut p95 search latency 4.9x (71ms -> 14ms) under k6 load",
        "Wrote 286 automated tests covering the pipeline, auth, and the RoleRadar decision engine",
      ],
    },
    {
      name: "Portfolio Site",
      stack: ["Next.js", "Three.js", "Tailwind"],
      dates: "Mar 2026 - Jun 2026",
      bullets: ["Built an interactive 3D portfolio with React Three Fiber"],
    },
  ],
};

const SAMPLE_JD = `Software Engineer Intern, Backend

Minimum Qualifications
- Currently enrolled in a Bachelor's degree program in Computer Science
- Graduating between December 2026 and August 2027
- Strong programming skills in Python or Go
- Experience with SQL and relational databases
- Familiarity with Docker and containerized deployment

Preferred Qualifications
- Experience with Kubernetes
- Exposure to distributed systems

We are unable to provide visa sponsorship for this position.`;

const VERDICT_STYLE: Record<string, { label: string; color: string; blurb: string }> = {
  apply: { label: "APPLY", color: "var(--tier-very-high)", blurb: "Your evidence covers the required list." },
  stretch: { label: "STRETCH", color: "var(--tier-medium)", blurb: "Worth sending, with known gaps." },
  skip: { label: "SKIP", color: "var(--tier-low)", blurb: "Too little overlap to be worth the slot." },
  blocked: { label: "BLOCKED", color: "var(--tier-unknown)", blurb: "A hard requirement rules you out." },
};

const STATUS_COLOR: Record<string, string> = {
  strong: "var(--tier-very-high)",
  partial: "var(--tier-medium)",
  missing: "var(--tier-low)",
  ok: "var(--tier-very-high)",
  risk: "var(--tier-medium)",
  blocked: "var(--tier-low)",
  unknown: "var(--tier-unknown)",
};

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function CoverageRow({ cov, evidence }: { cov: SkillCoverage; evidence: Record<string, EvidenceUnit> }) {
  const [open, setOpen] = useState(false);
  const cited = cov.evidence_ids.map((id) => evidence[id]).filter(Boolean);

  return (
    <li className="border-b border-[var(--line)] last:border-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={cited.length > 0 ? open : undefined}
        disabled={cited.length === 0}
        className="flex w-full items-start gap-3 py-2 text-left disabled:cursor-default"
      >
        <span
          className="mt-1 h-2 w-2 shrink-0 rounded-full"
          style={{ background: STATUS_COLOR[cov.status] }}
          aria-hidden
        />
        <span className="flex-1">
          <span className="font-[family-name:var(--font-mono)] text-sm">
            {cov.skill ?? cov.requirement_text.slice(0, 48)}
          </span>
          <span className="ml-2 text-xs text-[var(--muted)]">
            {cov.importance} · {cov.status}
          </span>
          <span className="block text-xs text-[var(--muted)]">{cov.rationale}</span>
        </span>
        <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
          {cited.length > 0 ? (open ? "hide" : `${cited.length} cited`) : "no evidence"}
        </span>
      </button>

      {open && cited.length > 0 && (
        <ul className="mb-3 ml-5 space-y-2 border-l border-[var(--line)] pl-4">
          {cited.map((unit) => (
            <li key={unit.evidence_id} className="text-xs">
              <p className="text-[var(--text)]">&ldquo;{unit.text}&rdquo;</p>
              {/* The JSON path is the audit trail. It is shown, not hidden
                  behind a tooltip, because a citation nobody can check is
                  indistinguishable from a citation that does not exist. */}
              <p className="font-[family-name:var(--font-mono)] text-[var(--muted)]">
                {unit.kind} · {unit.source}
              </p>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function RadarPage() {
  const { data: session } = useSession();
  const token = session?.backendToken;
  const [saveDecision, setSaveDecision] = useState(false);
  const [useLlm, setUseLlm] = useState(false);
  const [journalVersion, setJournalVersion] = useState(0);
  const [jdText, setJdText] = useState(SAMPLE_JD);
  const [resumeText, setResumeText] = useState(JSON.stringify(SAMPLE_RESUME, null, 2));
  const [company, setCompany] = useState("Acme");
  const [title, setTitle] = useState("Software Engineer Intern");
  const [needsSponsorship, setNeedsSponsorship] = useState<"yes" | "no" | "unknown">("unknown");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showResume, setShowResume] = useState(false);

  const required = useMemo(
    () => (decision?.coverages ?? []).filter((c) => c.importance === "required"),
    [decision],
  );
  const preferred = useMemo(
    () => (decision?.coverages ?? []).filter((c) => c.importance !== "required"),
    [decision],
  );

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      let resume: unknown;
      try {
        resume = JSON.parse(resumeText);
      } catch {
        throw new Error("Resume must be valid JSON (resume.json format).");
      }
      const [result, info] = await Promise.all([
        api.decide({
          job: { title, company },
          jd_text: jdText,
          resume,
          save: Boolean(token && saveDecision),
          use_llm: useLlm,
          profile: {
            // Tri-state, deliberately: "unknown" is sent as null so the
            // backend flags sponsorship as a risk instead of deciding it.
            needs_sponsorship:
              needsSponsorship === "unknown" ? null : needsSponsorship === "yes",
          },
        }, token),
        model ? Promise.resolve(model) : api.getModelInfo().catch(() => null),
      ]);
      setDecision(result);
      setModel(info);
      if (result.decision_id) setJournalVersion((value) => value + 1);
    } catch (err) {
      setError(String((err as Error).message ?? err));
      setDecision(null);
    } finally {
      setLoading(false);
    }
  }

  const style = decision ? VERDICT_STYLE[decision.verdict] : null;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
      <header className="mb-8">
        <h1 className="font-[family-name:var(--font-display)] text-3xl sm:text-4xl">
          Should I apply?
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">
          Paste a job description. RoleRadar extracts its hard constraints and
          requirements, checks them against evidence pulled from your resume,
          and shows the citation behind every line of the answer. Nothing is
          stored — this runs without an account.
        </p>
      </header>

      <div className="mb-6 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4 text-sm">
        <span className="font-medium text-[var(--amber)]">Sample workspace</span>
        <p className="mt-1 text-[var(--muted)]">The candidate, project claims, company, and job description below are illustrative. Replace the sample resume with your own evidence before making a decision.</p>
      </div>
      <form onSubmit={run} className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">
          <span className="text-[var(--muted)]">Company</span>
          <input
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className="mt-1 w-full rounded border border-[var(--line)] bg-transparent px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="text-[var(--muted)]">Role title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded border border-[var(--line)] bg-transparent px-3 py-2"
          />
        </label>

        <label className="text-sm sm:col-span-2">
          <span className="text-[var(--muted)]">Job description</span>
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={12}
            className="mt-1 w-full rounded border border-[var(--line)] bg-transparent px-3 py-2 font-[family-name:var(--font-mono)] text-xs"
          />
        </label>

        <fieldset className="text-sm sm:col-span-2">
          <legend className="text-[var(--muted)]">Do you need visa sponsorship?</legend>
          <div className="mt-2 flex flex-wrap gap-4 font-[family-name:var(--font-mono)] text-xs">
            {(["yes", "no", "unknown"] as const).map((value) => (
              <label key={value} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="sponsorship"
                  checked={needsSponsorship === value}
                  onChange={() => setNeedsSponsorship(value)}
                />
                {value === "unknown" ? "prefer not to say" : value}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-[var(--muted)]">
            Never inferred. Left unset, a no-sponsorship posting is flagged as a
            risk rather than decided either way.
          </p>
        </fieldset>

        <div className="sm:col-span-2">
          <button
            type="button"
            aria-expanded={showResume}
            onClick={() => setShowResume((v) => !v)}
            className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)] hover:text-[var(--amber)]"
          >
            {showResume ? "Hide resume" : "Review / replace sample resume"}
          </button>
          {showResume && (
            <textarea
              aria-label="Resume evidence in JSON format"
              value={resumeText}
              onChange={(e) => setResumeText(e.target.value)}
              rows={16}
              className="mt-2 w-full rounded border border-[var(--line)] bg-transparent px-3 py-2 font-[family-name:var(--font-mono)] text-xs"
            />
          )}
        </div>

        <div className="space-y-3 rounded-lg border border-[var(--line)] p-4 text-sm sm:col-span-2">
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} className="mt-1" />
            <span>Use an AI explanation <span className="block text-xs text-[var(--muted)]">Optional: sends evidence and requirements to the configured Gemini/Groq provider. The match score stays deterministic.</span></span>
          </label>
          {token ? <label className="flex items-start gap-2">
            <input type="checkbox" checked={saveDecision} onChange={(e) => setSaveDecision(e.target.checked)} className="mt-1" />
            <span>Save this decision to my journal <span className="block text-xs text-[var(--muted)]">Stores this prediction and cited resume evidence in your account so you can track outcomes.</span></span>
          </label> : <p className="text-xs text-[var(--muted)]"><Link className="text-[var(--amber)] underline" href="/login">Sign in</Link> to save decisions and track applications. This preview is not saved.</p>}
        </div>
        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-[var(--amber)] px-4 py-2 font-[family-name:var(--font-mono)] text-sm text-[var(--ink)] disabled:opacity-50"
          >
            {loading ? "scoring…" : "score this role"}
          </button>
        </div>
      </form>

      {error && (
        <p role="alert" className="mt-6 text-sm text-[var(--status-warn)]">
          {error}
        </p>
      )}

      {decision && style && (
        <section id="decision-result" className="mt-10 space-y-8">
          <p className="text-xs text-[var(--muted)]" role="status">{decision.decision_id ? "Decision saved to your journal." : "Preview only. Not saved."} Match score measures evidence fit; it is not a probability of an interview or offer.</p>
          <div className="flex flex-wrap items-baseline gap-4 border-b border-[var(--line)] pb-4">
            <span
              className="font-[family-name:var(--font-display)] text-2xl"
              style={{ color: style.color }}
            >
              {style.label}
            </span>
            <span className="font-[family-name:var(--font-mono)] text-3xl">
              {Math.round(decision.score * 100)}
              <span className="text-base text-[var(--muted)]">/100</span>
            </span>
            <span className="text-sm text-[var(--muted)]">{style.blurb}</span>
            <span className="ml-auto font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
              confidence {pct(decision.confidence)}
            </span>
          </div>

          {decision.gate.verdicts.length > 0 && (
            <div>
              <h2 className="font-[family-name:var(--font-display)] text-lg">
                Hard constraints
              </h2>
              <p className="mb-2 text-xs text-[var(--muted)]">
                Checked before scoring. A blocker vetoes the role no matter how
                well the skills line up.
              </p>
              <ul className="space-y-1">
                {decision.gate.verdicts.map((v) => (
                  <li key={v.constraint_id} className="flex items-start gap-3 text-sm">
                    <span
                      className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                      style={{ background: STATUS_COLOR[v.status] }}
                      aria-hidden
                    />
                    <span>
                      <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
                        {v.kind} · {v.status}
                      </span>
                      <span className="block">{v.reason}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid gap-8 sm:grid-cols-2">
            <div>
              <h2 className="font-[family-name:var(--font-display)] text-lg">
                Required ({pct(decision.breakdown.required_coverage)} covered)
              </h2>
              <ul>
                {required.map((c) => (
                  <CoverageRow key={c.requirement_id} cov={c} evidence={decision.evidence} />
                ))}
                {required.length === 0 && (
                  <li className="py-2 text-sm text-[var(--muted)]">
                    No hard requirements were extractable from this description.
                  </li>
                )}
              </ul>
            </div>
            <div>
              <h2 className="font-[family-name:var(--font-display)] text-lg">
                Preferred ({pct(decision.breakdown.preferred_coverage)} covered)
              </h2>
              <ul>
                {preferred.map((c) => (
                  <CoverageRow key={c.requirement_id} cov={c} evidence={decision.evidence} />
                ))}
                {preferred.length === 0 && (
                  <li className="py-2 text-sm text-[var(--muted)]">None listed.</li>
                )}
              </ul>
            </div>
          </div>

          <div>
            <h2 className="font-[family-name:var(--font-display)] text-lg">The write-up</h2>
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded border border-[var(--line)] p-4 font-[family-name:var(--font-mono)] text-xs">
              {decision.explanation}
            </pre>
            <p className="mt-1 text-xs text-[var(--muted)]">
              {decision.explanation_source === "llm"
                ? "AI commentary includes citation and numeric checks. Those checks do not prove factual accuracy; inspect the evidence. The computed verdict, blockers, and gaps remain authoritative."
                : "Deterministic write-up. AI was disabled or unavailable, or its response did not pass grounding checks."}
            </p>
          </div>

          <div>
            <h2 className="font-[family-name:var(--font-display)] text-lg">How the number was built</h2>
            <table className="mt-2 w-full text-left font-[family-name:var(--font-mono)] text-xs">
              <thead className="text-[var(--muted)]">
                <tr>
                  <th className="py-1">term</th>
                  <th className="py-1">value</th>
                  <th className="py-1">weight</th>
                  <th className="py-1">contribution</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["required_coverage", decision.breakdown.required_coverage],
                    ["preferred_coverage", decision.breakdown.preferred_coverage],
                    ["semantic_similarity", decision.breakdown.semantic_similarity],
                    ["seniority_fit", decision.breakdown.seniority_fit],
                  ] as const
                ).map(([term, value]) => {
                  const weight = decision.breakdown.weights[term] ?? 0;
                  return (
                    <tr key={term} className="border-t border-[var(--line)]">
                      <td className="py-1">{term}</td>
                      <td className="py-1">{value.toFixed(2)}</td>
                      <td className="py-1">{weight.toFixed(2)}</td>
                      <td className="py-1">{(value * weight).toFixed(3)}</td>
                    </tr>
                  );
                })}
                <tr className="border-t border-[var(--line)] text-[var(--status-warn)]">
                  <td className="py-1">risk_penalty</td>
                  <td className="py-1">—</td>
                  <td className="py-1">—</td>
                  <td className="py-1">-{decision.breakdown.risk_penalty.toFixed(3)}</td>
                </tr>
              </tbody>
            </table>
            {model && (
              <p className="mt-2 text-xs text-[var(--muted)]">
                Model {model.version}. {model.llm.used_for}.
              </p>
            )}
          </div>
        </section>
      )}
      {token && <DecisionJournal key={`${token}:${journalVersion}`} token={token} onInspect={setDecision} />}
    </div>
  );
}


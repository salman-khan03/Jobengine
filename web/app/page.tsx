"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, JobsSummary } from "@/lib/api";
import { TierChart } from "@/components/TierChart";
import { StatTile } from "@/components/StatTile";
import { Reveal } from "@/components/Reveal";
import { CursorSpotlight } from "@/components/CursorSpotlight";
import { DecisionTrail } from "@/components/DecisionTrail";

const INSTALL_CMD = 'docker compose up --build -d';

export default function LandingPage() {
  const [summary, setSummary] = useState<JobsSummary | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.getJobsSummary().then(setSummary).catch(() => setSummary(null));
  }, []);

  const ranked = summary
    ? ["very_high", "high", "offers", "medium", "low", "unknown"].reduce(
        (a, k) => a + (summary[k] ?? 0),
        0,
      )
    : null;
  const knownSponsors = summary
    ? (summary.very_high ?? 0) + (summary.high ?? 0) + (summary.offers ?? 0)
    : null;

  return (
    <div className="mx-auto max-w-5xl px-6">
      {/* ---------- hero ---------- */}
      <CursorSpotlight className="grid grid-cols-1 gap-12 py-16 md:grid-cols-[1fr_1.1fr] md:items-center md:py-20">
        <Reveal>
          <p className="mb-4 font-[family-name:var(--font-mono)] text-xs uppercase tracking-[0.14em] text-[var(--amber)]">
            ROLERADAR / EVIDENCE-GROUNDED JOB INTELLIGENCE
          </p>
          <h1 className="text-balance font-[family-name:var(--font-display)] text-4xl font-extrabold leading-[1.05] tracking-tight md:text-5xl">
            Your next application.{' '}
            <span className="text-[var(--amber)]">Backed by evidence.</span>
          </h1>
          <p className="mt-5 max-w-[44ch] text-[17px] text-[var(--muted)]">
            Turn your resume and a job description into a decision you can inspect.
            Check eligibility, trace skill matches to your work, and learn from
            what happens after you apply.
          </p>

          <div className="mt-7 flex w-fit items-center overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--panel)] font-[family-name:var(--font-mono)] text-sm transition-colors duration-200 hover:border-[var(--amber-dim)]">
            <code className="px-4 py-3 text-[var(--muted)]">
              <span className="text-[var(--amber)]">$ </span>
              {INSTALL_CMD}
            </code>
            <button
              onClick={() => {
                navigator.clipboard.writeText(INSTALL_CMD);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
              className="border-l border-[var(--line)] bg-[var(--panel-2)] px-4 py-3 text-xs text-[var(--muted)] hover:text-[var(--amber)]"
            >
              {copied ? "copied" : "copy"}
            </button>
          </div>

          <div className="mt-5 flex flex-wrap gap-5 font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            <Link href="/radar" className="rounded bg-[var(--amber)] px-4 py-3 font-semibold text-[var(--ink)] transition-transform duration-150 hover:scale-[1.03] active:scale-[0.98]">Try Should I Apply? →</Link>
            <span className="self-center">No account or AI key needed for the sample</span>
          </div>
        </Reveal>

        <Reveal delayMs={150} className="rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-6 transition-colors duration-300 hover:border-[var(--amber-dim)] sm:p-8">
          <p className="font-[family-name:var(--font-mono)] text-xs text-[var(--amber)]">THE DECISION TRAIL</p>
          <h2 className="mt-4 text-2xl font-semibold">Every match has a source.</h2>
          <DecisionTrail />
          <p className="mt-7 border-t border-[var(--line)] pt-4 text-xs text-[var(--muted)]">A transparent match score. An inspectable explanation. No invented hiring probability.</p>
        </Reveal>
      </CursorSpotlight>

      {/* ---------- live metrics ---------- */}
      <section id="metrics" className="border-t border-[var(--line)] py-16">
        <Reveal>
        <p className="mb-3 font-[family-name:var(--font-mono)] text-xs uppercase tracking-[0.14em] text-[var(--amber)]">
          Live from this instance
        </p>
        <h2 className="mb-8 text-balance font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight md:text-3xl">
          The 2026–27 market, measured — not guessed at.
        </h2>

        {summary === null ? (
          <p className="rounded-md border border-[var(--line)] bg-[var(--panel)] px-4 py-3 font-[family-name:var(--font-mono)] text-sm text-[var(--muted)]">
            API unreachable — run <code className="text-[var(--amber)]">jobengine serve</code> to
            see live numbers here.
          </p>
        ) : (
          <div className="flex flex-col gap-6">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatTile value={ranked?.toLocaleString() ?? "—"} label="active SWE / AI-ML roles" animate />
              <StatTile
                value={knownSponsors?.toLocaleString() ?? "—"}
                label="roles with sponsorship signals"
                accent
                animate
              />
              <StatTile
                value={`${(((knownSponsors ?? 0) / (ranked || 1)) * 100).toFixed(1)}%`}
                label="of roles with positive sponsor signals"
                animate
              />
              <StatTile
                value={(summary.unknown ?? 0).toLocaleString()}
                label='marked "unknown" — not "no"'
                animate
              />
            </div>
            <TierChart summary={summary} />
          </div>
        )}
        <p className="mt-4 max-w-[68ch] text-sm text-[var(--muted)]">
          Simplify&apos;s own sponsorship field reads &quot;Other&quot; on the vast majority of
          postings. JobEngine doesn&apos;t guess at that gap — it joins each listing against real
          DOL LCA filing history, and a company absent from that history stays{" "}
          <span className="text-[var(--text)]">unknown</span>, never{" "}
          <span className="text-[var(--text)]">does not sponsor</span>.
        </p>
        </Reveal>
      </section>

      {/* ---------- features ---------- */}
      <section className="border-t border-[var(--line)] py-16">
        <Reveal>
        <p className="mb-3 font-[family-name:var(--font-mono)] text-xs uppercase tracking-[0.14em] text-[var(--amber)]">
          What it does
        </p>
        <h2 className="mb-8 font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight md:text-3xl">
          One pipeline, fetch to offer.
        </h2>
        <div className="overflow-hidden rounded-lg border border-[var(--line)]">
          {[
            {
              cmd: "jobengine fetch && build",
              body: "Live listings, deduplicated. Pulls both SimplifyJobs feeds and collapses reposts into one canonical row per real posting.",
            },
            {
              cmd: "roleradar decide",
              body: "Resume evidence plus job requirements: eligibility gates, cited skill coverage, bounded semantic ranking, and optional AI explanation.",
            },
            {
              cmd: "roleradar evaluate",
              body: "Original predictions stay linked to application outcomes. Pending applications are excluded from failure labels, and small samples withhold ranking metrics.",
            },
            {
              cmd: "sponsor_index.py",
              body: "H-1B LCA cross-referencing against real DOL filing history — a seed index offline, real filing counts once you load a DOL CSV.",
            },
            {
              cmd: "jobengine tailor --semantic",
              body: "Honest resume tailoring: selection and reordering only, gated by a metric audit that blocks unverifiable claims. --semantic adds an opt-in TF-IDF cosine ranking shown alongside, not instead of, the keyword score.",
            },
            {
              cmd: "jobengine track",
              body: "Applications, stages, and follow-ups in one store, with a full status-change timeline — not a spreadsheet that drifts.",
            },
            {
              cmd: "jobengine serve",
              body: "A typed FastAPI backend (Postgres or SQLite) with auto-generated OpenAPI docs — the same data this site is reading right now.",
            },
          ].map((f, i) => (
            <div
              key={f.cmd}
              className={`group grid grid-cols-1 gap-3 px-6 py-5 transition-colors duration-150 md:grid-cols-[240px_1fr] ${
                i % 2 ? "bg-[var(--panel-2)]" : "bg-[var(--panel)]"
              } ${i > 0 ? "border-t border-[var(--line)]" : ""} hover:bg-[#232d38]`}
            >
              <span className="font-[family-name:var(--font-mono)] text-sm text-[var(--amber)] transition-transform duration-150 group-hover:translate-x-0.5">
                {f.cmd}
              </span>
              <p className="text-sm text-[var(--muted)]">{f.body}</p>
            </div>
          ))}
        </div>
        </Reveal>
      </section>

      {/* ---------- principles ---------- */}
      <section className="border-t border-[var(--line)] py-16">
        <Reveal>
        <p className="mb-3 font-[family-name:var(--font-mono)] text-xs uppercase tracking-[0.14em] text-[var(--amber)]">
          Principles
        </p>
        <h2 className="mb-8 font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight md:text-3xl">
          Built like it&apos;s going to be audited.
        </h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {[
            {
              h: "No fabricated metrics",
              p: "The tailoring engine can't invent claims — an audit gate rejects any bullet with an unverifiable number.",
            },
            {
              h: "Unknown is not “no”",
              p: "A company absent from the sponsor index stays unknown. Absence of evidence isn't evidence of absence, and a test enforces exactly that.",
            },
            {
              h: "Portable by design",
              p: "One DATABASE_URL switch moves the whole pipeline between local SQLite and production Postgres — verified against both, not assumed.",
            },
            {
              h: "Explicit saving",
              p: "Try the sample without an account. Sign in and choose to save a decision to preserve its cited evidence and record outcomes. AI explanations are optional.",
            },
          ].map((x, i) => (
            <Reveal key={x.h} delayMs={i * 60}>
              <div className="border-l-2 border-[var(--amber-dim)] py-1 pl-5 transition-[border-color,transform] duration-200 hover:translate-x-1 hover:border-[var(--amber)]">
                <h3 className="mb-1.5 text-[15px] font-semibold">{x.h}</h3>
                <p className="text-sm text-[var(--muted)]">{x.p}</p>
              </div>
            </Reveal>
          ))}
        </div>
        </Reveal>
      </section>

      {/* ---------- CTA ---------- */}
      <section className="border-t border-[var(--line)] py-16 text-center">
        <Reveal className="flex flex-col items-center">
        <h2 className="mb-3 font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight md:text-3xl">
          Stop applying into dead ends.
        </h2>
        <p className="mx-auto mb-7 max-w-[52ch] text-[var(--muted)]">
          Browse the ranked shortlist right now, or track the applications you&apos;ve already
          sent.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Link
            href="/radar"
            className="rounded-lg bg-[var(--amber)] px-6 py-3 font-[family-name:var(--font-mono)] text-sm font-semibold text-[#161006] transition-transform duration-150 hover:scale-[1.03] hover:bg-[#ffc270] active:scale-[0.98]"
          >
            Should I apply? →
          </Link>
          <Link
            href="/tracker"
            className="rounded-lg border border-[var(--line)] px-6 py-3 font-[family-name:var(--font-mono)] text-sm text-[var(--text)] transition-transform duration-150 hover:scale-[1.03] hover:border-[var(--amber)] active:scale-[0.98]"
          >
            Open the tracker
          </Link>
        </div>
        <p className="mt-9 font-[family-name:var(--font-mono)] text-xs text-[var(--faint)]">
          built by Salman Aziz Khan · MIT license
        </p>
        </Reveal>
      </section>
    </div>
  );
}

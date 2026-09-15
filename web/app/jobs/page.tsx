"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Job, JobsSummary, SemanticMatch, parseJson } from "@/lib/api";

const TIER_COLOR: Record<string, string> = {
  very_high: "var(--tier-very-high)",
  high: "var(--tier-high)",
  offers: "var(--tier-offers)",
  medium: "var(--tier-medium)",
  low: "var(--tier-low)",
  unknown: "var(--tier-unknown)",
};

const TIER_ORDER = ["very_high", "high", "offers", "medium", "low", "unknown"];

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [summary, setSummary] = useState<JobsSummary>({});
  const [grad, setGrad] = useState<"intern" | "newgrad" | "">("");
  const [tier, setTier] = useState<string>("very_high,high,offers");
  const [filterDraft, setFilterDraft] = useState({ location: "", company: "", skill: "" });
  const [filters, setFilters] = useState(filterDraft);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [j, s] = await Promise.all([
          api.getJobs({
            grad: grad || undefined, tier: tier || undefined, max: 100,
            location: filters.location || undefined,
            company: filters.company || undefined,
            skill: filters.skill || undefined,
          }),
          api.getJobsSummary(),
        ]);
        if (cancelled) return;
        setJobs(j);
        setSummary(s);
      } catch (e) {
        if (!cancelled) setError(String((e as Error).message ?? e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [grad, tier, filters]);

  const total = useMemo(() => Object.values(summary).reduce((a, b) => a + b, 0), [summary]);

  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticResults, setSemanticResults] = useState<SemanticMatch[] | null>(null);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [semanticError, setSemanticError] = useState<string | null>(null);

  async function handleSemanticSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!semanticQuery.trim()) return;
    setSemanticLoading(true);
    setSemanticError(null);
    try {
      setSemanticResults(await api.semanticSearchJobs(semanticQuery, 8));
    } catch (err) {
      setSemanticError(String((err as Error).message ?? err));
      setSemanticResults(null);
    } finally {
      setSemanticLoading(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
          Sponsor-ranked roles
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Cross-referenced against DOL H-1B LCA filing history — {total.toLocaleString()} active
          SWE / AI-ML roles indexed.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {TIER_ORDER.filter((t) => summary[t] !== undefined).map((t) => (
          <span
            key={t}
            className="rounded-full border border-[var(--line)] px-3 py-1 font-[family-name:var(--font-mono)] text-xs"
            style={{ color: TIER_COLOR[t] }}
          >
            {t.replace("_", " ")} · {summary[t]}
          </span>
        ))}
      </div>

      <div className="flex flex-wrap gap-3">
        <select
          value={grad}
          onChange={(e) => setGrad(e.target.value as "intern" | "newgrad" | "")}
          className="rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-1.5 font-[family-name:var(--font-mono)] text-sm"
        >
          <option value="">All (intern + new grad)</option>
          <option value="intern">Internships</option>
          <option value="newgrad">New grad</option>
        </select>
        <select
          value={tier}
          onChange={(e) => setTier(e.target.value)}
          className="rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-1.5 font-[family-name:var(--font-mono)] text-sm"
        >
          <option value="very_high,high,offers">Sponsor tiers: very high / high / offers</option>
          <option value="very_high,high,offers,medium,low,unknown">All non-excluded tiers</option>
          <option value="very_high">Very high only</option>
        </select>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFilters({
            location: filterDraft.location.trim(),
            company: filterDraft.company.trim(),
            skill: filterDraft.skill.trim(),
          });
        }}
        className="grid gap-3 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4 sm:grid-cols-3"
      >
        {(["location", "company", "skill"] as const).map((field) => (
          <label key={field} className="flex flex-col gap-1 text-xs text-[var(--muted)]">
            <span className="font-[family-name:var(--font-mono)] capitalize">{field}</span>
            <input
              value={filterDraft[field]}
              onChange={(event) => setFilterDraft((current) => ({
                ...current, [field]: event.target.value,
              }))}
              placeholder={field === "location" ? "Remote, Chicago" : field === "company" ? "Microsoft" : "Java"}
              className="rounded-md border border-[var(--line)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]"
            />
          </label>
        ))}
        <div className="flex gap-2 sm:col-span-3">
          <button type="submit" className="rounded-md bg-[var(--amber)] px-4 py-2 text-sm font-semibold text-[#161006]">
            Apply filters
          </button>
          <button
            type="button"
            onClick={() => {
              const empty = { location: "", company: "", skill: "" };
              setFilterDraft(empty);
              setFilters(empty);
            }}
            className="rounded-md border border-[var(--line)] px-4 py-2 text-sm text-[var(--muted)]"
          >
            Clear
          </button>
        </div>
      </form>

      <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-5">
        <h3 className="mb-1 font-[family-name:var(--font-mono)] text-xs uppercase tracking-[0.14em] text-[var(--amber)]">
          Vector search
        </h3>
        <p className="mb-3 text-xs text-[var(--muted)]">
          Paste a job description or describe the role — matched by cosine similarity over
          pgvector, not keyword overlap. Needs a Postgres backend with{" "}
          <code className="text-[var(--text)]">jobengine build --embed</code> run.
        </p>
        <form onSubmit={handleSemanticSearch} className="flex flex-wrap gap-2">
          <input
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            placeholder="e.g. backend engineer building APIs with Python and Postgres"
            className="min-w-[280px] flex-1 rounded-md border border-[var(--line)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)]"
          />
          <button
            type="submit"
            disabled={semanticLoading}
            className="rounded-md bg-[var(--amber)] px-4 py-1.5 font-[family-name:var(--font-mono)] text-sm font-semibold text-[#161006] disabled:opacity-50"
          >
            {semanticLoading ? "Searching…" : "Search"}
          </button>
          {semanticResults && (
            <button
              type="button"
              onClick={() => {
                setSemanticResults(null);
                setSemanticQuery("");
              }}
              className="rounded-md border border-[var(--line)] px-4 py-1.5 text-sm text-[var(--muted)]"
            >
              Clear
            </button>
          )}
        </form>
        {semanticError && (
          <p className="mt-3 text-sm text-[var(--status-warn)]">{semanticError}</p>
        )}
        {semanticResults && (
          <ul className="mt-4 flex flex-col divide-y divide-[var(--line)] border-t border-[var(--line)]">
            {semanticResults.map((r) => {
              const locations = parseJson<string[]>(r.locations, []);
              return (
                <li key={r.dedup_key} className="flex flex-col gap-1 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-variant-tabular font-[family-name:var(--font-mono)] text-xs text-[var(--amber)]">
                      {(1 - r.distance).toFixed(3)} match
                    </span>
                    <span className="font-medium">{r.company}</span>
                    <span className="text-[var(--faint)]">·</span>
                    <span>{r.title}</span>
                  </div>
                  <div className="text-sm text-[var(--muted)]">
                    {locations.slice(0, 3).join(", ") || "Location n/a"}
                    {r.url && (
                      <>
                        {" · "}
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[var(--amber)] underline underline-offset-2"
                        >
                          Apply
                        </a>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
            {semanticResults.length === 0 && (
              <p className="py-3 text-sm text-[var(--muted)]">No matches.</p>
            )}
          </ul>
        )}
      </div>

      {error && (
        <p className="rounded-md border border-[var(--status-warn)] bg-[var(--panel)] px-3 py-2 text-sm text-[var(--status-warn)]">
          Could not reach the API: {error}. Is `jobengine serve` running?
        </p>
      )}
      {loading && <p className="text-sm text-[var(--muted)]">Loading…</p>}

      <ul className="flex flex-col divide-y divide-[var(--line)] rounded-lg border border-[var(--line)] bg-[var(--panel)]">
        {jobs.map((job) => {
          const locations = parseJson<string[]>(job.locations, []);
          return (
            <li key={job.dedup_key} className="flex flex-col gap-1 px-5 py-4">
              <div className="flex items-center gap-2">
                <span
                  className="rounded-full border border-[var(--line)] px-2 py-0.5 font-[family-name:var(--font-mono)] text-xs"
                  style={{ color: TIER_COLOR[job.sponsor_tier] ?? "var(--status-excluded)" }}
                >
                  {job.sponsor_tier.replace("_", " ")}
                </span>
                <span className="font-medium">{job.company}</span>
                <span className="text-[var(--faint)]">·</span>
                <span>{job.title}</span>
              </div>
              <div className="text-sm text-[var(--muted)]">
                {locations.slice(0, 3).join(", ") || "Location n/a"}
                {job.url && (
                  <>
                    {" · "}
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--amber)] underline underline-offset-2"
                    >
                      Apply
                    </a>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {!loading && !error && jobs.length === 0 && (
        <p className="text-sm text-[var(--muted)]">No roles match these filters.</p>
      )}
    </div>
  );
}

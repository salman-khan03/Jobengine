"use client";

import { useEffect, useState } from "react";
import { api, Decision, RankingReport, SavedDecision } from "@/lib/api";

const STAGES = ["applied", "oa", "phone_screen", "interview", "onsite", "offer", "rejected", "ghosted", "withdrawn"];
const label = (stage: string) => stage === "oa" ? "Online assessment" : stage.replaceAll("_", " ");

export default function DecisionJournal({ token, onInspect }: { token: string; onInspect: (decision: Decision) => void }) {
  const [rows, setRows] = useState<SavedDecision[]>([]);
  const [report, setReport] = useState<RankingReport | null>(null);
  const [funnel, setFunnel] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [active, setActive] = useState<number | null>(null);
  const [stage, setStage] = useState("applied");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [history, evaluation, counts] = await Promise.all([api.getDecisions(token), api.getEvaluation(token), api.getFunnel(token)]);
        if (cancelled) return;
        setRows(history.decisions);
        setReport(evaluation);
        setFunnel(counts.funnel);
        setError("");
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load your journal.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [token, revision]);

  async function record(e: React.FormEvent, row: SavedDecision) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api.recordOutcome(token, row.job_key, stage, note);
      setNotice(`${label(stage)} recorded for ${row.company}. Your original prediction is preserved.`);
      setActive(null);
      setNote("");
      setRevision((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record this outcome. Please retry.");
    } finally {
      setSaving(false);
    }
  }

  return <section className="mt-14 border-t border-[var(--line)] pt-8" aria-labelledby="journal-heading">
    <div className="flex flex-wrap items-baseline justify-between gap-3">
      <h2 id="journal-heading" className="font-[family-name:var(--font-display)] text-2xl">Your decision journal</h2>
      <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">PREDICT → APPLY → LEARN</span>
    </div>
    <p className="mt-2 max-w-2xl text-sm text-[var(--muted)]">Keep the evidence behind each decision, then record what happened. Outcomes stay linked to the original prediction so later re-scoring cannot rewrite history.</p>
    {notice && <p role="status" className="mt-4 text-sm text-[var(--tier-very-high)]">{notice}</p>}
    {error && <div role="alert" className="mt-4 text-sm text-[var(--status-warn)]">{error} <button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Retry loading</button></div>}
    {loading ? <p role="status" className="mt-6 text-sm text-[var(--muted)]">Loading your decisions…</p> : <>
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {["applied", "oa", "interview", "offer", "rejected", "ghosted", "withdrawn"].map((item) => <div key={item} className="rounded-lg border border-[var(--line)] p-4">
          <p className="text-xs capitalize text-[var(--muted)]">{label(item)}</p>
          <p className="mt-1 font-[family-name:var(--font-mono)] text-2xl">{funnel[item] ?? 0}</p>
        </div>)}
      </div>
      <p className="mt-2 text-xs text-[var(--muted)]">Current recorded stage for each distinct role. Terminal outcomes stay visible; ranking evaluation uses the furthest stage reached.</p>
      <div className="my-6 rounded-lg border border-[var(--line)] p-4">
        <h3 className="text-sm font-medium">Is the ranking working?</h3>
        {report && <>
          <p className="mt-1 text-sm text-[var(--muted)]">{report.note || "Compare original match rankings with the furthest recorded application stage."}</p>
          <p className="mt-2 text-xs text-[var(--muted)]">{report.n} labeled roles · {report.positives} progressed to an assessment or beyond</p>
          {!report.underpowered && <dl className="mt-4 flex flex-wrap gap-8 text-sm">
            <div><dt className="text-[var(--muted)]">Ranking quality · NDCG@5</dt><dd className="font-[family-name:var(--font-mono)]">{report.ndcg_at_5.toFixed(3)}</dd></div>
            <div><dt className="text-[var(--muted)]">Top 5 progression rate</dt><dd className="font-[family-name:var(--font-mono)]">{Math.round(report.precision_at_5 * 100)}%</dd></div>
            <div><dt className="text-[var(--muted)]">Top 5 lift</dt><dd className="font-[family-name:var(--font-mono)]">{report.lift_at_5.toFixed(2)}×</dd></div>
          </dl>}
          <p className="mt-3 text-xs text-[var(--muted)]">Observational feedback from the roles you chose to pursue. Pending outcomes, selection bias, and small samples limit conclusions; this does not establish hiring probability.</p>
        </>}
      </div>
      {rows.length === 0 && !error && <div className="rounded-lg border border-dashed border-[var(--line)] p-8 text-center"><p>No saved decisions yet.</p><p className="mt-2 text-sm text-[var(--muted)]">Select “Save this decision to my journal” above, then score a role to begin.</p></div>}
      <ul className="space-y-3">
        {rows.map((row) => <li key={row.decision_id} className="rounded-lg border border-[var(--line)] p-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div><h3 className="font-medium">{row.title}</h3><p className="text-sm text-[var(--muted)]">{row.company} · {new Date(row.created_at).toLocaleDateString()}</p><p className="mt-2 font-[family-name:var(--font-mono)] text-xs">{row.verdict.toUpperCase()} · {Math.round(row.score * 100)}/100 evidence match</p></div>
            <div className="flex gap-3 text-xs">
              <button type="button" className="rounded border border-[var(--line)] px-3 py-2" onClick={() => { onInspect({ ...row.payload, decision_id: row.decision_id }); document.getElementById("decision-result")?.scrollIntoView({ behavior: "smooth" }); }}>Review evidence</button>
              <button type="button" disabled={saving} aria-expanded={active === row.decision_id} className="rounded bg-[var(--amber)] px-3 py-2 text-[var(--ink)] disabled:opacity-50" onClick={() => { setActive(active === row.decision_id ? null : row.decision_id); setStage("applied"); setNote(""); }}>Record outcome</button>
            </div>
          </div>
          {active === row.decision_id && <form onSubmit={(e) => record(e, row)} className="mt-4 grid gap-3 border-t border-[var(--line)] pt-4 sm:grid-cols-2">
            <label className="text-xs">Stage<select value={stage} onChange={(e) => setStage(e.target.value)} className="mt-1 w-full rounded border border-[var(--line)] bg-[var(--panel)] px-3 py-2 capitalize">{STAGES.map((item) => <option key={item} value={item}>{label(item)}</option>)}</select></label>
            <label className="text-xs">Note (optional)<input maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 w-full rounded border border-[var(--line)] bg-transparent px-3 py-2" placeholder="e.g. Assessment invitation received" /></label>
            <button type="submit" disabled={saving} className="justify-self-start rounded bg-[var(--amber)] px-4 py-2 text-xs text-[var(--ink)] disabled:opacity-50">{saving ? "Saving…" : "Save outcome"}</button>
          </form>}
        </li>)}
      </ul>
    </>}
  </section>;
}

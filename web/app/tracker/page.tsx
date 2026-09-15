"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api, Application, ApplicationStatus } from "@/lib/api";

const STATUSES: ApplicationStatus[] = [
  "saved",
  "applied",
  "heard_back",
  "oa",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
];

const SOURCES = ["linkedin", "company_site", "simplify", "referral", "email", "other"];

export default function TrackerPage() {
  const { data: session } = useSession();
  const token = session?.backendToken;

  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ company: "", title: "", source: "other" });
  const [submitting, setSubmitting] = useState(false);

  async function load(tok: string) {
    setLoading(true);
    try {
      setApps(await api.getApplications(tok));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    async function initialLoad(tok: string) {
      setLoading(true);
      try {
        const rows = await api.getApplications(tok);
        if (!cancelled) setApps(rows);
      } catch (e) {
        if (!cancelled) setError(String((e as Error).message ?? e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    initialLoad(token);
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!form.company || !form.title || !token) return;
    setSubmitting(true);
    try {
      await api.createApplication(token, form);
      setForm({ company: "", title: "", source: "other" });
      load(token);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStatusChange(appId: number, status: string) {
    if (!token) return;
    await api.updateStatus(token, appId, status);
    load(token);
  }

  async function handleDelete(appId: number) {
    if (!token) return;
    await api.deleteApplication(token, appId);
    load(token);
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
          Application tracker
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          What you applied to, where from, and what happened since — visible only to you.
        </p>
      </div>

      <form
        onSubmit={handleAdd}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4"
      >
        <div className="flex flex-col gap-1">
          <label className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            Company
          </label>
          <input
            required
            value={form.company}
            onChange={(e) => setForm({ ...form, company: e.target.value })}
            className="rounded-md border border-[var(--line)] bg-[var(--panel-2)] px-2 py-1.5 text-sm text-[var(--text)]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            Title
          </label>
          <input
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="rounded-md border border-[var(--line)] bg-[var(--panel-2)] px-2 py-1.5 text-sm text-[var(--text)]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            Source
          </label>
          <select
            value={form.source}
            onChange={(e) => setForm({ ...form, source: e.target.value })}
            className="rounded-md border border-[var(--line)] bg-[var(--panel-2)] px-2 py-1.5 text-sm text-[var(--text)]"
          >
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-[var(--amber)] px-4 py-1.5 font-[family-name:var(--font-mono)] text-sm font-semibold text-[#161006] disabled:opacity-50"
        >
          Add application
        </button>
      </form>

      {error && (
        <p className="rounded-md border border-[var(--status-warn)] bg-[var(--panel)] px-3 py-2 text-sm text-[var(--status-warn)]">
          {error}
        </p>
      )}
      {loading && <p className="text-sm text-[var(--muted)]">Loading…</p>}

      <ul className="flex flex-col divide-y divide-[var(--line)] rounded-lg border border-[var(--line)] bg-[var(--panel)]">
        {apps.map((a) => (
          <li key={a.app_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {a.company} — {a.title}
              </div>
              <div className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
                #{a.app_id} · {a.source} · updated {a.last_update.slice(0, 10)}
              </div>
            </div>
            <select
              value={a.status}
              onChange={(e) => handleStatusChange(a.app_id, e.target.value)}
              className="rounded-md border border-[var(--line)] bg-[var(--panel-2)] px-2 py-1 text-sm text-[var(--text)]"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <button
              onClick={() => handleDelete(a.app_id)}
              className="text-sm text-[var(--status-warn)] hover:underline"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
      {!loading && !error && apps.length === 0 && (
        <p className="text-sm text-[var(--muted)]">No applications tracked yet.</p>
      )}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api, AnalyticsSummary, Health } from "@/lib/api";
import { StatTile } from "@/components/StatTile";

const WINDOWS = [
  { hours: 1, label: "1h" },
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
];

function pct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

/** Compact number so a 6-digit request count doesn't overflow a tile on mobile. */
function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(0)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function DashboardPage() {
  const { data: session, status: sessionStatus } = useSession();
  const token = session?.backendToken;

  const [hours, setHours] = useState(24);
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (tok: string, windowHours: number) => {
      setLoading(true);
      setError(null);
      try {
        // Health is unauthenticated and must not fail the whole page, so it
        // settles independently of the analytics call.
        const [summary, healthResult] = await Promise.all([
          api.getAnalytics(tok, windowHours),
          api.getHealth().catch(() => null),
        ]);
        setData(summary);
        setHealth(healthResult);
      } catch (e) {
        setError(String((e as Error).message ?? e));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!token) return;
    // Schedule the request after the effect; signed-out UI derives from session status.
    let cancelled = false;
    Promise.resolve().then(() => { if (!cancelled) void load(token, hours); });
    return () => { cancelled = true; };
  }, [token, hours, load]);

  if (sessionStatus !== "loading" && !token) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
          Dashboard
        </h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Traffic and latency data isn&apos;t public.{" "}
          <a href="/login" className="text-[var(--amber)] hover:underline">
            Sign in
          </a>{" "}
          to view it.
        </p>
      </div>
    );
  }

  const worstRoute =
    data && data.by_route.length > 0
      ? [...data.by_route].sort((a, b) => b.p95_ms - a.p95_ms)[0]
      : null;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
            Service dashboard
          </h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Measured from real traffic recorded by the API middleware — not estimates.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {health && (
            <span
              className="rounded-md border border-[var(--line)] bg-[var(--panel)] px-2 py-1 font-[family-name:var(--font-mono)] text-xs"
              title={`backend: ${health.backend}`}
            >
              <span
                className={
                  health.status === "ok"
                    ? "text-[var(--status-ok,#4ade80)]"
                    : "text-[var(--status-warn)]"
                }
              >
                ●
              </span>{" "}
              {health.status} · v{health.version}
            </span>
          )}
          <div
            className="flex rounded-md border border-[var(--line)] bg-[var(--panel)]"
            role="group"
            aria-label="Time window"
          >
            {WINDOWS.map((w) => (
              <button
                key={w.hours}
                onClick={() => setHours(w.hours)}
                aria-pressed={hours === w.hours}
                className={`px-3 py-1 font-[family-name:var(--font-mono)] text-xs ${
                  hours === w.hours
                    ? "text-[var(--amber)]"
                    : "text-[var(--muted)] hover:text-[var(--text)]"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <p className="rounded-md border border-[var(--status-warn)] bg-[var(--panel)] px-3 py-2 text-sm text-[var(--status-warn)]">
          Couldn&apos;t load analytics: {error}
        </p>
      )}

      {loading && <p className="text-sm text-[var(--muted)]">Loading…</p>}

      {!loading && !error && data && data.requests === 0 && (
        <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-5 py-6">
          <p className="text-sm text-[var(--muted)]">
            No requests recorded in the last {data.window_hours}h. Numbers appear here once
            the API serves traffic — nothing on this page is seeded or simulated.
          </p>
        </div>
      )}

      {!loading && !error && data && data.requests > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <StatTile value={compact(data.requests)} label={`requests / ${data.window_hours}h`} />
            <StatTile value={`${data.latency_ms.p95}ms`} label="p95 latency" accent />
            <StatTile value={pct(data.error_rate)} label="error rate (5xx)" />
            <StatTile value={String(data.active_users)} label="active users" />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <StatTile value={`${data.latency_ms.p50}ms`} label="p50 latency" />
            <StatTile value={`${data.latency_ms.p99}ms`} label="p99 latency" />
            <StatTile value={`${data.throughput_rps}`} label="throughput (req/s avg)" />
            <StatTile value={String(data.registered_users)} label="registered users" />
          </div>

          {worstRoute && (
            <p className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
              slowest endpoint: {worstRoute.route} @ p95 {worstRoute.p95_ms}ms
            </p>
          )}

          <section className="rounded-lg border border-[var(--line)] bg-[var(--panel)]">
            <h2 className="border-b border-[var(--line)] px-4 py-3 font-[family-name:var(--font-mono)] text-sm sm:px-5">
              By endpoint
            </h2>
            {/* Tables don't shrink gracefully; scroll it horizontally on
                narrow screens rather than letting the page itself scroll. */}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[34rem] text-sm">
                <thead>
                  <tr className="text-left font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
                    <th className="px-4 py-2 font-normal sm:px-5">route</th>
                    <th className="px-3 py-2 text-right font-normal">reqs</th>
                    <th className="px-3 py-2 text-right font-normal">p50</th>
                    <th className="px-3 py-2 text-right font-normal">p95</th>
                    <th className="px-4 py-2 text-right font-normal sm:px-5">5xx</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--line)]">
                  {data.by_route.map((r) => (
                    <tr key={r.route}>
                      <td className="px-4 py-2 font-[family-name:var(--font-mono)] text-xs sm:px-5">
                        {r.route}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{compact(r.requests)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.p50_ms}ms</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.p95_ms}ms</td>
                      <td
                        className={`px-4 py-2 text-right tabular-nums sm:px-5 ${
                          r.errors > 0 ? "text-[var(--status-warn)]" : "text-[var(--muted)]"
                        }`}
                      >
                        {r.errors}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <p className="text-xs text-[var(--muted)]">
            Percentiles are nearest-rank over every request in the window. Client errors
            (4xx) are tracked separately at {pct(data.client_error_rate)} and excluded from
            the error rate above — a 401 on an expired token is the API behaving correctly.
          </p>
        </>
      )}
    </div>
  );
}

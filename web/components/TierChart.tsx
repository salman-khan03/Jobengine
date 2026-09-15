"use client";

import { useState } from "react";
import type { JobsSummary } from "@/lib/api";

// Ordinal amber ramp, best sponsor signal -> worst, validated with
// scripts/validate_palette.js --ordinal --mode dark --surface #161c23
// (see globals.css for the check notes). Order here IS the chart's
// sort order — it doubles as the ranking query.py itself uses.
const TIERS: { key: string; label: string; color: string }[] = [
  { key: "very_high", label: "very high", color: "var(--tier-very-high)" },
  { key: "high", label: "high", color: "var(--tier-high)" },
  { key: "offers", label: "offers", color: "var(--tier-offers)" },
  { key: "medium", label: "medium", color: "var(--tier-medium)" },
  { key: "low", label: "low", color: "var(--tier-low)" },
  { key: "unknown", label: "unknown", color: "var(--tier-unknown)" },
];

const EXCLUDED: { key: string; label: string }[] = [
  { key: "does_not_sponsor", label: "does not sponsor" },
  { key: "citizen_only", label: "citizens only" },
];

export function TierChart({ summary }: { summary: JobsSummary }) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = TIERS.map((t) => ({ ...t, count: summary[t.key] ?? 0 }));
  const rankedTotal = rows.reduce((a, r) => a + r.count, 0);
  const max = Math.max(...rows.map((r) => r.count), 1);
  const excludedTotal = EXCLUDED.reduce((a, e) => a + (summary[e.key] ?? 0), 0);

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-6">
      <div className="mb-5 flex items-baseline justify-between gap-4">
        <h3 className="font-[family-name:var(--font-mono)] text-xs uppercase tracking-[0.14em] text-[var(--amber)]">
          Sponsorship tier — active SWE / AI-ML roles
        </h3>
        <span className="font-variant-tabular font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
          {rankedTotal.toLocaleString()} ranked
        </span>
      </div>

      <div className="flex flex-col gap-[2px]">
        {rows.map((r) => {
          const pct = rankedTotal ? (r.count / rankedTotal) * 100 : 0;
          const widthPct = (r.count / max) * 100;
          const isHover = hover === r.key;
          return (
            <div
              key={r.key}
              className="group grid grid-cols-[88px_1fr_64px] items-center gap-3 rounded-sm py-1.5"
              onMouseEnter={() => setHover(r.key)}
              onMouseLeave={() => setHover(null)}
            >
              <span className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
                {r.label}
              </span>
              <div className="relative h-5 rounded bg-[var(--panel-2)]">
                {r.count > 0 && (
                  <div
                    className="h-full rounded transition-[width] duration-300"
                    style={{ width: `${Math.max(widthPct, 1.5)}%`, background: r.color }}
                  />
                )}
                {isHover && (
                  <div className="absolute -top-8 left-0 z-10 whitespace-nowrap rounded border border-[var(--line)] bg-[var(--ink)] px-2 py-1 font-[family-name:var(--font-mono)] text-[11px] text-[var(--text)] shadow-lg">
                    {r.count.toLocaleString()} roles · {pct.toFixed(1)}% of ranked
                  </div>
                )}
              </div>
              <span className="text-right font-variant-tabular font-[family-name:var(--font-mono)] text-xs text-[var(--text)]">
                {r.count.toLocaleString()}
              </span>
            </div>
          );
        })}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-[var(--line)] pt-4">
        <span className="font-[family-name:var(--font-mono)] text-[11px] uppercase tracking-[0.1em] text-[var(--faint)]">
          Excluded from ranking, not &ldquo;no data&rdquo;:
        </span>
        {EXCLUDED.map((e) => (
          <span
            key={e.key}
            className="rounded-full border border-[var(--line)] px-2 py-0.5 font-[family-name:var(--font-mono)] text-[11px] text-[var(--status-excluded)]"
          >
            {e.label} · {(summary[e.key] ?? 0).toLocaleString()}
          </span>
        ))}
        <span className="ml-auto font-[family-name:var(--font-mono)] text-[11px] text-[var(--faint)]">
          {excludedTotal.toLocaleString()} explicitly ruled out
        </span>
      </div>
    </div>
  );
}

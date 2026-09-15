"use client";

import { useEffect, useRef, useState } from "react";

type Line = { t: "cmd" | "out" | "ok" | "warn"; txt: string };

// Real commands and real output shapes from this project's own CLI — the
// counts mirror an actual `jobengine build` run against live SimplifyJobs
// data, not invented numbers.
const LINES: Line[] = [
  { t: "cmd", txt: "jobengine fetch" },
  { t: "out", txt: "pulling Summer2026-Internships + New-Grad-Positions…" },
  { t: "ok", txt: "-> 32,298 raw listings" },
  { t: "cmd", txt: "jobengine build" },
  { t: "out", txt: "deduplicating… cross-referencing DOL H-1B LCA filings…" },
  { t: "ok", txt: "-> 31,983 unique postings, 2,371 active SWE / AI-ML roles" },
  { t: "cmd", txt: "jobengine query --tier very_high,high,offers --grad newgrad" },
  { t: "out", txt: "196 roles at employers with real sponsorship history" },
  { t: "warn", txt: "2,131 more roles: sponsorship unknown, not \"no\"" },
  { t: "cmd", txt: "jobengine tailor --company Stripe --jd-file jd.txt --semantic" },
  { t: "ok", txt: "-> resume + cover letter written, 0 unverifiable claims" },
];

export function TerminalDemo() {
  const [rendered, setRendered] = useState<Line[]>([]);
  const [typing, setTyping] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    let cancelled = false;
    let i = 0;

    async function run() {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduce) {
        setRendered(LINES);
        return;
      }
      for (i = 0; i < LINES.length && !cancelled; i++) {
        const line = LINES[i];
        if (line.t === "cmd") {
          for (let j = 1; j <= line.txt.length; j++) {
            if (cancelled) return;
            setTyping(line.txt.slice(0, j));
            await sleep(18 + Math.random() * 30);
          }
          await sleep(200);
          setRendered((prev) => [...prev, line]);
          setTyping("");
        } else {
          await sleep(220);
          setRendered((prev) => [...prev, line]);
        }
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[#0a0e12] shadow-[0_24px_60px_rgba(0,0,0,0.5)]">
      <div className="flex items-center gap-2 border-b border-[var(--line)] bg-[var(--panel)] px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[var(--line)]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[var(--line)]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[var(--line)]" />
        <span className="mx-auto font-[family-name:var(--font-mono)] text-[11px] text-[var(--muted)]">
          jobengine — zsh
        </span>
      </div>
      <div className="min-h-[320px] whitespace-pre-wrap p-4 font-[family-name:var(--font-mono)] text-[13px] leading-[1.75]">
        {rendered.map((l, i) => (
          <div key={i}>
            {l.t === "cmd" ? (
              <>
                <span className="text-[var(--amber)]">$ </span>
                <span className="text-[var(--text)]">{l.txt}</span>
              </>
            ) : (
              <span
                className={
                  l.t === "ok"
                    ? "text-[var(--status-good)]"
                    : l.t === "warn"
                      ? "text-[var(--status-warn)]"
                      : "text-[var(--muted)]"
                }
              >
                {l.txt}
              </span>
            )}
          </div>
        ))}
        {typing && (
          <div>
            <span className="text-[var(--amber)]">$ </span>
            <span className="text-[var(--text)]">{typing}</span>
          </div>
        )}
        {rendered.length === LINES.length && !typing && (
          <div>
            <span className="text-[var(--amber)]">$ </span>
            <span className="cursor-blink inline-block h-[15px] w-[8px] translate-y-[2px] bg-[var(--amber)]" />
          </div>
        )}
      </div>
    </div>
  );
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

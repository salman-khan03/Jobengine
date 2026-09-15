"use client";

import { useEffect, useRef, useState } from "react";

/** Splits "3,387" / "14.46ms" / "99.9%" / "—" into a numeric core plus the
 * prefix/suffix text around it, so only the number counts up and units,
 * separators, and non-numeric values (like an em dash placeholder) render
 * exactly as passed in. */
function parseNumeric(value: string): { prefix: string; number: number; decimals: number; suffix: string } | null {
  const match = value.match(/^([^\d-]*)(-?[\d,]*\.?\d+)([^\d]*)$/);
  if (!match) return null;
  const [, prefix, numStr, suffix] = match;
  const clean = numStr.replace(/,/g, "");
  const number = Number(clean);
  if (Number.isNaN(number)) return null;
  const decimals = clean.includes(".") ? clean.split(".")[1].length : 0;
  return { prefix, number, decimals, suffix };
}

function formatLike(original: string, n: number, decimals: number): string {
  const hasCommas = /\d,\d/.test(original);
  return hasCommas
    ? n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : n.toFixed(decimals);
}

export function StatTile({
  value,
  label,
  accent = false,
  animate = false,
}: {
  value: string;
  label: string;
  accent?: boolean;
  /** Count up from 0 the first time this tile scrolls into view. Opt-in and
   * backward compatible — every existing caller renders identically. */
  animate?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // Holds an in-progress animated frame; null means "no animation running,
  // render `value` directly." Every write to this happens from inside an
  // IntersectionObserver or requestAnimationFrame callback — both fire
  // asynchronously relative to the effect that registers them, so none of
  // this trips the set-state-in-effect rule the way a synchronous setState
  // call in the effect body would. It also means every non-animating case
  // (animate=false, an uncountable value, reduced motion) falls out for
  // free: the effect simply never calls setDisplay, and render below always
  // shows the real, correct `value`.
  const [display, setDisplay] = useState<string | null>(null);

  useEffect(() => {
    if (!animate) return;
    const parsed = parseNumeric(value);
    if (!parsed) return; // not a number we can count ("—", etc.) — `value` renders as-is
    const el = ref.current;
    if (!el) return;

    const { prefix, number, decimals, suffix } = parsed;
    const DURATION = 900;
    let raf = 0;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.unobserve(el);
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          return; // leave display unset -> `value` renders immediately, no count-up
        }
        const start = performance.now();
        const tick = (now: number) => {
          const t = Math.min(1, (now - start) / DURATION);
          // ease-out cubic: fast start, settles into the final digits rather
          // than a linear count that feels mechanical at these magnitudes.
          const eased = 1 - Math.pow(1 - t, 3);
          setDisplay(`${prefix}${formatLike(value, number * eased, decimals)}${suffix}`);
          if (t < 1) raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [animate, value]);

  return (
    <div
      ref={ref}
      className="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-5 py-4 transition-colors duration-300 hover:border-[var(--amber-dim)]"
    >
      <div
        className={`font-variant-tabular font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight tabular-nums ${
          accent ? "text-[var(--amber)]" : "text-[var(--text)]"
        }`}
      >
        {display ?? value}
      </div>
      <div className="mt-1 font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
        {label}
      </div>
    </div>
  );
}

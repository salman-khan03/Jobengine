"use client";

import { useState } from "react";

const STEPS: [string, string, string][] = [
  ["01", "Extract the evidence", "Projects, experience, and skills keep their resume source."],
  ["02", "Check the hard constraints", "Eligibility can veto a role, regardless of skill overlap."],
  ["03", "Explain the match", "See demonstrated skills, missing requirements, and score arithmetic."],
  ["04", "Follow the outcome", "Keep the original prediction through assessment, interview, and offer or rejection."],
];

/**
 * The four-step trail, with a fill rail that tracks whichever step has
 * hover/focus — a small, literal reinforcement of "this is a trail, not a
 * black box": moving through it visibly connects one step to the next
 * instead of four cards sitting inertly next to each other.
 *
 * Keyboard users get the identical highlight via :focus-within on each
 * step's wrapper (each step is a real, tabbable element), not a
 * mouse-only affordance.
 */
export function DecisionTrail() {
  const [active, setActive] = useState<number | null>(null);
  const fillPct = active === null ? 0 : ((active + 1) / STEPS.length) * 100;

  return (
    <ol className="relative mt-6 space-y-5">
      <div
        aria-hidden
        className="absolute left-[7px] top-2 bottom-2 w-px bg-[var(--line)]"
      >
        <div
          className="w-full bg-[var(--amber)] transition-[height] duration-300 ease-out"
          style={{ height: `${fillPct}%` }}
        />
      </div>
      {STEPS.map(([step, heading, detail], i) => (
        <li
          key={step}
          tabIndex={0}
          onMouseEnter={() => setActive(i)}
          onMouseLeave={() => setActive(null)}
          onFocus={() => setActive(i)}
          onBlur={() => setActive(null)}
          className="relative flex cursor-default gap-4 rounded-md pl-0.5 outline-none transition-transform duration-200 ease-out hover:translate-x-1 focus-visible:translate-x-1"
        >
          <span
            className={`relative z-10 font-[family-name:var(--font-mono)] text-sm transition-colors duration-200 ${
              active === i ? "text-[var(--amber)]" : "text-[var(--faint)]"
            }`}
          >
            {step}
          </span>
          <div>
            <h3
              className={`text-sm font-semibold transition-colors duration-200 ${
                active === i ? "text-[var(--amber)]" : "text-[var(--text)]"
              }`}
            >
              {heading}
            </h3>
            <p className="mt-1 text-sm text-[var(--muted)]">{detail}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

"use client";

import { useRef, type ReactNode } from "react";

/**
 * A soft radial highlight that tracks the pointer within its container.
 *
 * Position is written straight to CSS custom properties via a ref on every
 * `pointermove` — not `useState` — because state would re-render this
 * component (and everything under it) on every pixel of mouse movement.
 * Direct style mutation is how you get a cursor-responsive surface without
 * pulling in a motion library for one gradient.
 *
 * Touch devices get no `pointermove` stream worth tracking, and
 * `prefers-reduced-motion` users get the gradient parked at center — both
 * paths render the static fallback gradient already in the CSS, so neither
 * needs a JS branch.
 */
export function CursorSpotlight({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  function handlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (e.pointerType !== "mouse") return; // no hover concept on touch
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--spot-x", `${((e.clientX - rect.left) / rect.width) * 100}%`);
    el.style.setProperty("--spot-y", `${((e.clientY - rect.top) / rect.height) * 100}%`);
  }

  return (
    <div
      ref={ref}
      onPointerMove={handlePointerMove}
      className={`relative ${className}`}
      style={{
        // Fallback center position before the first pointermove (and for
        // touch/reduced-motion, which never fire one).
        ["--spot-x" as string]: "50%",
        ["--spot-y" as string]: "30%",
      }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-70 motion-safe:transition-[background] motion-safe:duration-300"
        style={{
          background:
            "radial-gradient(480px circle at var(--spot-x) var(--spot-y), rgba(255,180,84,0.10), transparent 70%)",
        }}
      />
      {children}
    </div>
  );
}

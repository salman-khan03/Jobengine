"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Fades + lifts children into place the first time they scroll into view.
 *
 * IntersectionObserver rather than a scroll-position library: this page has
 * zero animation dependencies today, and one small hook covers every reveal
 * on the page without adding one. Fires once (`unobserve` after triggering)
 * so re-scrolling past a section doesn't replay it — a page that keeps
 * re-animating on every scroll reads as nervous, not alive.
 *
 * Reduced motion is handled entirely by the `motion-safe:`/`motion-reduce:`
 * classes below, matching the plain-CSS `@media (prefers-reduced-motion)`
 * pattern already used in globals.css — not by reading `matchMedia` in JS.
 * Reading it in a `useState` initializer would run differently during SSR
 * (no `window`) than during client hydration (real `window`), which is a
 * hydration-mismatch risk the moment a user actually has the setting on;
 * CSS media queries carry no such risk since the browser evaluates them at
 * paint time, identically on every render.
 */
export function Reveal({
  children,
  delayMs = 0,
  className = "",
}: {
  children: ReactNode;
  delayMs?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.unobserve(el);
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={`motion-safe:transition-[opacity,transform] motion-safe:duration-700 motion-safe:ease-out motion-reduce:opacity-100 motion-reduce:translate-y-0 ${
        visible ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0"
      } ${className}`}
      style={{ transitionDelay: visible ? `${delayMs}ms` : "0ms" }}
    >
      {children}
    </div>
  );
}

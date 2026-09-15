/**
 * Nav brand mark: the same radar glyph as app/icon.tsx (ring, sweep beam,
 * off-angle blip, center dot), redrawn as real inline SVG rather than
 * reused as an <img src="/icon">. Two reasons: this renders in a normal
 * React/DOM context (not Satori's flexbox-only CSS subset), so real SVG
 * paths are available here and render crisper at nav-bar size; and an
 * inline mark paints with zero extra network request, which matters for
 * something that appears on every page.
 */
export function Logo({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      className="shrink-0"
    >
      <circle cx="12" cy="12" r="9.5" stroke="var(--amber)" strokeWidth="1.6" />
      <circle cx="12" cy="12" r="5.5" stroke="var(--amber)" strokeWidth="1" opacity="0.35" />
      <line
        x1="12"
        y1="12"
        x2="17.2"
        y2="6.8"
        stroke="var(--amber)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="8" cy="16.5" r="1.1" fill="var(--amber)" opacity="0.55" />
      <circle cx="12" cy="12" r="1.3" fill="var(--amber)" />
    </svg>
  );
}

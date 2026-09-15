import { ImageResponse } from "next/og";

/**
 * The single image most people will ever see of this project — whatever
 * renders here is the actual first impression on LinkedIn, Slack, or
 * Twitter, generated once at build time and reused for every share. A
 * link with no image (or a broken one) gets scrolled past; this is the
 * cheapest, highest-leverage thing a project can do for click-through.
 *
 * Deliberately mirrors the site's own terminal aesthetic (globals.css'
 * --ink/--panel/--amber tokens, hardcoded here since this renders outside
 * React/CSS-variable scope via Satori) rather than a generic gradient
 * card — the preview should look like the product, not like a template.
 */
export const alt =
  "RoleRadar — evidence-grounded job intelligence. Every match cited to a resume line.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#0e1216",
          padding: "72px 80px",
          fontFamily: "monospace",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ color: "#ffb454", fontSize: 34 }}>$</span>
          <span style={{ color: "#8494a3", fontSize: 26, letterSpacing: 2 }}>
            ROLERADAR · EVIDENCE-GROUNDED JOB INTELLIGENCE
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              display: "flex",
              color: "#dde5ec",
              fontSize: 66,
              fontWeight: 700,
              lineHeight: 1.08,
              letterSpacing: -1,
            }}
          >
            Your next application.
          </div>
          <div
            style={{
              display: "flex",
              color: "#ffb454",
              fontSize: 66,
              fontWeight: 700,
              lineHeight: 1.08,
              letterSpacing: -1,
            }}
          >
            Backed by evidence.
          </div>
        </div>

        <div style={{ display: "flex", gap: 40 }}>
          {[
            ["36,541", "deduplicated postings"],
            ["100%", "AI claims cite evidence"],
            ["286", "automated tests"],
          ].map(([n, label]) => (
            <div key={label} style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ color: "#ffb454", fontSize: 40, fontWeight: 700 }}>{n}</span>
              <span style={{ color: "#8494a3", fontSize: 20 }}>{label}</span>
            </div>
          ))}
        </div>
      </div>
    ),
    { ...size },
  );
}

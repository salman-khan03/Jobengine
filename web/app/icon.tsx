import { ImageResponse } from "next/og";

/**
 * Browser-tab favicon: a minimal radar glyph — ring, center dot, one sweep
 * beam — rather than generic job-board iconography (briefcase, magnifying
 * glass). It's literal to the product name and its actual metaphor (a
 * scoring sweep over postings), not a category stock icon.
 *
 * Built from plain divs (border-radius for the ring/dot, a rotated
 * gradient div for the beam) rather than an embedded <svg> or path data —
 * Satori (the renderer behind next/og's ImageResponse) supports a flexbox
 * CSS subset, not arbitrary SVG, so shapes here are CSS primitives, not
 * vector paths.
 */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: "50%",
          background: "#0e1216",
          border: "2px solid #ffb454",
        }}
      >
        <div style={{ position: "relative", width: "100%", height: "100%", display: "flex" }}>
          {/* sweep beam: a tapered line from center to the 1-o'clock edge */}
          <div
            style={{
              position: "absolute",
              left: "50%",
              bottom: "50%",
              width: "2px",
              height: "13px",
              background: "linear-gradient(to top, #ffb454, transparent)",
              transform: "rotate(35deg)",
              transformOrigin: "bottom",
            }}
          />
          {/* a previously-detected contact, away from the sweep's current
              angle -- at the tip it read as an arrowhead, not a radar blip */}
          <div
            style={{
              position: "absolute",
              bottom: "6px",
              left: "6px",
              width: "3px",
              height: "3px",
              borderRadius: "50%",
              background: "#ffb454",
              opacity: 0.55,
            }}
          />
          {/* center */}
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              width: "3px",
              height: "3px",
              marginTop: "-1.5px",
              marginLeft: "-1.5px",
              borderRadius: "50%",
              background: "#ffb454",
            }}
          />
        </div>
      </div>
    ),
    { ...size },
  );
}

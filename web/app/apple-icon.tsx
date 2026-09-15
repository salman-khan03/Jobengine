import { ImageResponse } from "next/og";

// Same glyph as icon.tsx, scaled to iOS's expected home-screen size. Kept as
// a separate file rather than a shared size prop because apple-icon needs a
// fully opaque background (iOS applies its own rounded-mask + shadow; a
// transparent edge here shows as a faint square behind the mask) and a
// thicker ring proportionate to 180px instead of 32px.
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0e1216",
        }}
      >
        <div
          style={{
            width: "140px",
            height: "140px",
            borderRadius: "50%",
            border: "8px solid #ffb454",
            display: "flex",
            position: "relative",
          }}
        >
          {/* inner range ring -- the one thing that actually reads as
              "radar screen" rather than "compass face" or "gauge" */}
          <div
            style={{
              position: "absolute",
              top: "28px",
              left: "28px",
              width: "84px",
              height: "84px",
              borderRadius: "50%",
              border: "3px solid #ffb454",
              opacity: 0.35,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: "50%",
              bottom: "50%",
              width: "8px",
              height: "62px",
              background: "linear-gradient(to top, #ffb454, transparent)",
              transform: "rotate(35deg)",
              transformOrigin: "bottom",
            }}
          />
          {/* a previously-detected contact, off the sweep's current angle --
              at the beam's tip this read as an arrowhead, not a radar blip */}
          <div
            style={{
              position: "absolute",
              bottom: "22px",
              left: "24px",
              width: "13px",
              height: "13px",
              borderRadius: "50%",
              background: "#ffb454",
              opacity: 0.55,
            }}
          />
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              width: "14px",
              height: "14px",
              marginTop: "-7px",
              marginLeft: "-7px",
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

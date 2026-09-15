import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "RoleRadar — Evidence-Grounded Job Intelligence",
    short_name: "RoleRadar",
    description:
      "Explainable application decisions: every claim cites a resume line, unsupported AI claims are deleted, not softened.",
    start_url: "/",
    display: "standalone",
    // Matches globals.css --ink / --amber — a PWA install icon and splash
    // screen that don't match the site's own palette read as unfinished.
    background_color: "#0e1216",
    theme_color: "#0e1216",
    icons: [
      { src: "/icon", sizes: "32x32", type: "image/png" },
      { src: "/apple-icon", sizes: "180x180", type: "image/png" },
    ],
  };
}

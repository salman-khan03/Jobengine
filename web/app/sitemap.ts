import type { MetadataRoute } from "next";

// No fixed domain yet — this repo hasn't been deployed (see DEPLOY.md). Set
// NEXT_PUBLIC_SITE_URL to the real production URL once it exists; every path
// below is built from it so nothing needs to change at that point beyond the
// env var itself.
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function sitemap(): MetadataRoute.Sitemap {
  // Priority reflects what actually earns a click from search, not page
  // importance to the codebase: the two pages that work signed-out and
  // demonstrate the product (/, /radar) outrank auth-gated or CLI-adjacent
  // pages a search visitor can't use without first understanding the
  // product anyway.
  const routes: { path: string; priority: number; changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"] }[] = [
    { path: "", priority: 1.0, changeFrequency: "daily" },
    { path: "/radar", priority: 0.9, changeFrequency: "weekly" },
    { path: "/jobs", priority: 0.7, changeFrequency: "daily" },
    { path: "/tracker", priority: 0.3, changeFrequency: "monthly" },
    { path: "/login", priority: 0.2, changeFrequency: "yearly" },
    { path: "/register", priority: 0.2, changeFrequency: "yearly" },
  ];

  return routes.map((r) => ({
    url: `${SITE_URL}${r.path}`,
    lastModified: new Date(),
    changeFrequency: r.changeFrequency,
    priority: r.priority,
  }));
}

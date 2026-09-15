import type { MetadataRoute } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // /dashboard and /tracker are auth-gated already, so this isn't a
      // security boundary — it just keeps a crawler from spending its
      // budget on pages it can't read anyway and that add nothing to search
      // results for someone who doesn't already have an account.
      disallow: ["/dashboard", "/tracker"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}

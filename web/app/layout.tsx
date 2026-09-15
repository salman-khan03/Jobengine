import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { AuthProvider } from "@/components/AuthProvider";
import { NavAuthStatus } from "@/components/NavAuthStatus";
import { Logo } from "@/components/Logo";
import "./globals.css";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
const TITLE = "RoleRadar — Evidence-Grounded AI Job Intelligence";
const DESCRIPTION =
  "Turn resume evidence and job requirements into explainable application decisions. Every claim cites a resume line; unsupported AI claims are deleted, not softened. Built on JobEngine's sponsor-aware listings pipeline.";

export const metadata: Metadata = {
  // Required for the OG/Twitter image file conventions to resolve to an
  // absolute URL — without it they'd emit a relative path, which most
  // link-unfurlers (Slack, LinkedIn, iMessage) silently refuse to fetch.
  metadataBase: new URL(SITE_URL),
  title: TITLE,
  description: DESCRIPTION,
  keywords: [
    "H-1B sponsorship jobs",
    "international student job search",
    "software engineering internships",
    "new grad software engineer",
    "job application tracker",
    "AI resume matching",
    "visa sponsorship tracker",
  ],
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: "RoleRadar",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
};

// Separate from `metadata` as of the App Router's current Metadata API —
// themeColor lives in `viewport`, not `metadata`; putting it in the wrong
// export is silently ignored rather than an error, so this is checked
// against generateViewport's docs rather than carried over from memory.
export const viewport: Viewport = {
  themeColor: "#0e1216",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className="h-full"
    >
      <body className="min-h-full flex flex-col bg-[var(--ink)] text-[var(--text)] antialiased">
        <AuthProvider>
          <header className="border-b border-[var(--line)]">
            {/* Wraps rather than overflows: six links at 375px do not fit on
                one line, and a horizontally scrolling header hides nav items
                behind a gesture most users never try. */}
            <nav className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-4 font-[family-name:var(--font-mono)] text-sm sm:gap-x-6 sm:px-6 sm:py-5">
              <Link href="/" className="flex items-center gap-2 text-[var(--text)]">
                <Logo />
                RoleRadar
              </Link>
              <Link href="/#metrics" className="text-[var(--muted)] hover:text-[var(--amber)]">
                metrics
              </Link>
              <Link href="/jobs" className="text-[var(--muted)] hover:text-[var(--amber)]">
                jobs
              </Link>
              <Link href="/radar" className="text-[var(--muted)] hover:text-[var(--amber)]">
                radar
              </Link>
              <Link href="/tracker" className="text-[var(--muted)] hover:text-[var(--amber)]">
                tracker
              </Link>
              <Link href="/dashboard" className="text-[var(--muted)] hover:text-[var(--amber)]">
                dashboard
              </Link>
              <NavAuthStatus />
            </nav>
          </header>
          <main className="flex-1">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}

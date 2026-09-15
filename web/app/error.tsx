"use client"; // Error boundaries must be Client Components.

import { useEffect } from "react";
import Link from "next/link";

/**
 * Route-level error boundary. Without this, an unhandled render error shows
 * the user a blank page and tells them nothing.
 *
 * Next 16 note: the recovery prop is `unstable_retry` (added in 16.2), which
 * re-fetches *and* re-renders the segment. The older `reset` only clears the
 * error state and re-renders with the same failed data — which for a page
 * whose failure came from a bad API response just re-throws immediately.
 */
export default function Error({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    // No error-reporting service is wired up yet; the console is the honest
    // current state rather than a stub that pretends telemetry exists.
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-2xl flex-col items-start gap-4 px-4 py-16 sm:px-6">
      <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
        Something broke on this page
      </h1>
      <p className="text-sm text-[var(--muted)]">
        This is a bug, not something you did. Retrying re-fetches the page&apos;s data — if
        the API is down, it will keep failing until the service recovers.
      </p>
      {error.digest && (
        <p className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
          error id: {error.digest}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => unstable_retry()}
          className="rounded-md bg-[var(--amber)] px-4 py-1.5 font-[family-name:var(--font-mono)] text-sm font-semibold text-[#161006]"
        >
          Try again
        </button>
        <Link
          href="/"
          className="rounded-md border border-[var(--line)] px-4 py-1.5 font-[family-name:var(--font-mono)] text-sm text-[var(--muted)] hover:text-[var(--text)]"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}

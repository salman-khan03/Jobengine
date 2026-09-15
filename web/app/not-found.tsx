import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-start gap-4 px-4 py-16 sm:px-6">
      <p className="font-[family-name:var(--font-mono)] text-sm text-[var(--amber)]">404</p>
      <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
        No such page
      </h1>
      <p className="text-sm text-[var(--muted)]">
        The link is wrong or the page moved.
      </p>
      <div className="flex flex-wrap gap-3 font-[family-name:var(--font-mono)] text-sm">
        <Link href="/jobs" className="text-[var(--amber)] hover:underline">
          browse jobs
        </Link>
        <Link href="/tracker" className="text-[var(--amber)] hover:underline">
          tracker
        </Link>
        <Link href="/" className="text-[var(--muted)] hover:text-[var(--text)]">
          home
        </Link>
      </div>
    </div>
  );
}

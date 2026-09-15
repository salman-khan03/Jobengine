"use client";

import { useState, Suspense } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const requestedNext = params.get("next");
  const next = requestedNext?.startsWith("/") && !requestedNext.startsWith("//")
    ? requestedNext : "/radar";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const res = await signIn("credentials", { email, password, redirect: false });
    setSubmitting(false);
    if (res?.error) {
      setError("Incorrect email or password.");
      return;
    }
    router.push(next);
    router.refresh();
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-6 px-6 py-20">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
          Sign in
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Your applications, scoped to your account only.
        </p>
      </div>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="email" className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            Email
          </label>
          <input
            id="email"
            autoComplete="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-sm text-[var(--text)]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="password" className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            Password
          </label>
          <input
            id="password"
            autoComplete="current-password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-sm text-[var(--text)]"
          />
        </div>
        {error && <p className="text-sm text-[var(--status-warn)]">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-[var(--amber)] px-4 py-2 font-[family-name:var(--font-mono)] text-sm font-semibold text-[#161006] disabled:opacity-50"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="text-sm text-[var(--muted)]">
        No account?{" "}
        <Link href="/register" className="text-[var(--amber)] underline underline-offset-2">
          Register
        </Link>
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

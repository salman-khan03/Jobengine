"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8765";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Registration failed");
      }
      // Registration succeeded on the backend — now establish the NextAuth
      // session through the same Credentials flow login uses, so the two
      // paths never drift apart.
      const signInRes = await signIn("credentials", { email, password, redirect: false });
      if (signInRes?.error) throw new Error("Registered, but sign-in failed — try logging in.");
      router.push("/tracker");
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-6 px-6 py-20">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">
          Create an account
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Email + password, 8 characters minimum. Nothing else required.
        </p>
      </div>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <label className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            Email
          </label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-sm text-[var(--text)]"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="font-[family-name:var(--font-mono)] text-xs text-[var(--muted)]">
            Password
          </label>
          <input
            type="password"
            required
            minLength={8}
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
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="text-sm text-[var(--muted)]">
        Already have an account?{" "}
        <Link href="/login" className="text-[var(--amber)] underline underline-offset-2">
          Sign in
        </Link>
      </p>
    </div>
  );
}

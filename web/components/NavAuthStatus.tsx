"use client";

import { useSession, signOut } from "next-auth/react";
import Link from "next/link";

export function NavAuthStatus() {
  const { data: session, status } = useSession();

  if (status === "loading") return null;

  if (!session) {
    return (
      <Link href="/login" className="ml-auto text-[var(--muted)] hover:text-[var(--amber)]">
        sign in
      </Link>
    );
  }

  return (
    <div className="ml-auto flex items-center gap-4">
      <span className="text-[var(--faint)]">{session.user?.email}</span>
      <button onClick={() => signOut({ callbackUrl: "/" })} className="text-[var(--muted)] hover:text-[var(--amber)]">
        sign out
      </button>
    </div>
  );
}

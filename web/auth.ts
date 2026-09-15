import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

// Auth.js is the session layer only — it never checks passwords itself.
// authorize() calls our own FastAPI backend's /api/auth/login, which is the
// single source of truth for credentials (same DB the CLI's `users` table
// lives in). The backend's JWT is threaded through the NextAuth JWT/session
// so client components can attach it as a Bearer token on API calls without
// re-implementing auth on the frontend.
const API_URL = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8765";

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email = credentials?.email as string | undefined;
        const password = credentials?.password as string | undefined;
        if (!email || !password) return null;

        const res = await fetch(`${API_URL}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        if (!res.ok) return null;

        const data = await res.json();
        return { id: data.email, email: data.email, backendToken: data.token as string };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) token.backendToken = (user as { backendToken: string }).backendToken;
      return token;
    },
    async session({ session, token }) {
      session.backendToken = token.backendToken as string;
      return session;
    },
  },
});

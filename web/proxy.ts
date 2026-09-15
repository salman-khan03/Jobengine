import { auth } from "@/auth";
import { NextResponse } from "next/server";

// The tracker is the only page with per-user data — jobs browsing and the
// landing page stay public so anyone can see the sponsor-tier metrics
// without an account.
export default auth((req) => {
  const isTracker = req.nextUrl.pathname.startsWith("/tracker");
  if (isTracker && !req.auth) {
    const loginUrl = new URL("/login", req.nextUrl.origin);
    loginUrl.searchParams.set("next", req.nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }
});

export const config = {
  matcher: ["/tracker/:path*"],
};

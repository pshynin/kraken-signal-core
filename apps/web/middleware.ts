/**
 * Next.js Edge Middleware — passcode auth gate.
 *
 * Every request that reaches the dashboard (except /login and the auth API)
 * must carry a valid mc_auth cookie.  If not, the user is redirected to
 * /login with the original path preserved in the ?from= query param.
 *
 * Open mode: if DASHBOARD_PASSCODE is not set (local dev without .env),
 * all requests pass through without authentication.
 */

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { COOKIE_NAME, isValidToken } from "@/lib/auth";

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const passcode = process.env.DASHBOARD_PASSCODE;

  // No passcode configured → open-access dev mode.
  if (!passcode) {
    return NextResponse.next();
  }

  const token = request.cookies.get(COOKIE_NAME)?.value ?? "";
  const authed = await isValidToken(token, passcode);

  if (!authed) {
    const loginUrl = new URL("/login", request.url);
    const from = request.nextUrl.pathname + request.nextUrl.search;
    // Only include ?from= for non-root paths to keep the URL clean.
    if (from !== "/") {
      loginUrl.searchParams.set("from", from);
    }
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /**
     * Run on every route EXCEPT:
     *   /login           — the login page itself
     *   /api/auth/*      — the auth API routes (login / logout)
     *   /_next/static    — Next.js build assets
     *   /_next/image     — Next.js image optimisation
     *   /favicon.ico     — browser favicon
     *   *.png/jpg/svg/…  — static assets served from /public
     */
    "/((?!login|api/auth|_next/static|_next/image|favicon\\.ico|.*\\.(?:png|jpg|jpeg|gif|svg|webp|ico|avif)$).*)",
  ],
};

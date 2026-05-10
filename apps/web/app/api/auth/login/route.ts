import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import {
  COOKIE_MAX_AGE_SECONDS,
  COOKIE_NAME,
  makeAuthToken,
} from "@/lib/auth";

/**
 * POST /api/auth/login
 *
 * Body: { passcode: string }
 *
 * On success: sets an httpOnly mc_auth cookie and returns { ok: true }.
 * On failure: returns 401 { error: "Invalid passcode" }.
 *
 * Open mode: if DASHBOARD_PASSCODE is not set, any passcode is accepted
 * and a dev token is issued (lets the middleware pass through).
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const body = await request.json().catch(() => ({})) as {
    passcode?: string;
  };
  const { passcode = "" } = body;

  const expected = process.env.DASHBOARD_PASSCODE;

  if (!expected) {
    // Open dev mode — issue a dev token so the middleware cookie check passes.
    const response = NextResponse.json({ ok: true });
    response.cookies.set(COOKIE_NAME, await makeAuthToken("dev"), cookieOptions());
    return response;
  }

  if (!passcode || passcode !== expected) {
    return NextResponse.json({ error: "Invalid passcode" }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(COOKIE_NAME, await makeAuthToken(expected), cookieOptions());
  return response;
}

function cookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict" as const,
    maxAge: COOKIE_MAX_AGE_SECONDS,
    path: "/",
  };
}

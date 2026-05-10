import { NextResponse } from "next/server";
import { COOKIE_NAME } from "@/lib/auth";

/**
 * POST /api/auth/logout
 *
 * Clears the mc_auth session cookie. Returns { ok: true }.
 * The client is responsible for redirecting to /login after this call.
 */
export async function POST(): Promise<NextResponse> {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(COOKIE_NAME);
  return response;
}

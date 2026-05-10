/**
 * Passcode-based authentication helpers.
 *
 * Auth model (single-user MVP):
 *   - DASHBOARD_PASSCODE env var holds the raw passcode.
 *   - On successful login, a SHA-256 derived token is stored in an
 *     httpOnly cookie (COOKIE_NAME).
 *   - middleware.ts reads the cookie and calls isValidToken() on every
 *     request to decide whether to redirect to /login.
 *   - The raw passcode is never stored anywhere — only the derived hex token.
 *
 * Not using bcrypt or JWTs: single-user dashboard, no user accounts,
 * passcode resets are done by changing the env var.
 */

export const COOKIE_NAME = "mc_auth";

/** 7-day session by default. */
export const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

/**
 * Derive the cookie token from the raw passcode using Web Crypto SHA-256.
 *
 * Uses globalThis.crypto.subtle so this module is safe to import in both
 * the Next.js Edge Runtime (middleware) and Node.js route handlers.
 * A fixed domain prefix ensures tokens are app-specific.
 */
export async function makeAuthToken(passcode: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(`momentum-copilot:${passcode}`);
  const hashBuffer = await globalThis.crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Returns true iff the cookie value matches the derived token for the given
 * passcode. Async because makeAuthToken is async.
 */
export async function isValidToken(
  cookieValue: string,
  passcode: string
): Promise<boolean> {
  const expected = await makeAuthToken(passcode);
  return cookieValue === expected;
}

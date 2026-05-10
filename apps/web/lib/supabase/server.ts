/**
 * Supabase server-side client.
 *
 * Uses SUPABASE_SERVICE_ROLE_KEY — bypasses RLS, never sent to the browser.
 * Import only from Server Components, Route Handlers, and Server Actions.
 */
import { createClient } from "@supabase/supabase-js";
import type { Database } from "@kraken-signal/shared-types";

function getServerClient() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!url || !key) {
    throw new Error(
      "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY. " +
        "Check your .env file or Vercel environment variables."
    );
  }

  return createClient<Database>(url, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });
}

/** Call once per request — not a singleton (safe for server components). */
export function createServerClient() {
  return getServerClient();
}

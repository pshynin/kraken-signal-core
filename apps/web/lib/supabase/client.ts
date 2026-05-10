/**
 * Supabase browser client.
 *
 * Uses NEXT_PUBLIC_SUPABASE_ANON_KEY — safe to expose to the browser.
 * For the MVP dashboard (read-only, passcode-gated), anon key is sufficient
 * since all tables are public schema with no RLS.
 *
 * Import from Client Components only.
 */
import { createClient } from "@supabase/supabase-js";
import type { Database } from "@kraken-signal/shared-types";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

/** Browser singleton — created once per page load. */
export const supabaseBrowserClient = createClient<Database>(
  supabaseUrl,
  supabaseAnonKey
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0014: grant_permissions
-- Explicit role grants required by PostgREST / Supabase API layer.
--
-- service_role : full access, bypasses RLS — used by scanner + server components
-- authenticated: full access, respects RLS — reserved for future user auth
-- anon         : read-only,  respects RLS — used by browser client (anon key)
-- ─────────────────────────────────────────────────────────────────────────────

GRANT USAGE ON SCHEMA public TO service_role, anon, authenticated;

-- service_role: full read/write on all current and future tables
GRANT ALL ON ALL TABLES    IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL ROUTINES  IN SCHEMA public TO service_role;

-- authenticated: full read/write (RLS policies control actual access)
GRANT ALL ON ALL TABLES    IN SCHEMA public TO authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO authenticated;

-- anon: read-only (RLS policies control actual access)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon;

-- Ensure future tables created in this schema inherit the same grants
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON TABLES    TO service_role, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON SEQUENCES TO service_role, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO anon;

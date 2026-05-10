-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 0014: grant_permissions
-- Explicit role grants required by PostgREST / Supabase API layer.
--
-- service_role : full access, bypasses RLS — used by scanner + server components
-- authenticated: full access, respects RLS — reserved for future user auth
-- anon         : read-only,  respects RLS — used by browser client (anon key)
-- ─────────────────────────────────────────────────────────────────────────────

-- Grants are wrapped in DO blocks so this migration is safe to run in both
-- Supabase (where these roles exist) and plain Postgres CI containers (where
-- they do not). Missing roles are silently skipped.

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT USAGE ON SCHEMA public TO service_role;
    GRANT ALL ON ALL TABLES    IN SCHEMA public TO service_role;
    GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
    GRANT ALL ON ALL ROUTINES  IN SCHEMA public TO service_role;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES    TO service_role;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    GRANT USAGE ON SCHEMA public TO authenticated;
    GRANT ALL ON ALL TABLES    IN SCHEMA public TO authenticated;
    GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES    TO authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    GRANT USAGE ON SCHEMA public TO anon;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO anon;
  END IF;
END $$;

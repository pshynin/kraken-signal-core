import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Supabase realtime and storage packages use Node.js APIs —
  // keep them server-side only and out of the browser bundle.
  serverExternalPackages: ["@supabase/supabase-js"],
};

export default nextConfig;

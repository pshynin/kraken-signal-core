/**
 * @kraken-signal/shared-types
 *
 * Shared TypeScript contracts between the Next.js dashboard and the scanner service.
 *
 * This is a stub for PR 1 (scaffold). Full type definitions, interfaces, and
 * JSON schemas are added in PR 3 (Shared Types / Contracts).
 *
 * Do not import from this package in production code until PR 3 is merged.
 */

// ── Asset lifecycle state machine ────────────────────────────────────────────
export type AssetState =
  | "excluded"
  | "candidate_clean"
  | "candidate_ugly"
  | "alerted"
  | "active"
  | "invalidated"
  | "expired"
  | "entered"       // future: trade tracking
  | "target_hit"    // future: trade tracking
  | "stop_hit"      // future: trade tracking
  | "manually_closed"; // future: trade tracking

// ── Sizing buckets ────────────────────────────────────────────────────────────
export type SizeBucket = "2k" | "2k-5k" | "5k-10k" | "10k-20k" | "20k+";

// ── Candidate category ────────────────────────────────────────────────────────
export type Category = "clean" | "ugly";

// ── Timeframes used in multi-timeframe analysis ───────────────────────────────
export type Timeframe = "4h" | "1h" | "30m";

// ── Scan run status ───────────────────────────────────────────────────────────
export type ScanStatus = "running" | "completed" | "failed" | "partial";

// ── Alert types ───────────────────────────────────────────────────────────────
export type AlertType =
  | "new_candidate"
  | "state_change"
  | "expiry_warning"
  | "invalidation"
  | "system";

// ── Discord channel keys ──────────────────────────────────────────────────────
export type AlertChannel = "discord_clean" | "discord_ugly" | "discord_system";

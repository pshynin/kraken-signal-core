/**
 * Discord webhook payload types.
 * https://discord.com/developers/docs/resources/webhook#execute-webhook
 *
 * The scanner builds these payloads and stores them in alerts_sent.payload (JSONB).
 * The web /alerts page can reconstruct the embed preview from stored payloads.
 */

// ── Discord embed colors (semantic) ───────────────────────────────────────────
/** Clean candidate — emerald green */
export const DISCORD_COLOR_CLEAN = 0x22c55e;
/** Ugly candidate — amber */
export const DISCORD_COLOR_UGLY = 0xf59e0b;
/** System / error — red */
export const DISCORD_COLOR_SYSTEM = 0xef4444;
/** State change / neutral — blue */
export const DISCORD_COLOR_INFO = 0x3b82f6;

// ── Embed components ──────────────────────────────────────────────────────────
export interface DiscordEmbedFooter {
  text: string;
  icon_url?: string;
}

export interface DiscordEmbedAuthor {
  name: string;
  url?: string;
  icon_url?: string;
}

export interface DiscordEmbedField {
  name: string;
  value: string;
  inline?: boolean;
}

export interface DiscordEmbed {
  title?: string;
  description?: string;
  url?: string;
  color?: number;
  timestamp?: string;        // ISO 8601
  footer?: DiscordEmbedFooter;
  author?: DiscordEmbedAuthor;
  fields?: DiscordEmbedField[];
}

// ── Top-level webhook payload ─────────────────────────────────────────────────
export interface DiscordWebhookPayload {
  username?: string;
  avatar_url?: string;
  content?: string;
  embeds?: DiscordEmbed[];    // max 10 embeds per message
}

// ── Candidate alert embed (structured) ───────────────────────────────────────
/**
 * The structured data used to build a candidate alert embed.
 * One of these is constructed per candidate in the alert formatter (PR 11).
 */
export interface CandidateAlertData {
  symbol: string;
  kraken_pair: string;
  category: "clean" | "ugly";
  rank: number;

  score_total: number;
  probability_pct: number;

  entry_price: number;
  entry_price_low: number | null;
  entry_price_high: number | null;
  exit_price: number;
  stop_loss: number;

  expected_gain_pct: number;
  reward_risk_ratio: number;
  suggested_size_bucket: string;

  notes: string | null;

  scan_run_id: string;
  scanned_at: string;        // ISO 8601
}

// ── System health alert ───────────────────────────────────────────────────────
export interface SystemAlertData {
  alert_subtype: "stale_run" | "scanner_error" | "startup" | "health_check";
  message: string;
  details?: string;
  scan_run_id?: string;
  timestamp: string;
}

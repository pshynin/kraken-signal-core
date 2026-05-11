/**
 * Supabase queries for the alert history page (/alerts).
 */

import { createServerClient } from "@/lib/supabase/server";

export interface AlertHistoryRow {
  id: string;
  scan_run_id: string;
  symbol: string;
  alert_type: string;
  channel: string;
  delivery_status: string;
  sent_at: string | null;
  error_message: string | null;
  created_at: string;
}

interface RawAlertRow {
  id: string;
  scan_run_id: string;
  alert_type: string;
  channel: string;
  delivery_status: string;
  sent_at: string | null;
  error_message: string | null;
  created_at: string;
  assets: { symbol: string } | null;
}

/** Fetch paginated alert history, newest first. */
export async function fetchAlertHistory(
  limit = 100,
  offset = 0
): Promise<AlertHistoryRow[]> {
  try {
    const client = createServerClient();
    const { data, error } = await client
      .from("alerts_sent")
      .select(
        `id, scan_run_id, alert_type, channel, delivery_status,
         sent_at, error_message, created_at,
         assets ( symbol )`
      )
      .order("created_at", { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      console.error("fetchAlertHistory:", error.message);
      return [];
    }

    return ((data ?? []) as unknown as RawAlertRow[]).map((r) => ({
      id: r.id,
      scan_run_id: r.scan_run_id,
      symbol: r.assets?.symbol ?? "???",
      alert_type: r.alert_type,
      channel: r.channel,
      delivery_status: r.delivery_status,
      sent_at: r.sent_at,
      error_message: r.error_message,
      created_at: r.created_at,
    }));
  } catch (err) {
    console.error("fetchAlertHistory exception:", err);
    return [];
  }
}

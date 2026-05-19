import type { Metadata } from "next";
import { createServerClient } from "@/lib/supabase/server";
import { SettingsForm, type RawSettingRow } from "@/components/settings/settings-form";
import { PageShell, PageHeader } from "@/components/shell/page-shell";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Settings" };

async function fetchSettings(): Promise<RawSettingRow[]> {
  try {
    const client = createServerClient();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { data, error } = await (client as any)
      .from("strategy_settings")
      .select("setting_key, setting_value, description, updated_at")
      .order("setting_key");

    if (error) {
      console.error("fetchSettings:", error.message);
      return [];
    }
    return (data ?? []) as RawSettingRow[];
  } catch (err) {
    console.error("fetchSettings exception:", err);
    return [];
  }
}

export default async function SettingsPage() {
  const settings = await fetchSettings();

  const lastUpdated =
    settings.length > 0
      ? new Date(
          Math.max(...settings.map((s) => new Date(s.updated_at).getTime()))
        ).toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : null;

  const subtitle = (
    <>
      {settings.length} parameters loaded from database
      {lastUpdated && (
        <span className="ml-2 text-muted-foreground/60">
          · last updated {lastUpdated}
        </span>
      )}
    </>
  );

  return (
    <PageShell>
      <PageHeader title="Strategy Settings" subtitle={subtitle} />
      <SettingsForm settings={settings} />
    </PageShell>
  );
}

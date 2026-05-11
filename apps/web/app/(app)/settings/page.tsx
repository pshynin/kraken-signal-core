import { createServerClient } from "@/lib/supabase/server";
import { SettingsForm, type RawSettingRow } from "@/components/settings/settings-form";

export const dynamic = "force-dynamic";

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

  return (
    <div className="mx-auto max-w-5xl px-8 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">
          Strategy Settings
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {settings.length} parameters loaded from database
          {lastUpdated && (
            <span className="ml-2 text-muted-foreground/60">
              · last updated {lastUpdated}
            </span>
          )}
        </p>
      </div>
      <SettingsForm settings={settings} />
    </div>
  );
}

"use server";

import { createServerClient } from "@/lib/supabase/server";
import { revalidatePath } from "next/cache";

export interface UpdateResult {
  error?: string;
}

/**
 * Update a single strategy_settings row by key.
 * valueJson is a JSON-encoded string of the new value.
 */
export async function updateSetting(
  key: string,
  valueJson: string
): Promise<UpdateResult> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(valueJson);
  } catch {
    return { error: "Invalid JSON value." };
  }

  try {
    const client = createServerClient();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { error } = await (client as any)
      .from("strategy_settings")
      .update({ setting_value: parsed })
      .eq("setting_key", key);

    if (error) return { error: error.message };

    revalidatePath("/settings");
    return {};
  } catch (err) {
    return { error: String(err) };
  }
}

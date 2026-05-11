"use client";

import { useState, useTransition } from "react";
import { updateSetting } from "@/app/settings/actions";
import { cn } from "@/lib/utils";

export interface RawSettingRow {
  setting_key: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setting_value: any;
  description: string | null;
  updated_at: string;
}

// ── helpers ───────────────────────────────────────────────────────────────────

const GROUPS = ["clean", "ugly", "global", "scanner", "scoring", "sizing"] as const;
type Group = (typeof GROUPS)[number];

const GROUP_LABELS: Record<Group, string> = {
  clean: "Clean",
  ugly: "Ugly",
  global: "Global",
  scanner: "Scanner",
  scoring: "Scoring",
  sizing: "Sizing",
};

function groupOf(key: string): Group {
  const prefix = key.split(".")[0] as Group;
  return GROUPS.includes(prefix) ? prefix : "global";
}

function valueType(val: unknown): "boolean" | "number" | "json" {
  if (typeof val === "boolean") return "boolean";
  if (typeof val === "number") return "number";
  return "json";
}

// ── sub-components ────────────────────────────────────────────────────────────

function StatusDot({ state }: { state: "idle" | "saving" | "ok" | "err" }) {
  if (state === "idle") return null;
  return (
    <span
      className={cn("ml-2 text-xs", {
        "text-muted-foreground animate-pulse": state === "saving",
        "text-emerald-400": state === "ok",
        "text-red-400": state === "err",
      })}
    >
      {state === "saving" ? "saving…" : state === "ok" ? "saved" : "error"}
    </span>
  );
}

interface FieldProps {
  row: RawSettingRow;
}

function SettingField({ row }: FieldProps) {
  const type = valueType(row.setting_value);
  const [draft, setDraft] = useState<string>(
    type === "json"
      ? JSON.stringify(row.setting_value, null, 2)
      : String(row.setting_value)
  );
  const [status, setStatus] = useState<"idle" | "saving" | "ok" | "err">("idle");
  const [isPending, startTransition] = useTransition();

  const isDirty =
    type === "boolean"
      ? draft !== String(row.setting_value)
      : draft !== (type === "json"
          ? JSON.stringify(row.setting_value, null, 2)
          : String(row.setting_value));

  async function save() {
    setStatus("saving");
    let valueJson: string;
    if (type === "boolean") {
      valueJson = draft; // "true" or "false"
    } else if (type === "number") {
      const n = Number(draft);
      if (isNaN(n)) { setStatus("err"); return; }
      valueJson = String(n);
    } else {
      valueJson = draft;
    }

    startTransition(async () => {
      const result = await updateSetting(row.setting_key, valueJson);
      setStatus(result.error ? "err" : "ok");
      setTimeout(() => setStatus("idle"), 2500);
    });
  }

  const shortKey = row.setting_key.split(".").slice(1).join(".");

  return (
    <div className="flex items-start gap-4 rounded-lg px-4 py-3 hover:bg-muted/20 transition-colors">
      {/* Key + description */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-medium text-foreground">
            {shortKey}
          </span>
          <StatusDot state={isPending ? "saving" : status} />
        </div>
        {row.description && (
          <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">
            {row.description}
          </p>
        )}
      </div>

      {/* Input */}
      <div className="flex shrink-0 items-center gap-2">
        {type === "boolean" ? (
          <button
            onClick={() => {
              const next = draft === "true" ? "false" : "true";
              setDraft(next);
            }}
            className={cn(
              "relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none",
              draft === "true" ? "bg-primary" : "bg-muted-foreground/30"
            )}
          >
            <span
              className={cn(
                "inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform",
                draft === "true" ? "translate-x-4" : "translate-x-1"
              )}
            />
          </button>
        ) : type === "number" ? (
          <input
            type="number"
            value={draft}
            step="any"
            onChange={(e) => setDraft(e.target.value)}
            className="w-28 rounded border border-border bg-card px-2 py-1 text-right font-mono text-sm text-foreground focus:border-primary focus:outline-none"
          />
        ) : (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-64 rounded border border-border bg-card px-2 py-1 font-mono text-xs text-foreground focus:border-primary focus:outline-none resize-y"
          />
        )}

        <button
          onClick={save}
          disabled={!isDirty || isPending}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium transition-colors",
            isDirty && !isPending
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "cursor-not-allowed bg-muted text-muted-foreground"
          )}
        >
          Save
        </button>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  settings: RawSettingRow[];
}

export function SettingsForm({ settings }: Props) {
  const [activeGroup, setActiveGroup] = useState<Group>("clean");

  const grouped = Object.fromEntries(
    GROUPS.map((g) => [g, settings.filter((s) => groupOf(s.setting_key) === g)])
  ) as Record<Group, RawSettingRow[]>;

  return (
    <div className="space-y-4">
      {/* Tabs */}
      <div className="flex gap-1 rounded-lg border border-border bg-card p-1">
        {GROUPS.map((g) => (
          <button
            key={g}
            onClick={() => setActiveGroup(g)}
            className={cn(
              "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              activeGroup === g
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {GROUP_LABELS[g]}
            <span className="ml-1 text-muted-foreground/60">
              ({grouped[g].length})
            </span>
          </button>
        ))}
      </div>

      {/* Fields */}
      <div className="divide-y divide-border rounded-lg border border-border bg-card">
        {grouped[activeGroup].length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No settings in this group.
          </p>
        ) : (
          grouped[activeGroup].map((row) => (
            <SettingField key={row.setting_key} row={row} />
          ))
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Changes take effect on the next scanner run.
      </p>
    </div>
  );
}

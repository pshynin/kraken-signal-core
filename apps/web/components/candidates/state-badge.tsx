import { cn } from "@/lib/utils";
import type { RecommendationCategory } from "@kraken-signal/shared-types";

// ── Category badge (Clean / Ugly) ─────────────────────────────────────────────

interface CategoryBadgeProps {
  category: RecommendationCategory;
}

export function CategoryBadge({ category }: CategoryBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5",
        "text-[10px] font-bold uppercase tracking-widest",
        category === "clean"
          ? "bg-bull/15 text-bull"
          : "bg-caution/15 text-caution"
      )}
    >
      {category}
    </span>
  );
}

// ── Asset state badge ─────────────────────────────────────────────────────────

const STATE_MAP: Record<string, { label: string; className: string }> = {
  candidate_clean: { label: "New", className: "bg-bull/10 text-bull" },
  candidate_ugly: { label: "New", className: "bg-caution/10 text-caution" },
  alerted: {
    label: "Alerted",
    className: "bg-sky-500/10 text-sky-400",
  },
  active: {
    label: "Active",
    className: "bg-indigo-500/10 text-indigo-400",
  },
  invalidated: { label: "Invalid", className: "bg-bear/10 text-bear" },
  expired: {
    label: "Expired",
    className: "bg-muted text-muted-foreground",
  },
};

interface StateBadgeProps {
  state: string;
}

export function StateBadge({ state }: StateBadgeProps) {
  const cfg = STATE_MAP[state] ?? {
    label: state.replace(/_/g, " "),
    className: "bg-muted text-muted-foreground",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        cfg.className
      )}
    >
      {cfg.label}
    </span>
  );
}

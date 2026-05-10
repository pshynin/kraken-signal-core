"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown, ListX } from "lucide-react";

import type { CandidateTableRow, RecommendationCategory } from "@kraken-signal/shared-types";
import { cn, formatRelativeTime } from "@/lib/utils";
import { CategoryBadge, StateBadge } from "./state-badge";

// ── Price / percentage formatters ─────────────────────────────────────────────

function fmtPrice(price: number): string {
  if (price <= 0) return "—";
  if (price < 0.00001) return `$${price.toExponential(3)}`;
  if (price < 0.0001) return `$${price.toFixed(8)}`;
  if (price < 0.01) return `$${price.toFixed(6)}`;
  if (price < 1) return `$${price.toFixed(4)}`;
  if (price < 10) return `$${price.toFixed(3)}`;
  if (price < 10_000) return `$${price.toFixed(2)}`;
  return `$${price.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function fmtPct(val: number | null, forceSign = true): string {
  if (val == null) return "—";
  const sign = forceSign && val > 0 ? "+" : "";
  return `${sign}${val.toFixed(1)}%`;
}

/** Stop distance as % below entry (negative value). */
function stopDistPct(entry: number, stop: number): string {
  if (!entry) return "";
  return fmtPct(((stop - entry) / entry) * 100, false);
}

// ── Sorting ───────────────────────────────────────────────────────────────────

type SortKey =
  | "rank"
  | "score_total"
  | "probability_pct"
  | "reward_risk_ratio"
  | "expected_gain_pct"
  | "scanned_at";

type SortDir = "asc" | "desc";

interface SortState {
  key: SortKey;
  dir: SortDir;
}

function sortRows(rows: CandidateTableRow[], { key, dir }: SortState): CandidateTableRow[] {
  const mult = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1 * mult;
    if (bv == null) return -1 * mult;
    if (typeof av === "string" && typeof bv === "string") {
      return mult * av.localeCompare(bv);
    }
    return mult * ((av as number) - (bv as number));
  });
}

// ── Category filter ───────────────────────────────────────────────────────────

type CategoryFilter = "all" | RecommendationCategory;

// ── Table cell primitives ─────────────────────────────────────────────────────

function Td({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <td className={cn("px-3 py-3 align-middle", className)}>{children}</td>
  );
}

interface ThProps {
  children: React.ReactNode;
  sortKey?: SortKey;
  sort?: SortState;
  onSort?: (k: SortKey) => void;
  className?: string;
}

function Th({ children, sortKey, sort, onSort, className }: ThProps) {
  const sortable = !!sortKey;
  const active = sort?.key === sortKey;
  return (
    <th
      onClick={sortable && sortKey ? () => onSort?.(sortKey) : undefined}
      className={cn(
        "px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground",
        sortable && "cursor-pointer select-none hover:text-foreground",
        className
      )}
    >
      <span className="flex items-center gap-1">
        {children}
        {sortable && (
          active ? (
            sort?.dir === "asc" ? (
              <ChevronUp className="h-3 w-3 text-foreground" />
            ) : (
              <ChevronDown className="h-3 w-3 text-foreground" />
            )
          ) : (
            <ChevronsUpDown className="h-3 w-3 opacity-30" />
          )
        )}
      </span>
    </th>
  );
}

// ── Candidate table ───────────────────────────────────────────────────────────

interface CandidatesTableProps {
  rows: CandidateTableRow[];
  initialCategory?: CategoryFilter;
}

export function CandidatesTable({
  rows,
  initialCategory = "all",
}: CandidatesTableProps) {
  const [category, setCategory] = useState<CategoryFilter>(initialCategory);
  const [sort, setSort] = useState<SortState>({ key: "rank", dir: "asc" });

  function toggleSort(key: SortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "scanned_at" ? "desc" : "asc" }
    );
  }

  const cleanCount = rows.filter((r) => r.category === "clean").length;
  const uglyCount = rows.filter((r) => r.category === "ugly").length;

  const tabs: { value: CategoryFilter; label: string; count: number }[] = [
    { value: "all", label: "All", count: rows.length },
    { value: "clean", label: "Clean", count: cleanCount },
    { value: "ugly", label: "Ugly", count: uglyCount },
  ];

  const displayed = useMemo(() => {
    const filtered =
      category === "all" ? rows : rows.filter((r) => r.category === category);
    return sortRows(filtered, sort);
  }, [rows, category, sort]);

  return (
    <div className="space-y-0">
      {/* Category tabs */}
      <div className="flex items-center gap-0 border-b border-border">
        {tabs.map(({ value, label, count }) => (
          <button
            key={value}
            onClick={() => setCategory(value)}
            className={cn(
              "flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
              category === value
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
            <span
              className={cn(
                "rounded-full px-1.5 py-0.5 text-xs",
                category === value
                  ? "bg-muted text-foreground"
                  : "bg-muted/40 text-muted-foreground"
              )}
            >
              {count}
            </span>
          </button>
        ))}
      </div>

      {/* Empty state */}
      {displayed.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-b-lg border-x border-b border-border bg-card py-16">
          <ListX className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium text-foreground">
            No active candidates
          </p>
          <p className="text-xs text-muted-foreground max-w-xs text-center">
            Candidates appear here after the scanner identifies qualifying
            assets. Runs every 6 hours.
          </p>
        </div>
      ) : (
        /* Table */
        <div className="overflow-x-auto rounded-b-lg border-x border-b border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-card/80">
                <Th className="w-10">#</Th>
                <Th>Symbol</Th>
                <Th className="w-16">Type</Th>
                <Th sortKey="score_total" sort={sort} onSort={toggleSort}>
                  Score
                </Th>
                <Th>Entry Zone</Th>
                <Th sortKey="expected_gain_pct" sort={sort} onSort={toggleSort}>
                  Target
                </Th>
                <Th>Stop</Th>
                <Th sortKey="reward_risk_ratio" sort={sort} onSort={toggleSort}>
                  R:R
                </Th>
                <Th className="w-16">Size</Th>
                <Th className="w-20">Status</Th>
                <Th sortKey="scanned_at" sort={sort} onSort={toggleSort}>
                  Age
                </Th>
              </tr>
            </thead>
            <tbody>
              {displayed.map((row, i) => (
                <tr
                  key={row.id}
                  className={cn(
                    "border-b border-border/40 transition-colors hover:bg-muted/20",
                    i % 2 === 0 ? "bg-background" : "bg-card/20"
                  )}
                >
                  {/* Rank */}
                  <Td className="w-10 tabular-nums text-muted-foreground text-xs">
                    {row.rank}
                  </Td>

                  {/* Symbol */}
                  <Td>
                    <span className="font-mono font-semibold text-foreground tracking-tight">
                      {row.symbol}
                    </span>
                    {row.notes && (
                      <p className="mt-0.5 text-[10px] text-muted-foreground truncate max-w-[140px]">
                        {row.notes}
                      </p>
                    )}
                  </Td>

                  {/* Category */}
                  <Td className="w-16">
                    <CategoryBadge category={row.category} />
                  </Td>

                  {/* Score */}
                  <Td>
                    <div className="tabular-nums">
                      <span className="font-semibold text-foreground">
                        {row.score_total.toFixed(1)}
                      </span>
                      {row.probability_pct != null && (
                        <span className="ml-1.5 text-xs text-muted-foreground">
                          {row.probability_pct.toFixed(0)}%
                        </span>
                      )}
                    </div>
                  </Td>

                  {/* Entry Zone */}
                  <Td>
                    <div className="tabular-nums leading-snug">
                      <div className="text-foreground font-medium">
                        {fmtPrice(row.entry_price)}
                      </div>
                      {row.entry_price_low != null &&
                        row.entry_price_high != null && (
                          <div className="text-[11px] text-muted-foreground">
                            {fmtPrice(row.entry_price_low)}
                            &ndash;
                            {fmtPrice(row.entry_price_high)}
                          </div>
                        )}
                    </div>
                  </Td>

                  {/* Target */}
                  <Td>
                    <div className="tabular-nums leading-snug">
                      <div className="text-bull font-medium">
                        {fmtPrice(row.exit_price)}
                      </div>
                      {row.expected_gain_pct != null && (
                        <div className="text-[11px] text-bull/70">
                          {fmtPct(row.expected_gain_pct)}
                        </div>
                      )}
                    </div>
                  </Td>

                  {/* Stop */}
                  <Td>
                    <div className="tabular-nums leading-snug">
                      <div className="text-bear font-medium">
                        {fmtPrice(row.stop_loss)}
                      </div>
                      <div className="text-[11px] text-bear/70">
                        {stopDistPct(row.entry_price, row.stop_loss)}
                      </div>
                    </div>
                  </Td>

                  {/* R:R */}
                  <Td>
                    {row.reward_risk_ratio != null ? (
                      <span
                        className={cn(
                          "tabular-nums font-medium",
                          row.reward_risk_ratio >= 3
                            ? "text-bull"
                            : row.reward_risk_ratio >= 2
                              ? "text-foreground"
                              : "text-muted-foreground"
                        )}
                      >
                        {row.reward_risk_ratio.toFixed(1)}
                        <span className="text-xs">×</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </Td>

                  {/* Size */}
                  <Td className="w-16">
                    <span className="font-mono text-xs text-muted-foreground">
                      ${row.suggested_size_bucket}
                    </span>
                  </Td>

                  {/* State */}
                  <Td className="w-20">
                    <StateBadge state={row.state} />
                  </Td>

                  {/* Age */}
                  <Td className="tabular-nums text-xs text-muted-foreground whitespace-nowrap">
                    {formatRelativeTime(row.scanned_at)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

import { notFound } from "next/navigation";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { fetchAssetHistory } from "@/lib/queries/diagnostics";
import { PageShell } from "@/components/shell/page-shell";

export const dynamic = "force-dynamic";

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stateLabel(state: string | null): string {
  if (!state) return "—";
  return state.replace(/_/g, " ");
}

export default async function AssetHistoryPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol: rawSymbol } = await params;
  const symbol = decodeURIComponent(rawSymbol);
  const view = await fetchAssetHistory(symbol);

  if (!view) notFound();

  const latest = view.history[0];

  return (
    <PageShell>
      <Link
        href="/candidates"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Candidates
      </Link>

      <header className="space-y-1">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[1.375rem] font-semibold tracking-tight text-foreground font-mono">
            {view.symbol}
          </h1>
          {!view.is_active && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              inactive
            </span>
          )}
        </div>
        {latest && (
          <p className="text-sm text-muted-foreground">
            Last seen as{" "}
            <span className="text-foreground font-medium capitalize">
              {stateLabel(latest.to_state)}
            </span>{" "}
            on {formatTimestamp(latest.created_at)}.
          </p>
        )}
      </header>

      <section>
        <h2 className="mb-3 text-sm font-semibold tracking-tight text-foreground">
          State History ({view.history.length}
          {view.history.length === 100 ? "+" : ""})
        </h2>
        {view.history.length === 0 ? (
          <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border/70 text-sm text-muted-foreground">
            No history yet for {view.symbol}.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border/70 bg-card shadow-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 bg-muted/30 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-3 font-medium">When</th>
                  <th className="px-4 py-3 font-medium">From</th>
                  <th className="px-4 py-3 font-medium">To</th>
                  <th className="px-4 py-3 font-medium">Reason</th>
                  <th className="px-4 py-3 font-medium">Run</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {view.history.map((row, i) => (
                  <tr
                    key={`${row.created_at}-${i}`}
                    className="transition-colors hover:bg-muted/20"
                  >
                    <td className="px-4 py-2.5 tabular-nums text-muted-foreground whitespace-nowrap">
                      {formatTimestamp(row.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground capitalize">
                      {stateLabel(row.from_state)}
                    </td>
                    <td className="px-4 py-2.5 text-xs font-medium text-foreground capitalize">
                      {stateLabel(row.to_state)}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                      {row.reason ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                      {row.scan_run_id ? (
                        <Link
                          href={`/scans/${row.scan_run_id}`}
                          className="hover:underline"
                        >
                          {row.scan_run_id.slice(0, 8)}…
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </PageShell>
  );
}

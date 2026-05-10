import { Sidebar } from "@/components/shell/sidebar";
import { CandidatesTable } from "@/components/candidates/candidates-table";
import { fetchActiveCandidates } from "@/lib/queries/candidates";
import type { RecommendationCategory } from "@kraken-signal/shared-types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function isCategory(v: string | undefined): v is RecommendationCategory {
  return v === "clean" || v === "ugly";
}

// ── Page ──────────────────────────────────────────────────────────────────────

// Next.js 15: searchParams is a Promise in Server Components.
interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function CandidatesPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const cat = typeof params.cat === "string" ? params.cat : undefined;
  const initialCategory = isCategory(cat) ? cat : "all";

  const rows = await fetchActiveCandidates();

  const cleanCount = rows.filter((r) => r.category === "clean").length;
  const uglyCount = rows.filter((r) => r.category === "ugly").length;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />

      <main className="flex-1 overflow-auto">
        <div className="mx-auto max-w-7xl px-8 py-8 space-y-6">
          {/* Header */}
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-xl font-semibold text-foreground">
                Candidates
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Active scanner candidates with entry, target, and stop
                parameters.
              </p>
            </div>

            {rows.length > 0 && (
              <div className="flex items-center gap-3 pt-1 text-xs tabular-nums">
                <span className="text-bull font-medium">
                  {cleanCount} clean
                </span>
                <span className="text-border">·</span>
                <span className="text-caution font-medium">
                  {uglyCount} ugly
                </span>
              </div>
            )}
          </div>

          {/* Candidates table (tabs + sortable rows) */}
          <CandidatesTable rows={rows} initialCategory={initialCategory} />
        </div>
      </main>
    </div>
  );
}

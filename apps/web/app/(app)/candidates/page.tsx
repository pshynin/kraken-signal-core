import type { Metadata } from "next";
import { CandidatesTable } from "@/components/candidates/candidates-table";
import { fetchActiveCandidates } from "@/lib/queries/candidates";
import { PageShell, PageHeader } from "@/components/shell/page-shell";
import type { RecommendationCategory } from "@kraken-signal/shared-types";

export const metadata: Metadata = { title: "Candidates" };

function isCategory(v: string | undefined): v is RecommendationCategory {
  return v === "clean" || v === "ugly";
}

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
    <PageShell>
      <PageHeader
        title="Candidates"
        subtitle="Active scanner candidates with entry, target, and stop parameters."
        right={
          rows.length > 0 && (
            <div className="flex items-center gap-3 text-xs tabular-nums">
              <span className="text-bull font-medium">{cleanCount} clean</span>
              <span className="text-border">·</span>
              <span className="text-caution font-medium">{uglyCount} ugly</span>
            </div>
          )
        }
      />

      <CandidatesTable rows={rows} initialCategory={initialCategory} />
    </PageShell>
  );
}

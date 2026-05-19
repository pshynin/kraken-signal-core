import type { Metadata } from "next";
import { fetchScanRuns } from "@/lib/queries/scans";
import { ScanHistoryTable } from "@/components/scans/scan-history-table";
import { PageShell, PageHeader } from "@/components/shell/page-shell";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Scan History" };

export default async function ScansPage() {
  const runs = await fetchScanRuns(50);

  return (
    <PageShell>
      <PageHeader
        title="Scan History"
        subtitle={`${runs.length} most recent scanner runs`}
      />
      <ScanHistoryTable rows={runs} />
    </PageShell>
  );
}

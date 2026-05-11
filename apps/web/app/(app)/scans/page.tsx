import { fetchScanRuns } from "@/lib/queries/scans";
import { ScanHistoryTable } from "@/components/scans/scan-history-table";

export const dynamic = "force-dynamic";

export default async function ScansPage() {
  const runs = await fetchScanRuns(50);

  return (
    <div className="mx-auto max-w-5xl px-8 py-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Scan History</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {runs.length} most recent scanner runs
        </p>
      </div>
      <ScanHistoryTable rows={runs} />
    </div>
  );
}

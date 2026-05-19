import type { Metadata } from "next";
import { fetchAlertHistory } from "@/lib/queries/alerts";
import { AlertHistoryTable } from "@/components/alerts/alert-history-table";
import { PageShell, PageHeader } from "@/components/shell/page-shell";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Alert History" };

export default async function AlertsPage() {
  const alerts = await fetchAlertHistory(100);

  const sentCount = alerts.filter((a) => a.delivery_status === "sent").length;
  const failedCount = alerts.filter(
    (a) => a.delivery_status === "failed"
  ).length;

  const subtitle = (
    <>
      {alerts.length} most recent alerts
      {sentCount > 0 && (
        <span className="ml-2 text-bull">{sentCount} sent</span>
      )}
      {failedCount > 0 && (
        <span className="ml-2 text-bear">{failedCount} failed</span>
      )}
    </>
  );

  return (
    <PageShell>
      <PageHeader title="Alert History" subtitle={subtitle} />
      <AlertHistoryTable rows={alerts} />
    </PageShell>
  );
}

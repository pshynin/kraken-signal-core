import { fetchAlertHistory } from "@/lib/queries/alerts";
import { AlertHistoryTable } from "@/components/alerts/alert-history-table";

export const dynamic = "force-dynamic";

export default async function AlertsPage() {
  const alerts = await fetchAlertHistory(100);

  const sentCount = alerts.filter((a) => a.delivery_status === "sent").length;
  const failedCount = alerts.filter(
    (a) => a.delivery_status === "failed"
  ).length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">
            Alert History
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {alerts.length} most recent alerts
            {sentCount > 0 && (
              <span className="ml-2 text-emerald-400">{sentCount} sent</span>
            )}
            {failedCount > 0 && (
              <span className="ml-2 text-red-400">{failedCount} failed</span>
            )}
          </p>
        </div>
      </div>
      <AlertHistoryTable rows={alerts} />
    </div>
  );
}

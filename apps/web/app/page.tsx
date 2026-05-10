export default function DashboardPage() {
  return (
    <main className="min-h-screen p-8">
      <div className="max-w-7xl mx-auto space-y-8">

        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              Momentum Copilot
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Kraken Spot Scanner — Decision Support System
            </p>
          </div>
        </div>

        {/* Scaffold placeholder */}
        <div className="rounded-lg border border-border bg-card p-12 text-center space-y-3">
          <p className="text-foreground font-medium">Dashboard scaffold</p>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Data layer, candidate tables, and system health arrive in PRs 2–14.
            The scanner pipeline is being built in parallel.
          </p>
          <div className="flex items-center justify-center gap-6 pt-4 text-xs text-muted-foreground font-mono">
            <span>PR 2 → Schema</span>
            <span>→</span>
            <span>PR 4–12 → Scanner</span>
            <span>→</span>
            <span>PR 13–14 → Dashboard</span>
          </div>
        </div>

      </div>
    </main>
  );
}

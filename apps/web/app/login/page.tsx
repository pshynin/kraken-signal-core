"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { MomentumLogo } from "@/components/brand/momentum-logo";

// ── Inner form — isolated in its own component so useSearchParams()
// has a Suspense boundary (required by Next.js App Router).

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passcode }),
      });

      if (res.ok) {
        const from = searchParams.get("from") ?? "/";
        router.push(from);
        router.refresh();
      } else {
        setError("Incorrect passcode. Try again.");
        setPasscode("");
      }
    } catch {
      setError("Connection error. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-2">
        <label
          htmlFor="passcode"
          className="block text-xs font-medium uppercase tracking-wider text-muted-foreground"
        >
          Passcode
        </label>
        <input
          id="passcode"
          type="password"
          autoComplete="current-password"
          autoFocus
          required
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          className={[
            "w-full rounded-md border bg-background px-3.5 py-2.5 text-sm",
            "font-mono text-foreground placeholder:text-muted-foreground/50",
            "transition-colors focus:outline-none focus:border-primary/60",
            "focus:ring-1 focus:ring-primary/40",
            error ? "border-bear/60" : "border-border",
          ].join(" ")}
          placeholder="••••••••"
        />
      </div>

      {error && <p className="text-sm text-bear">{error}</p>}

      <button
        type="submit"
        disabled={loading || !passcode}
        className={[
          "w-full rounded-md bg-primary px-4 py-2.5 text-sm font-semibold",
          "text-primary-foreground transition-all",
          "hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40",
          "shadow-card",
        ].join(" ")}
      >
        {loading ? "Verifying…" : "Access Dashboard"}
      </button>
    </form>
  );
}

// ── Page component ────────────────────────────────────────────────────────────

export default function LoginPage() {
  return (
    <main className="relative min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-8">
        {/* Brand */}
        <div className="text-center space-y-4">
          <div className="flex items-center justify-center gap-2.5">
            <MomentumLogo size={32} className="text-foreground" />
            <span className="text-foreground font-semibold text-xl tracking-tight">
              Momentum Copilot
            </span>
          </div>
          <p className="text-muted-foreground text-sm">
            Enter your passcode to access the dashboard
          </p>
        </div>

        {/* Card */}
        <div className="rounded-xl border border-border/70 bg-card p-6 shadow-elevated">
          <Suspense fallback={<div className="h-[164px]" />}>
            <LoginForm />
          </Suspense>
        </div>

        <p className="text-center text-[11px] uppercase tracking-[0.2em] text-muted-foreground/60 font-mono">
          kraken-signal-core
        </p>
      </div>
    </main>
  );
}

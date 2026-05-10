"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

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
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <label
          htmlFor="passcode"
          className="block text-sm font-medium text-foreground"
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
            "w-full rounded-md border bg-card px-3 py-2 text-sm",
            "font-mono text-foreground placeholder:text-muted-foreground",
            "focus:outline-none focus:ring-1 focus:ring-primary",
            error ? "border-bear" : "border-border",
          ].join(" ")}
          placeholder="••••••••"
        />
      </div>

      {error && <p className="text-sm text-bear">{error}</p>}

      <button
        type="submit"
        disabled={loading || !passcode}
        className={[
          "w-full rounded-md bg-primary px-4 py-2 text-sm font-medium",
          "text-primary-foreground transition-opacity",
          "hover:opacity-90 disabled:opacity-40",
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
    <main className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-8 px-4">
        {/* Logo */}
        <div className="text-center space-y-2">
          <div className="flex items-center justify-center gap-2">
            <span className="text-primary text-2xl select-none">◈</span>
            <span className="text-foreground font-semibold text-xl tracking-tight">
              Momentum Copilot
            </span>
          </div>
          <p className="text-muted-foreground text-sm">
            Enter your passcode to access the dashboard
          </p>
        </div>

        {/* Form — Suspense boundary required for useSearchParams() */}
        <Suspense fallback={<div className="h-[152px]" />}>
          <LoginForm />
        </Suspense>

        <p className="text-center text-xs text-muted-foreground font-mono">
          kraken-signal-core
        </p>
      </div>
    </main>
  );
}

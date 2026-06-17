# CLAUDE.md

Guidance for Claude Code (and any AI assistant) working in this repository.

## What This Is

Decision-support and alerting system for Kraken spot crypto trading. Scans the full Kraken USD-spot universe every 4 hours, ranks candidates for a fixed 10-day trading cycle, and delivers Discord alerts. **Not an auto-trader** — humans place the orders.

## Stack

- **Scanner:** Python 3.11+ (CI uses 3.12); ccxt, pandas-ta, supabase-py, httpx
- **Web:** Next.js 15 (App Router, React 19), TypeScript 5.7, Tailwind, Supabase JS
- **DB:** Supabase Postgres; migrations via Supabase CLI
- **Tooling:** pnpm 9 workspaces, ruff, mypy, pytest, ESLint
- **Runtime:** OCI Always Free VM systemd timer (scheduled scanner), Vercel (web), Docker (scanner packaging). GitHub Actions is CI/CD only — it deploys scanner code to the VM over SSH and never runs the scanner.

## Architecture

A scheduled Python pipeline (`apps/scanner/`) loads the Kraken universe, fetches OHLCV across 4h/1h/30m, computes indicators, applies hard filters, scores with a deterministic 9-factor model, runs the entry engine to compute setup-aware entries, persists results to Supabase, and POSTs Discord alerts. A read-only Next.js dashboard (`apps/web/`) reads the same Supabase tables and renders run history, candidates, alerts, and a thresholds UI. The contract between scanner and web is the Supabase schema plus `packages/shared-types`, which mirrors `apps/scanner/scanner/models.py`. All runtime thresholds live in the `strategy_settings` Supabase table; Python defaults mirror the migration 0012 seed, so the scanner runs safely against an empty table.

## Critical Rules — never break

- **Scoring is deterministic** — same input → same output. No randomness.
- **`--dry-run` skips all side effects** — no DB writes, no Discord POSTs.
- **`passed_metrics` and `passed_indicators` in `FilterResult` are co-indexed** — always iterate together with `zip()`.
- **`stop_loss < entry_price` and `exit_price > entry_price`** — enforced at construction in `selector.py`.
- **`SIZE_BUCKETS` in `models.py` must match the `crecs_size_bucket_check` DB constraint.**
- **Discord webhook URLs are never persisted** — only SHA-256 hashes in `alerts_sent.webhook_url_hash`.
- **`models.py` (Python) and `packages/shared-types/src/scanner.ts` must stay in sync** when fields change.
- **`asset_state_history` is insert-only** — never update or delete rows.

## Folder Structure

```
kraken-signal-core/
├── apps/
│   ├── scanner/              Python scanner service — the core pipeline
│   │   ├── scanner/          Source package; main.py orchestrates 8 stages
│   │   └── tests/            Unit + integration tests
│   └── web/                  Next.js 15 read-only dashboard over Supabase
│       ├── app/              App Router pages (server components by default)
│       ├── lib/
│       │   └── queries/      Supabase query helpers (server-side only)
│       └── components/       UI components (Tailwind + lucide-react)
├── packages/
│   └── shared-types/         TS contracts mirroring scanner models.py
├── supabase/
│   └── migrations/           Versioned Postgres schema; `supabase db push`
├── .github/
│   └── workflows/            CI checks + deploy scanner code to OCI VM (no scheduled scanner)
├── deploy/
│   └── oci/                  OCI VM runtime: systemd timer/service, runner, deploy script, runbook
└── docs/                     Long-form documentation (see index below)
```

## Docs Index

Read the relevant doc before making non-trivial changes in that area. If code, tests, migrations, and docs disagree, treat code/tests/migrations as source of truth and call out the mismatch.

| Doc | Read when… |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Changing how stages connect, adding a stage, or touching the scanner ↔ Supabase ↔ web seam (including `packages/shared-types`) |
| [docs/data-model.md](docs/data-model.md) | Adding/altering a Supabase table, changing `scanner/models.py` or `packages/shared-types`, or touching a DB constraint or `strategy_settings` key |
| [docs/scoring-model.md](docs/scoring-model.md) | Changing scoring factors, weights, category thresholds, or the probability map |
| [docs/entry-engine.md](docs/entry-engine.md) | Changing setup classification (`pullback` / `breakout_trigger` / `reclaim`), entry anchors, or validity gates in `selector.py` / `entry_engine.py` |
| [docs/state-machine.md](docs/state-machine.md) | Touching `state_machine.py`, asset lifecycle states, or `asset_state_history` writes |
| [docs/local-dev.md](docs/local-dev.md) | Setting up the project, running scanner/web/DB/Docker locally, running tests, or debugging env issues |
| [deploy/oci/README.md](deploy/oci/README.md) | Deploying/operating the scheduled scanner on the OCI VM, the systemd timer, the SSH deploy workflow, or VM secrets/logs |
| [docs/roadmap.md](docs/roadmap.md) | Planning new work, checking what's shipped vs pending, or scoping a PR |
| [CHANGELOG.md](CHANGELOG.md) | Recording or reviewing what changed and when |

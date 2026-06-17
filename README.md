# Crypto Momentum Alert Copilot

Decision-support and alerting system for Kraken spot crypto trading. Scans the full Kraken USD-spot universe every 6 hours (on an OCI Always Free VM), ranks candidates for a fixed 10-day trading cycle, and delivers Discord alerts for actionable setups.

> **Not an auto-trader.** Produces ranked candidates with entry / exit / stop / size recommendations for **manual** execution on Kraken spot.

## What It Does

- Loads the tradable Kraken USD-spot universe on a schedule (every 6 hours, via a systemd timer on an OCI Always Free VM).
- Fetches OHLCV across three timeframes (4h / 1h / 30m) and computes technical indicators.
- Applies hard filters and a deterministic 9-factor scoring model, producing ranked **Clean** and **Ugly** candidate tables.
- Computes setup-aware entry, exit, stop, and size recommendations for each candidate.
- Persists everything to Supabase and pushes Discord alerts with dedup and per-run safety caps.
- Surfaces results in a read-only Next.js dashboard for review.

For the trading workflow this is designed around — the fixed 10-day cycle, Day-1 entries through Day-10 force-close, Clean vs Ugly sizing — see [Trading Framework](#trading-framework) at the bottom of this file.

## Architecture

A scheduled Python scanner writes to Supabase Postgres; a read-only Next.js dashboard reads from the same database. Supabase is the only shared state — there is no direct scanner ↔ web link. Discord is fire-and-forget output from the scanner only.

See [docs/architecture.md](docs/architecture.md) for the 8-stage pipeline, the contract between scanner and web, the configuration flow, and scheduling / concurrency details.

## Stack

- **Scanner** — Python 3.11+ (CI uses 3.12); ccxt, pandas-ta, supabase-py, httpx.
- **Web** — Next.js 15 (App Router, React 19), TypeScript 5.7, Tailwind, Supabase JS.
- **DB** — Supabase Postgres; migrations via the Supabase CLI.
- **Tooling** — pnpm 9 workspaces, ruff, mypy, pytest, ESLint.
- **Runtime** — OCI Always Free VM systemd timer (scheduled scanner), Vercel (web), Docker (scanner packaging). GitHub Actions is CI/CD only.

## Quickstart

```bash
git clone https://github.com/yourname/kraken-signal-core.git
cd kraken-signal-core
pnpm install

cp .env.example apps/scanner/.env
cp .env.example apps/web/.env.local

supabase link --project-ref YOUR_PROJECT_REF
supabase db push

cd apps/scanner && pip install -r requirements-dev.txt
python -m scanner.main --dry-run

cd ../web && pnpm dev
```

Fill in `apps/scanner/.env` with your Supabase + Discord credentials, and `apps/web/.env.local` with your Supabase keys plus `DASHBOARD_PASSCODE`. `.env.example` at the repo root is the source of truth for all environment variables. The scanner's `--dry-run` flag skips DB writes and Discord posts. The dashboard runs at <http://localhost:3000>. Full setup, test workflow, Supabase migration workflow, and common issues live in [docs/local-dev.md](docs/local-dev.md).

## Repo Layout

```text
apps/scanner/             Python scanner pipeline (core logic)
apps/web/                 Next.js 15 read-only dashboard
packages/shared-types/    TS contracts mirroring scanner models.py
supabase/migrations/      Versioned Postgres schema
deploy/oci/               OCI VM scanner runtime (systemd timer/service, deploy script, runbook)
.github/workflows/        CI + deploy scanner code to OCI VM (no scheduled scanner)
docs/                     Long-form documentation
```

See [CLAUDE.md](CLAUDE.md) for contributor and AI-assistant guidance.

## Status

The scanner pipeline and dashboard are running end-to-end on a 6-hour cron. For shipped history and what's next:

- [`CHANGELOG.md`](CHANGELOG.md) — what has shipped (curated milestones).
- [`docs/roadmap.md`](docs/roadmap.md) — what's planned and known open issues.

## Documentation

| Doc | What it covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 8-stage pipeline, scanner ↔ Supabase ↔ web seam, scheduling, observability |
| [docs/data-model.md](docs/data-model.md) | Tables, Python/TS mirrors, DB constraints, field-mapping checklist |
| [docs/scoring-model.md](docs/scoring-model.md) | Hard filter, 9 scoring factors, category gates, probability map |
| [docs/entry-engine.md](docs/entry-engine.md) | Setup classification, anchors, validity gates, stop/exit/size logic |
| [docs/state-machine.md](docs/state-machine.md) | Asset lifecycle states, transitions, alert trigger conditions |
| [docs/local-dev.md](docs/local-dev.md) | Prerequisites, setup, test workflow, Supabase workflow, common issues |
| [deploy/oci/README.md](deploy/oci/README.md) | OCI VM scanner runtime: bootstrap, systemd timer, SSH deploy, secrets, logs, rollback |
| [docs/roadmap.md](docs/roadmap.md) | What exists, what's planned, known gaps, out-of-scope |
| [CLAUDE.md](CLAUDE.md) | Guidance for AI assistants working in this repo |

## Trading Framework

Fixed 10-day cycle the scanner's parameters are tuned for:

- **Day 1** — evaluate scanner output and place entry orders.
- **By Day 3** — cancel any unfilled entries and reevaluate.
- **Days 3–7** — manage exits via placed sell orders.
- **Days 8–10** — force-close any remaining open positions.

Two candidate tables: **Clean** (larger, higher-liquidity setups) and **Ugly** (smaller, earlier pre-spike setups).

## License

Private repository. No open-source license granted.

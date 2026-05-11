# Crypto Momentum Alert Copilot

Decision-support and alerting system for Kraken spot crypto trading.  
Scans the full Kraken tradable universe on a schedule, ranks candidates for a fixed 10-day trading cycle, and delivers Discord alerts for actionable setups.

> **Not an auto-trader.** Produces ranked candidates with entry / exit / stop / size recommendations for manual execution on Kraken spot.

---

## Architecture

```
GitHub Actions (cron: every 6 hours)
  └── apps/scanner  (Python)
        ├── Universe loader        — Kraken AssetPairs API → filtered USD spot pairs
        ├── Data fetcher           — OHLCV via ccxt (4H / 1H / 30m)
        ├── Indicator engine       — EMA 20/50/200, VWAP, RSI 14, ATR 14 (pandas-ta)
        ├── Hard filter            — exclusion rules (vertical, illiquid, broken structure)
        ├── Scoring engine         — 9-factor model, 0–100 score, deterministic
        ├── Candidate selector     — ranked Clean + Ugly tables with trade params
        ├── State machine          — tracks asset lifecycle across scans
        ├── Run persister          — bulk upserts to Supabase Postgres
        └── Alert dispatcher       — dedup + Discord webhook POST

Vercel (always-on)
  └── apps/web  (Next.js 15)
        └── Read-only dashboard over Supabase
              ├── /             — Pipeline health + last run summary
              ├── /candidates   — Clean + ugly candidate tables
              ├── /scans        — Scan run history
              ├── /alerts       — Alert delivery log
              └── /settings     — Threshold + webhook configuration
```

---

## Repo Structure

```
kraken-signal-core/
├── apps/
│   ├── scanner/              # Python scanner service
│   │   ├── scanner/          # Source package
│   │   │   ├── main.py           # Entrypoint / orchestrator
│   │   │   ├── config.py         # Env-var config loader
│   │   │   ├── db.py             # Supabase client factory
│   │   │   ├── universe.py       # Kraken universe loader
│   │   │   ├── fetcher.py        # OHLCV via ccxt (4H / 1H / 30m)
│   │   │   ├── indicators.py     # EMA / VWAP / RSI / ATR
│   │   │   ├── filter.py         # Hard-filter exclusion rules
│   │   │   ├── metrics.py        # Market metric calculations
│   │   │   ├── scoring.py        # 9-factor scoring engine
│   │   │   ├── selector.py       # Candidate selector + trade params
│   │   │   ├── state_machine.py  # Asset lifecycle state transitions
│   │   │   ├── persister.py      # Bulk upserts + run finalization
│   │   │   ├── alerter.py        # Discord alert dispatcher
│   │   │   ├── settings.py       # strategy_settings DB loader
│   │   │   └── models.py         # Python dataclasses / contracts
│   │   └── tests/
│   └── web/                  # Next.js 15 dashboard
├── packages/
│   └── shared-types/         # Shared TypeScript contracts
├── supabase/
│   └── migrations/           # Versioned Postgres schema     (PR 2)
└── .github/
    └── workflows/
        ├── ci.yml            # PR checks (lint, type-check, test, build)
        └── scanner.yml       # Scheduled scanner run          (PR 12)
```

---

## Quick Start

### Prerequisites

- Node.js >= 20 and pnpm >= 9
- Python >= 3.11
- [Supabase CLI](https://supabase.com/docs/guides/cli) (for migrations)
- A Supabase project (free tier is fine)
- A Discord server with webhook URLs configured

### 1. Clone and install dependencies

```bash
git clone https://github.com/yourname/kraken-signal-core.git
cd kraken-signal-core
pnpm install
```

### 2. Configure environment

```bash
# Scanner
cp .env.example apps/scanner/.env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DISCORD_WEBHOOK_*

# Dashboard
cp .env.example apps/web/.env.local
# Fill in all variables including NEXT_PUBLIC_* and DASHBOARD_PASSCODE
```

### 3. Apply the database schema

```bash
# Link to your Supabase project:
supabase link --project-ref YOUR_PROJECT_REF

# Push all migrations:
supabase db push
```

### 4. Run the scanner locally

```bash
cd apps/scanner
pip install -r requirements-dev.txt
python -m scanner.main
# Add --dry-run to skip DB writes and Discord POSTs
python -m scanner.main --dry-run
```

### 5. Run the dashboard locally

```bash
cd apps/web
pnpm dev
# Open http://localhost:3000
# Enter DASHBOARD_PASSCODE when prompted
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list with descriptions.

### GitHub Actions Repository Secrets

Set in: **GitHub → Settings → Secrets and variables → Actions → Repository secrets**

| Secret | Required | Description |
|---|---|---|
| `SUPABASE_URL` | ✅ | Supabase project URL (`https://xxx.supabase.co`) |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Service role key — full DB access, bypasses RLS |
| `DISCORD_WEBHOOK_CLEAN` | ✅ | Webhook URL for `#clean-candidates` channel |
| `DISCORD_WEBHOOK_UGLY` | ✅ | Webhook URL for `#ugly-candidates` channel |
| `DISCORD_WEBHOOK_SYSTEM` | ⚠️ optional | Webhook URL for `#system-alerts` channel |

### Vercel Environment Variables

Set in: **Vercel → Project → Settings → Environment Variables**

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Same value as `SUPABASE_URL` — exposed to browser |
| `SUPABASE_URL` | Supabase project URL — server-side |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon/publishable key — safe for browser |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret key — server components only, never browser |
| `DASHBOARD_PASSCODE` | Passcode for the `/login` gate — choose any string |

### Local Development

**`apps/scanner/.env`** — scanner only:
```bash
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
DISCORD_WEBHOOK_CLEAN=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_UGLY=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_SYSTEM=https://discord.com/api/webhooks/...
```

**`apps/web/.env.local`** — dashboard only:
```bash
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
DASHBOARD_PASSCODE=your-passcode
```

Both files are git-ignored and will never be committed.

---

## Scanner Run Schedule

Configured in `.github/workflows/scanner.yml` as a cron expression.  
Default: `0 */6 * * *` (every 6 hours at 00:00, 06:00, 12:00, 18:00 UTC).  
Manual trigger: GitHub Actions → scanner workflow → "Run workflow".

---

## Trading Framework

**10-day fixed cycle:**

| Day | Action |
|---|---|
| Day 1 | Analyze scanner output, define entry/stop/target, place buy orders |
| By Day 3 | Cancel all unfilled entries and reevaluate |
| Days 3–7 | Expect exits via placed sell orders; only lower targets if structure holds |
| Days 8–10 | Force-close all remaining open positions |

**Output tables:**

1. **Clean Candidates** — higher-liquidity swing setups, $5k–$20k+ sizing
2. **Ugly Pre-Spike** — early thin/small-cap setups, $2k–$5k sizing

**No bag holding beyond Day 10. No converting failed trades into investments.**

---

## Implementation Status

| PR | Scope | Status |
|---|---|---|
| PR 1 | Repo scaffold | ✅ Done |
| PR 2 | Database schema + migrations | ✅ Done |
| PR 3 | Shared types / contracts | ✅ Done |
| PR 4 | Kraken universe loader | ✅ Done |
| PR 5 | Market data ingestion pipeline | ✅ Done |
| PR 6 | Indicator engine | ✅ Done |
| PR 7 | Hard filter + metric calculator | ✅ Done |
| PR 8 | Scoring engine | ✅ Done |
| PR 9 | Candidate selector + trade params | ✅ Done |
| PR 10 | State machine + run persister | ✅ Done |
| PR 11 | Alert formatter + Discord dispatcher | ✅ Done |
| PR 12 | Scheduled scan runner + GH Actions | ✅ Done |
| PR 13 | Next.js dashboard scaffold + auth | ✅ Done |
| PR 14 | Candidate tables UI | ✅ Done |
| PR 15 | Scan history + alert history pages | ✅ Done |
| PR 16 | Settings / config UI | ✅ Done |
| PR 17 | Docker + on-prem portability | 🔜 Pending |
| PR 18 | End-to-end smoke tests + observability | ✅ Done |
| PR 19 | Global app shell — shared sidebar layout | ✅ Done |
| PR 21 | Scan run finalization + `timed_out` status | ✅ Done |

---

## License

Private — personal use. Not for redistribution.

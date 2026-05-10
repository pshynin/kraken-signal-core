# Crypto Momentum Alert Copilot

Decision-support and alerting system for Kraken spot crypto trading.  
Scans the full Kraken tradable universe on a schedule, ranks candidates for a fixed 10-day trading cycle, and delivers Discord alerts for actionable setups.

> **Not an auto-trader.** Produces ranked candidates with entry / exit / stop / size recommendations for manual execution on Kraken spot.

---

## Architecture

```
GitHub Actions (cron: every 4 hours)
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
              ├── /             — Current candidate tables + system health
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
│   │   │   ├── main.py       # Entrypoint / orchestrator
│   │   │   ├── universe.py   # Kraken universe loader        (PR 4)
│   │   │   ├── data_fetcher.py                               (PR 5)
│   │   │   ├── indicators.py                                 (PR 6)
│   │   │   ├── hard_filter.py                                (PR 7)
│   │   │   ├── metrics.py                                    (PR 7)
│   │   │   ├── scorer.py                                     (PR 8)
│   │   │   ├── selector.py                                   (PR 9)
│   │   │   ├── trade_params.py                               (PR 9)
│   │   │   ├── state_machine.py                              (PR 10)
│   │   │   ├── persister.py                                  (PR 10)
│   │   │   ├── alerter.py                                    (PR 11)
│   │   │   ├── settings.py   # Load strategy_settings from DB
│   │   │   └── models.py     # Python dataclasses / contracts
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
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DISCORD_WEBHOOK_*, DASHBOARD_PASSCODE
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

| Variable | Used By | Notes |
|---|---|---|
| `SUPABASE_URL` | Scanner + Web (server) | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Scanner + Web (server) | **Never expose to browser** |
| `NEXT_PUBLIC_SUPABASE_URL` | Web (client) | Same value as `SUPABASE_URL` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Web (client) | Anon/public key |
| `DISCORD_WEBHOOK_CLEAN` | Scanner only | `#kraken-clean` channel |
| `DISCORD_WEBHOOK_UGLY` | Scanner only | `#kraken-ugly` channel |
| `DISCORD_WEBHOOK_SYSTEM` | Scanner only | `#kraken-system` errors/health |
| `DASHBOARD_PASSCODE` | Web middleware | Protects dashboard route |
| `SCANNER_ENV` | Scanner | `development` or `production` |

---

## Scanner Run Schedule

Configured in `.github/workflows/scanner.yml` as a cron expression.  
Default: `0 */4 * * *` (every 4 hours, 24/7).  
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
| PR 2 | Database schema + migrations | 🔜 |
| PR 3 | Shared types / contracts | 🔜 |
| PR 4 | Kraken universe loader | 🔜 |
| PR 5 | Market data ingestion pipeline | 🔜 |
| PR 6 | Indicator engine | 🔜 |
| PR 7 | Hard filter + metric calculator | 🔜 |
| PR 8 | Scoring engine | 🔜 |
| PR 9 | Candidate selector + trade params | 🔜 |
| PR 10 | State machine + run persister | 🔜 |
| PR 11 | Alert formatter + Discord dispatcher | 🔜 |
| PR 12 | Scheduled scan runner + GH Actions | 🔜 |
| PR 13 | Next.js dashboard scaffold + auth | 🔜 |
| PR 14 | Candidate tables UI | 🔜 |
| PR 15 | Scan history + alert history pages | 🔜 |
| PR 16 | Settings / config UI | 🔜 |
| PR 17 | Docker + on-prem portability | 🔜 |
| PR 18 | End-to-end smoke tests + observability | 🔜 |

---

## License

Private — personal use. Not for redistribution.

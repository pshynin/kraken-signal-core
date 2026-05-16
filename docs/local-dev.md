# Local Development

How to get the scanner, dashboard, and database running on your machine — and how to debug when they don't.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | ≥ 3.11, < 3.14 (CI uses 3.12) | Scanner runtime (see `apps/scanner/pyproject.toml`) |
| Node.js | ≥ 20 | Web dashboard + tooling |
| pnpm | ≥ 9 | Monorepo package manager (`package.json` pins `pnpm@9.12.3`) |
| Supabase CLI | latest | Apply migrations, run local stack |
| Docker | optional | For the scanner Docker workflow |

You also need:

- A Supabase project (free tier is fine) — or run Supabase locally via `supabase start`.
- A Discord server with webhook URLs for `#clean-candidates` and `#ugly-candidates` (and optionally `#system-alerts`).

## First-Time Setup

```bash
git clone https://github.com/yourname/kraken-signal-core.git
cd kraken-signal-core
pnpm install
```

Then create the two env files (both are git-ignored):

```bash
cp .env.example apps/scanner/.env
cp .env.example apps/web/.env.local
```

Fill in `apps/scanner/.env` with `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and the `DISCORD_WEBHOOK_*` values. Fill in `apps/web/.env.local` with `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `DASHBOARD_PASSCODE`.

Apply the schema:

```bash
supabase link --project-ref YOUR_PROJECT_REF
supabase db push
```

## Scanner Workflow

From `apps/scanner/`:

```bash
pip install -r requirements-dev.txt
python -m scanner.main
python -m scanner.main --dry-run
python -m scanner.validation report
python -m scanner.validation report --since 2026-05-01
```

`pip install -r requirements-dev.txt` is one-time — it installs runtime deps plus ruff, mypy, and pytest. `python -m scanner.main` runs a full scan (writes to DB, posts to Discord). `--dry-run` exercises stages 1–6 fully (universe → fetcher → indicators → filter → scoring → selector) and skips persister + alerter. Useful for tuning thresholds without polluting the DB.

`python -m scanner.validation report` is **read-only**: it replays persisted recommendations against forward prices and prints fill / stop / target / MAE-MFE stats, split into `EXACT` and `CLOSE_APPROX` fidelity sections. It needs DB credentials (same `.env` as the scanner) but never writes. `--since YYYY-MM-DD` limits to scan runs on/after that UTC date. Until `ohlcv_candles` has ≥10 days of accrued forward data, expect only the `CLOSE_APPROX` (6h-close approximation) section.

## Linting, type-checking, tests

```bash
ruff check scanner/ tests/
ruff format --check scanner/ tests/
mypy scanner/
pytest tests/
pytest -m "not integration" tests/
pytest tests/unit/test_scoring.py
pytest --cov=scanner --cov-report=term-missing tests/
```

The `integration` marker is defined in `pyproject.toml` — tests so marked require live Supabase + Kraken access and are excluded with `-m "not integration"`. Default pytest options (`--tb=short -q`) are also configured in `pyproject.toml`.

## Docker (optional)

From `apps/scanner/`:

```bash
make build
make run
make dry-run
make logs
```

`make build` builds the `kraken-scanner:local` image. `make run` runs one scan reading `.env`. `make dry-run` runs `--dry-run` (no DB writes, no Discord). `make logs` tails logs from the last container. Equivalent to GitHub Actions' run shape — useful for verifying portability.

## Dashboard Workflow

From repo root or `apps/web/`:

```bash
pnpm dev
cd apps/web && pnpm dev
```

The root-level `pnpm dev` filters to `@kraken-signal/web`; the in-directory form is equivalent. Open <http://localhost:3000>. If `DASHBOARD_PASSCODE` is set in `.env.local`, you'll be redirected to `/login`. If it's not set, the middleware enables open-access dev mode (no login required).

Other commands:

```bash
pnpm --filter @kraken-signal/web lint
pnpm type-check
pnpm build
```

`pnpm type-check` runs `tsc --noEmit` across all workspaces. `pnpm build` produces a production build of the web app.

## Supabase Workflow

```bash
supabase db push
supabase db reset
supabase start
```

`supabase db push` applies all pending migrations. `supabase db reset` tears down and reapplies from scratch — useful after editing a migration. `supabase start` runs a local Supabase stack instead of cloud; afterwards, point `.env` at the local URL and service-role key from `supabase status`.

Adding a migration:

1. Create a new file in `supabase/migrations/` named `YYYYMMDDHHMMSS_<description>.sql`. Use a timestamp newer than the latest existing migration.
2. Test it locally with `supabase db reset` to confirm the full migration chain applies cleanly.
3. Mirror schema changes in `apps/scanner/scanner/models.py` and `packages/shared-types/src/database.ts` in the same PR — see [data-model.md](data-model.md).

## Common Issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `Configuration error: SUPABASE_URL not set` | `.env` missing or not loaded | Confirm `apps/scanner/.env` exists and you're running from `apps/scanner/` |
| Scanner runs but nothing is written | `SCANNER_ENV=test` or `--dry-run` is set | Remove `--dry-run`; check `SCANNER_ENV` is not `test` |
| `Failed to load strategy_settings — using defaults` | Supabase unreachable, or migrations not applied | Run `supabase db push`; verify service-role key |
| Discord alerts skipped with "webhooks not configured" | `DISCORD_WEBHOOK_CLEAN` / `DISCORD_WEBHOOK_UGLY` missing | Set both env vars in `apps/scanner/.env` |
| Dashboard shows "No scan runs yet" | DB is empty / scanner hasn't run | Run `python -m scanner.main` once, or seed manually |
| `/login` loop or 401 on every page | Cookie/passcode mismatch | Clear `mc_auth` cookie; confirm `DASHBOARD_PASSCODE` matches between env and what you're entering |
| `ModuleNotFoundError: scanner` | Running from wrong directory | Run from `apps/scanner/` so `scanner/` is on `sys.path` |
| `mypy` errors after editing `models.py` | Forgot to mirror in `packages/shared-types` | Update `src/scanner.ts` and `src/database.ts`; see [data-model.md](data-model.md) |
| Tests fail with Kraken/network errors | Integration tests are running | Use `pytest -m "not integration"` |

## Environment Reference

Single source of truth: `/.env.example` at the repo root. Full list and per-service expectations live there. See also the README's "Environment Variables" section for the GitHub Actions + Vercel split.

# Asset State Machine

How `apps/scanner/scanner/state_machine.py` records the lifecycle of every asset processed by the scanner. The module writes an **immutable audit trail** to `asset_state_history` — it does not enforce transition validity, and it does not gate alerts. Think of it as a journal, not a controller.

## What It Is and Isn't

- **It is:** an append-only log of "this asset moved to state X at time T because of reason R during scan run S".
- **It isn't:** a guarded FSM. Any `from_state → to_state` pair the scanner emits is accepted.
- **It isn't:** the source of truth for current state — the latest `candidate_recommendations` row is. The history table is for diagnostics, trend analysis, and the dashboard's `/alerts` and `/scans` views.

## States

Seven values are written by the scanner today. The DB column `asset_state_history.to_state` is `TEXT` (no CHECK constraint), so additional values can be introduced without a migration — but you should still document them here.

| State | Written when | Source |
|---|---|---|
| `candidate_clean` | Asset is in the top-N clean candidates this run | `record_initial_transitions()` |
| `candidate_ugly` | Asset is in the top-N ugly candidates this run | `record_initial_transitions()` |
| `watchlist` | Asset scored at or above `watchlist_min_score` but did not make either top-N table | `record_initial_transitions()` |
| `low_score` | Asset scored below `watchlist_min_score` — distinct from `excluded` | `record_initial_transitions()` |
| `entry_rejected` | Asset would have entered `candidate_clean`/`candidate_ugly` but the entry engine produced no valid trade plan | `record_initial_transitions()` |
| `excluded` | Asset failed the hard filter | `record_initial_transitions()` |
| `alerted` | Discord delivery succeeded for a `candidate_*` row | `record_alerted_transition()` |

## Transitions

Two write paths, two call sites.

### Initial transitions — `record_initial_transitions()`

Called once per run by `persister.persist_run()`. For every asset processed this run:

1. Fetches the most-recent prior `to_state` per asset (batched `in_` query, dedup'd in Python — see `_resolve_previous_states`).
2. Builds insert rows for:
   - Every candidate in `SelectionResult.clean` and `.ugly` → `candidate_clean` / `candidate_ugly`
   - Every hard-filtered asset in `FilterResult.exclusions` → `excluded`
   - Every scored-but-unselected asset in `ScoringResult.watchlist` → `watchlist`
   - Every below-floor score in `ScoringResult.low_score` → `low_score`
   - Every entry-engine rejection in `SelectionResult.rejected` → `entry_rejected`
3. Bulk-inserts in chunks of `_BATCH_SIZE = 200`.

`from_state` is the prior `to_state`, or `NULL` for first-ever entries. Reason strings:

| Reason | When |
|---|---|
| `new_candidate` | `to_state` is `candidate_*` and the prior state was different |
| `retained_candidate` | `to_state` is `candidate_*` and the prior state was the same `candidate_*` |
| `watchlist_entry` | `to_state` is `watchlist` |
| `low_score_entry` | `to_state` is `low_score` |
| _entry-rejection reason_ | `to_state` is `entry_rejected` — one of the constants in `scanner.rejection_reasons` |
| _hard-filter reason key_ | `to_state` is `excluded` — copied from `HardFilterResult.exclusion_reason` (see [scoring-model.md](scoring-model.md#hard-filter)) |

`metadata` (JSONB) snapshot per row:
- Candidates: `score_total`, `rank`, `probability_pct`, `price_usd`.
- Watchlist: `score_total`, `probability_pct`.
- Low_score: `score_total`, `probability_pct` (same shape as watchlist, distinct state).
- Entry_rejected: `category`, `rank`, `setup_type`, `score_total`, `probability_pct`, `current_price`.
- Excluded: `NULL`.

### Entry-rejection reasons

The full set of reason constants for `to_state='entry_rejected'` lives in `apps/scanner/scanner/rejection_reasons.py` (single source of truth). Today's set covers: over-chased breakouts, pullback/reclaim max-entry above current price, missing 20-day-high data, no qualifying reclaim anchor, and a catch-all unknown reason. New reasons must be added to that module and exported via `ENTRY_REJECTION_REASONS`.

### Alerted transitions — `record_alerted_transition()`

Called by `alerter.run_alerter()` **after** a successful Discord webhook POST, once per delivered alert.

- `from_state` is `candidate_clean` or `candidate_ugly` (passed in by the caller — whichever category the alert belongs to).
- `to_state` is `alerted`.
- `reason` is the literal string `"alerted"`.
- `metadata` is optional context (symbol, rank, score_total, etc.) supplied by the caller.

Single-row insert, not batched.

## Alert Trigger Conditions

Alert decisions live in `alerter.py`, not `state_machine.py`. The state machine simply records the outcome. Conditions that must be true before `record_alerted_transition()` runs:

1. **Discord webhooks configured.** `DISCORD_WEBHOOK_CLEAN` and `DISCORD_WEBHOOK_UGLY` are set in the environment; otherwise `load_alert_config()` returns `None` and Stage 8 is skipped.
2. **Candidate persisted.** Stage 7 succeeded — there is a row in `candidate_recommendations` and a row in `asset_state_history` with `to_state` in `{candidate_clean, candidate_ugly}` for the current run.
3. **Not within dedup window.** No row exists in `alerts_sent` with `asset_id = X` and `delivery_status = 'sent'` and `created_at >= now() - dedup_window_hours`.
   - `dedup_window_hours` is sourced from `strategy_settings.scanner.alert_dedup_hours` (default **8h**).
4. **Per-run safety cap not exceeded.** `AlertConfig.max_clean_alerts` / `max_ugly_alerts` default to 5 each.
5. **POST returns 2xx.** Network errors or non-2xx responses are logged to `alerts_sent` with `delivery_status != 'sent'` and **do not** produce a state-history row.

## Querying Asset History

Indexes on the table support common dashboard queries:

```sql
-- All transitions for one asset, newest first
SELECT * FROM asset_state_history
WHERE asset_id = $1
ORDER BY created_at DESC;

-- Everything from one scan run
SELECT * FROM asset_state_history
WHERE scan_run_id = $1;

-- Recently alerted assets
SELECT * FROM asset_state_history
WHERE to_state = 'alerted'
ORDER BY created_at DESC
LIMIT 50;
```

Indexes:

- `idx_state_hist_asset (asset_id, created_at DESC)`
- `idx_state_hist_run (scan_run_id)`
- `idx_state_hist_to_state (to_state)`

### Where to view this in the dashboard

- **Per-run breakdown** — `/scans/[id]` shows hard-filter exclusion counts (by reason), entry-engine rejections (per symbol with setup + reason), and below-threshold totals (watchlist + low_score). All derived from `asset_state_history` rows for that `scan_run_id`.
- **Per-asset timeline** — `/assets/[symbol]` shows the full transition history for one asset, newest first, capped at 100 rows. Symbol cells in the candidates / scan-detail / alerts tables link here.

## Foreign-Key Behaviour

- `asset_id` → `assets.id ON DELETE RESTRICT` — you cannot delete an asset that has history. Keeps the audit trail intact.
- `scan_run_id` → `scan_runs.id ON DELETE SET NULL` — pruning old runs is safe; the history row survives with `scan_run_id = NULL`.

## When to Change This

- **New state value** — pick a clear, lowercase-with-underscores string. Add it to the state table above, plus any dashboard filter UI. Consider whether existing code that pattern-matches on `candidate_*` needs updating.
- **New reason** — add it to the reasons table. If the new reason originates outside `state_machine.py`, document where it's set (for example `HardFilterResult.exclusion_reason`).
- **Guarded transitions** — if you ever need to reject invalid `from_state → to_state` pairs, do it in `state_machine.py` (not as a DB constraint) so the scanner can degrade gracefully. Add tests in `tests/unit/test_state_machine.py`.
- **Never delete or update rows** — the table is insert-only by design.

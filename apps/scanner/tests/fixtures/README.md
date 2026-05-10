# Test Fixtures

Static JSON fixtures used by unit and integration tests.  
These represent real Kraken API responses and computed data, captured once and committed.

## Files (added across PRs 4–9)

| File | Added in | Description |
|---|---|---|
| `kraken_asset_pairs.json` | PR 4 | Kraken `AssetPairs` API response snapshot |
| `ohlcv_sol_4h.json` | PR 5 | SOL/USD 4H OHLCV (180 candles) |
| `ohlcv_sol_1h.json` | PR 5 | SOL/USD 1H OHLCV (720 candles) |
| `ohlcv_sol_30m.json` | PR 5 | SOL/USD 30m OHLCV (96 candles) |
| `ohlcv_btc_4h.json` | PR 5 | BTC/USD 4H OHLCV (baseline for relative strength) |

## Naming Convention

`{symbol}_{timeframe}.json` — all symbols lowercase, USD pairs only.

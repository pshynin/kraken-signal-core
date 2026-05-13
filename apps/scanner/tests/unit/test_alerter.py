"""Unit tests for scanner.alerter — Discord formatting, dedup, dispatch.

All tests are fully offline:
    - Supabase client replaced with MagicMock.
    - httpx.post (via _post_to_webhook) patched with unittest.mock.patch.
    - No Discord webhooks are actually called.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scanner.alerter import (
    _COLOR_CLEAN,
    _COLOR_UGLY,
    _DISCORD_MAX_CHARS,
    AlertConfig,
    _is_already_alerted,
    _post_to_webhook,
    format_candidate_embed,
    format_table_messages,
    load_alert_config,
    run_alerter,
)
from scanner.models import (
    AssetIndicators,
    IndicatorSnapshot,
    MarketMetrics,
    ScoreBreakdown,
    ScoredCandidate,
    SelectionResult,
    TradeParameters,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_CFG = AlertConfig(
    webhook_clean="https://discord.com/api/webhooks/clean/token",
    webhook_ugly="https://discord.com/api/webhooks/ugly/token",
)


def _snap(symbol: str = "BTC") -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=symbol,
        timeframe="4h",
        snapshot_time="",
        ema_20=None,
        ema_50=None,
        ema_200=None,
        price_vs_ema20_pct=3.0,
        price_vs_ema50_pct=None,
        price_vs_ema200_pct=None,
        vwap=None,
        price_vs_vwap_pct=None,
        rsi_14=60.0,
        atr_14=None,
        atr_14_pct=8.0,
        volume_ma_20=1000.0,
        volume_current=1200.0,
        trend_state="up",
        ema_alignment="bullish",
        vwap_state="above",
    )


def _indicator(symbol: str = "BTC") -> AssetIndicators:
    s = _snap(symbol)
    return AssetIndicators(symbol=symbol, kraken_pair=f"{symbol}USD", tf_4h=s, tf_1h=s, tf_30m=s)


def _metrics(symbol: str = "BTC") -> MarketMetrics:
    return MarketMetrics(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        snapshot_time="",
        price_usd=50_000.0,
        price_btc=None,
        volume_24h_usd=5_000_000.0,
        volume_7d_avg_usd=8_000_000.0,
        volume_ratio_20d=1.4,
        return_3d=0.06,
        return_7d=0.12,
        return_14d=0.18,
        return_vs_btc_7d=0.05,
        dist_from_7d_high=-0.10,
        dist_from_20d_high=-0.15,
        spread_pct=0.008,
        atr_pct_7d=8.0,
    )


def _score(symbol: str = "BTC", category: str = "clean") -> ScoreBreakdown:
    return ScoreBreakdown(
        symbol=symbol,
        category=category,
        exclusion_reason=None,
        score_total=76.0,
        score_liquidity=14.0,
        score_upside=12.0,
        score_volatility=10.0,
        score_structure=13.0,
        score_rel_strength=8.0,
        score_volume=8.0,
        score_catalyst=8.0,
        score_supply_risk=4.0,
        score_execution=4.0,
        probability_pct=77.0,
    )


def _trade(symbol: str = "BTC") -> TradeParameters:
    return TradeParameters(
        symbol=symbol,
        entry_price=50_000.0,
        entry_price_low=49_750.0,
        entry_price_high=50_250.0,
        exit_price=56_000.0,
        stop_loss=47_000.0,
        suggested_size_bucket="5k-10k",
        expected_gain_pct=12.0,
        reward_risk_ratio=2.0,
        notes="trend:up | rsi:60",
        current_price=51_000.0,
        distance_to_entry_pct=-1.96,
        setup_type="pullback",
        preferred_entry=50_000.0,
        max_entry=50_500.0,
        support_anchor_type="ema_20",
        support_anchor_value=49_875.0,
    )


def _candidate(symbol: str = "BTC", category: str = "clean", rank: int = 1) -> ScoredCandidate:
    return ScoredCandidate(
        symbol=symbol,
        kraken_pair=f"{symbol}USD",
        category=category,
        rank=rank,
        score=_score(symbol, category),
        trade=_trade(symbol),
        market=_metrics(symbol),
        indicators=_indicator(symbol),
    )


def _client(dedup_data: list[dict] | None = None) -> MagicMock:
    """Build a MagicMock client covering all alerter DB call chains."""
    client = MagicMock()
    table = client.table.return_value

    # Dedup SELECT chain: .select().eq().eq().eq().gte().execute()
    dedup_resp = MagicMock()
    dedup_resp.data = dedup_data or []
    (
        table.select.return_value.eq.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value
    ) = dedup_resp

    # INSERT (alerts_sent + asset_state_history)
    insert_resp = MagicMock()
    insert_resp.data = [{"id": "alert-uuid"}]
    table.insert.return_value.execute.return_value = insert_resp

    # UPDATE (candidate_recommendations.state)
    update_resp = MagicMock()
    update_resp.data = []
    table.update.return_value.eq.return_value.eq.return_value.execute.return_value = update_resp

    return client


# ── format_candidate_embed ────────────────────────────────────────────────────


def test_format_embed_clean_emoji_in_title() -> None:
    embed = format_candidate_embed(_candidate("BTC", "clean"))
    assert "🟢" in embed["title"]
    assert "BTC" in embed["title"]


def test_format_embed_ugly_emoji_in_title() -> None:
    embed = format_candidate_embed(_candidate("ETH", "ugly"))
    assert "🟡" in embed["title"]
    assert "ETH" in embed["title"]


def test_format_embed_rank_in_title() -> None:
    embed = format_candidate_embed(_candidate("SOL", "clean", rank=3))
    assert "#3" in embed["title"]


def test_format_embed_clean_color() -> None:
    embed = format_candidate_embed(_candidate("BTC", "clean"))
    assert embed["color"] == _COLOR_CLEAN


def test_format_embed_ugly_color() -> None:
    embed = format_candidate_embed(_candidate("ETH", "ugly"))
    assert embed["color"] == _COLOR_UGLY


def test_format_embed_required_fields_present() -> None:
    embed = format_candidate_embed(_candidate())
    field_names = {f["name"] for f in embed["fields"]}
    for expected in ("Entry Zone", "Exit Target", "Stop Loss", "R:R Ratio", "Size Bucket", "Score"):
        assert expected in field_names, f"missing field: {expected}"


def test_format_embed_entry_zone_uses_low_high() -> None:
    embed = format_candidate_embed(_candidate())
    entry_field = next(f for f in embed["fields"] if f["name"] == "Entry Zone")
    assert "49,750" in entry_field["value"]
    assert "50,250" in entry_field["value"]


def test_format_embed_notes_in_description() -> None:
    embed = format_candidate_embed(_candidate())
    assert "trend:up" in embed["description"]


# ── _is_already_alerted ───────────────────────────────────────────────────────


def test_is_already_alerted_returns_true_when_data() -> None:
    client = _client(dedup_data=[{"id": "existing-alert"}])
    assert _is_already_alerted(client, "uuid-btc", "2026-01-01T00:00:00Z") is True


def test_is_already_alerted_returns_false_when_empty() -> None:
    client = _client(dedup_data=[])
    assert _is_already_alerted(client, "uuid-btc", "2026-01-01T00:00:00Z") is False


# ── _post_to_webhook ──────────────────────────────────────────────────────────


def test_post_to_webhook_raises_on_http_error() -> None:
    with patch("httpx.post") as mock_post:
        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        mock_post.return_value = mock_resp
        with pytest.raises(httpx.HTTPStatusError):
            _post_to_webhook("https://example.com/webhook", {"embeds": []})


# ── run_alerter ───────────────────────────────────────────────────────────────


def test_run_alerter_posts_to_clean_webhook() -> None:
    client = _client()
    sel = SelectionResult(clean=[_candidate("BTC", "clean")])
    with patch("scanner.alerter._post_to_webhook") as mock_post:
        run_alerter(client, "run-id", {"BTC": "uuid-btc"}, sel, _CFG)
    mock_post.assert_called_once()
    called_url = mock_post.call_args[0][0]
    assert "clean" in called_url


def test_run_alerter_posts_to_ugly_webhook() -> None:
    client = _client()
    sel = SelectionResult(ugly=[_candidate("ETH", "ugly")])
    with patch("scanner.alerter._post_to_webhook") as mock_post:
        run_alerter(client, "run-id", {"ETH": "uuid-eth"}, sel, _CFG)
    mock_post.assert_called_once()
    called_url = mock_post.call_args[0][0]
    assert "ugly" in called_url


def test_run_alerter_skips_deduped_asset() -> None:
    client = _client(dedup_data=[{"id": "prior-alert"}])
    sel = SelectionResult(clean=[_candidate("BTC", "clean")])
    with patch("scanner.alerter._post_to_webhook") as mock_post:
        count = run_alerter(client, "run-id", {"BTC": "uuid-btc"}, sel, _CFG)
    mock_post.assert_not_called()
    assert count == 0


def test_run_alerter_records_alerts_sent_on_success() -> None:
    client = _client()
    sel = SelectionResult(clean=[_candidate("BTC", "clean")])
    with patch("scanner.alerter._post_to_webhook"):
        run_alerter(client, "run-id", {"BTC": "uuid-btc"}, sel, _CFG)
    # alerts_sent INSERT should have been called
    table_calls = [c.args[0] for c in client.table.call_args_list]
    assert "alerts_sent" in table_calls


def test_run_alerter_records_failed_status_on_webhook_error() -> None:
    client = _client()
    sel = SelectionResult(clean=[_candidate("BTC", "clean")])
    with patch("scanner.alerter._post_to_webhook", side_effect=Exception("timeout")):
        count = run_alerter(client, "run-id", {"BTC": "uuid-btc"}, sel, _CFG)
    assert count == 0
    # alerts_sent should still be inserted with delivery_status='failed'
    insert_call = client.table.return_value.insert.call_args[0][0]
    assert insert_call["delivery_status"] == "failed"
    assert insert_call["error_message"] == "timeout"


def test_run_alerter_respects_max_clean_alerts() -> None:
    client = _client()
    candidates = [_candidate(f"C{i}", "clean", i + 1) for i in range(6)]
    sel = SelectionResult(clean=candidates)
    asset_id_map = {f"C{i}": f"uuid-c{i}" for i in range(6)}
    cfg = AlertConfig(
        webhook_clean=_CFG.webhook_clean,
        webhook_ugly=_CFG.webhook_ugly,
        max_clean_alerts=3,
    )
    with patch("scanner.alerter._post_to_webhook") as mock_post:
        count = run_alerter(client, "run-id", asset_id_map, sel, cfg)
    assert mock_post.call_count == 1
    assert count == 3


def test_run_alerter_returns_total_sent_count() -> None:
    client = _client()
    sel = SelectionResult(
        clean=[_candidate("BTC", "clean")],
        ugly=[_candidate("ETH", "ugly")],
    )
    asset_id_map = {"BTC": "uuid-btc", "ETH": "uuid-eth"}
    with patch("scanner.alerter._post_to_webhook"):
        count = run_alerter(client, "run-id", asset_id_map, sel, _CFG)
    assert count == 2


# ── format_table_messages ───────────────────────────────────────────────────────


def test_format_table_messages_contains_all_symbols() -> None:
    candidates = [_candidate("BTC", "clean", 1), _candidate("ETH", "clean", 2)]
    now = "2026-05-11T10:00:00Z"
    msgs = format_table_messages(candidates, "clean", now)
    assert len(msgs) >= 1
    combined = "".join(msgs)
    assert "BTC" in combined
    assert "ETH" in combined


def test_format_table_messages_under_discord_limit() -> None:
    candidates = [_candidate(f"C{i}", "clean", i + 1) for i in range(10)]
    now = "2026-05-11T10:00:00Z"
    msgs = format_table_messages(candidates, "clean", now)
    for msg in msgs:
        assert len(msg) <= _DISCORD_MAX_CHARS


def test_format_table_messages_ugly_label() -> None:
    candidates = [_candidate("ETH", "ugly", 1)]
    msgs = format_table_messages(candidates, "ugly", "2026-05-11T10:00:00Z")
    assert "🟡" in msgs[0]
    assert "Ugly" in msgs[0]


def test_format_table_messages_clean_label() -> None:
    candidates = [_candidate("BTC", "clean", 1)]
    msgs = format_table_messages(candidates, "clean", "2026-05-11T10:00:00Z")
    assert "🟢" in msgs[0]
    assert "Clean" in msgs[0]


def test_format_table_messages_splits_at_limit() -> None:
    import scanner.alerter as alerter_mod

    original = alerter_mod._DISCORD_MAX_CHARS
    try:
        alerter_mod._DISCORD_MAX_CHARS = 300
        candidates = [_candidate(f"T{i}", "clean", i + 1) for i in range(5)]
        msgs = format_table_messages(candidates, "clean", "2026-05-11T10:00:00Z")
        assert len(msgs) > 1
    finally:
        alerter_mod._DISCORD_MAX_CHARS = original


# ── load_alert_config ────────────────────────────────────────────────────────────


def test_load_alert_config_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_CLEAN", raising=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_UGLY", raising=False)
    assert load_alert_config() is None


def test_load_alert_config_returns_config_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_CLEAN", "https://clean.url")
    monkeypatch.setenv("DISCORD_WEBHOOK_UGLY", "https://ugly.url")
    monkeypatch.delenv("DISCORD_WEBHOOK_SYSTEM", raising=False)
    cfg = load_alert_config()
    assert cfg is not None
    assert cfg.webhook_clean == "https://clean.url"
    assert cfg.webhook_ugly == "https://ugly.url"
    assert cfg.webhook_system is None


def test_load_alert_config_uses_strategy_dedup_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strategy settings override the AlertConfig dedup window default."""
    from scanner.settings import StrategySettings

    monkeypatch.setenv("DISCORD_WEBHOOK_CLEAN", "https://clean.url")
    monkeypatch.setenv("DISCORD_WEBHOOK_UGLY", "https://ugly.url")
    strategy = StrategySettings(scanner_alert_dedup_hours=24)
    cfg = load_alert_config(strategy)
    assert cfg is not None
    assert cfg.dedup_window_hours == 24


def test_load_alert_config_without_strategy_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no strategy is passed, the AlertConfig default (8h) is used."""
    monkeypatch.setenv("DISCORD_WEBHOOK_CLEAN", "https://clean.url")
    monkeypatch.setenv("DISCORD_WEBHOOK_UGLY", "https://ugly.url")
    cfg = load_alert_config()
    assert cfg is not None
    assert cfg.dedup_window_hours == 8


def test_run_alerter_uses_configured_dedup_window() -> None:
    """The cutoff passed to the dedup query reflects AlertConfig.dedup_window_hours."""
    from datetime import UTC, datetime, timedelta

    client = _client()
    sel = SelectionResult(clean=[_candidate("BTC", "clean")])
    cfg = AlertConfig(
        webhook_clean=_CFG.webhook_clean,
        webhook_ugly=_CFG.webhook_ugly,
        dedup_window_hours=24,
    )
    before = datetime.now(UTC)
    with patch("scanner.alerter._post_to_webhook"):
        run_alerter(client, "run-id", {"BTC": "uuid-btc"}, sel, cfg)
    after = datetime.now(UTC)

    select_chain = client.table.return_value.select.return_value
    eq_chain = select_chain.eq.return_value.eq.return_value.eq.return_value
    gte_call = eq_chain.gte.call_args
    assert gte_call is not None, "dedup query did not call .gte()"
    cutoff_iso = gte_call[0][1]
    cutoff = datetime.fromisoformat(cutoff_iso)
    expected_min = before - timedelta(hours=24)
    expected_max = after - timedelta(hours=24)
    assert expected_min <= cutoff <= expected_max

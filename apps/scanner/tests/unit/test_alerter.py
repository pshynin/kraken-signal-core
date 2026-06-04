"""Unit tests for scanner.alerter — Discord formatting, dedup, dispatch.

All tests are fully offline:
    - Supabase client replaced with MagicMock.
    - httpx.post (via _post_to_webhook) patched with unittest.mock.patch.
    - No Discord webhooks are actually called.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from scanner.alerter import (
    _COLOR_CLEAN,
    _COLOR_UGLY,
    _DISCORD_MAX_CHARS,
    AlertConfig,
    _format_candidate_block,
    _is_already_alerted,
    _post_to_webhook,
    build_embed_payload,
    format_stacked_messages,
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


# ── _is_already_alerted ───────────────────────────────────────────────────────


def test_is_already_alerted_returns_true_when_data() -> None:
    client = _client(dedup_data=[{"id": "existing-alert"}])
    assert _is_already_alerted(client, "uuid-btc", "2026-01-01T00:00:00Z") is True


def test_is_already_alerted_returns_false_when_empty() -> None:
    client = _client(dedup_data=[])
    assert _is_already_alerted(client, "uuid-btc", "2026-01-01T00:00:00Z") is False


# ── _post_to_webhook ──────────────────────────────────────────────────────────


def _resp(status_code: int, retry_after: str | None = None) -> MagicMock:
    """Build a fake httpx.Response. raise_for_status raises HTTPStatusError
    for any status >= 400 (mirroring httpx behaviour)."""
    import httpx

    r = MagicMock()
    r.status_code = status_code
    r.headers = {} if retry_after is None else {"Retry-After": retry_after}
    if status_code >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status_code), request=MagicMock(), response=MagicMock()
        )
    else:
        r.raise_for_status.return_value = None
    return r


def test_post_to_webhook_raises_on_http_error() -> None:
    with patch("httpx.post") as mock_post:
        import httpx

        mock_post.return_value = _resp(404)
        with pytest.raises(httpx.HTTPStatusError):
            _post_to_webhook("https://example.com/webhook", {"embeds": []})


def test_post_to_webhook_does_not_retry_4xx() -> None:
    """A 404 is permanent — one POST, no retry, immediate raise."""
    import httpx

    with patch("httpx.post") as mock_post, patch("time.sleep") as mock_sleep:
        mock_post.return_value = _resp(404)
        with pytest.raises(httpx.HTTPStatusError):
            _post_to_webhook("https://example.com/webhook", {"embeds": []})
    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()


def test_post_to_webhook_retries_5xx_then_succeeds() -> None:
    """Two 503s then a 204 — succeeds on the third attempt, two backoff sleeps."""
    with patch("httpx.post") as mock_post, patch("time.sleep") as mock_sleep:
        mock_post.side_effect = [_resp(503), _resp(503), _resp(204)]
        _post_to_webhook("https://example.com/webhook", {"embeds": []})
    assert mock_post.call_count == 3
    assert mock_sleep.call_count == 2


def test_post_to_webhook_gives_up_after_max_attempts() -> None:
    """Persistent 500 — exhausts retries and raises on the final attempt."""
    import httpx

    with patch("httpx.post") as mock_post, patch("time.sleep") as mock_sleep:
        mock_post.side_effect = [_resp(500), _resp(500), _resp(500)]
        with pytest.raises(httpx.HTTPStatusError):
            _post_to_webhook("https://example.com/webhook", {"embeds": []})
    assert mock_post.call_count == 3
    assert mock_sleep.call_count == 2  # slept before attempts 2 and 3, not after 3


def test_post_to_webhook_honors_retry_after_header() -> None:
    """A 429 with Retry-After: 5 sleeps 5s, not the static backoff (1s)."""
    with patch("httpx.post") as mock_post, patch("time.sleep") as mock_sleep:
        mock_post.side_effect = [_resp(429, retry_after="5"), _resp(204)]
        _post_to_webhook("https://example.com/webhook", {"embeds": []})
    mock_sleep.assert_called_once_with(5.0)


def test_post_to_webhook_retries_connection_error_then_succeeds() -> None:
    """A RequestError (timeout/connection) is retried, then succeeds."""
    import httpx

    with patch("httpx.post") as mock_post, patch("time.sleep") as mock_sleep:
        mock_post.side_effect = [
            httpx.ConnectError("boom"),
            _resp(204),
        ]
        _post_to_webhook("https://example.com/webhook", {"embeds": []})
    assert mock_post.call_count == 2
    assert mock_sleep.call_count == 1


def test_post_to_webhook_connection_error_exhausts_and_raises() -> None:
    import httpx

    with patch("httpx.post") as mock_post, patch("time.sleep"):
        mock_post.side_effect = httpx.ConnectError("boom")
        with pytest.raises(httpx.ConnectError):
            _post_to_webhook("https://example.com/webhook", {"embeds": []})
    assert mock_post.call_count == 3


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


# ── format_stacked_messages ─────────────────────────────────────────────────────


def _when() -> datetime:
    return datetime(2026, 5, 14, 3, 15, tzinfo=UTC)


def test_format_stacked_messages_header_clean_emoji_and_label() -> None:
    msgs = format_stacked_messages([_candidate("BTC", "clean", 1)], "clean", _when())
    first_line = msgs[0].splitlines()[0]
    assert first_line.startswith("🟢 Clean Candidates — 1")


def test_format_stacked_messages_header_ugly_emoji_and_label() -> None:
    msgs = format_stacked_messages([_candidate("ETH", "ugly", 1)], "ugly", _when())
    first_line = msgs[0].splitlines()[0]
    assert first_line.startswith("🟡 Ugly Candidates — 1")


def test_format_stacked_messages_header_includes_timestamp() -> None:
    msgs = format_stacked_messages([_candidate("BTC", "clean", 1)], "clean", _when())
    first_line = msgs[0].splitlines()[0]
    assert "(<t:1778728500:R>)" in first_line


def test_format_stacked_messages_contains_all_symbols() -> None:
    candidates = [_candidate("BTC", "clean", 1), _candidate("ETH", "clean", 2)]
    msgs = format_stacked_messages(candidates, "clean", _when())
    combined = "".join(msgs)
    assert "#1 BTC" in combined
    assert "#2 ETH" in combined


def test_format_stacked_messages_under_discord_limit() -> None:
    candidates = [_candidate(f"C{i}", "clean", i + 1) for i in range(10)]
    msgs = format_stacked_messages(candidates, "clean", _when())
    for msg in msgs:
        assert len(msg) <= _DISCORD_MAX_CHARS


def test_format_stacked_messages_empty_returns_empty_list() -> None:
    assert format_stacked_messages([], "clean", _when()) == []


def test_format_stacked_messages_splits_between_candidates() -> None:
    """When the body would exceed the per-message cap, splits happen at
    candidate boundaries — never mid-block."""
    import scanner.alerter as alerter_mod

    original = alerter_mod._DISCORD_MAX_CHARS
    try:
        alerter_mod._DISCORD_MAX_CHARS = 300
        candidates = [_candidate(f"T{i}", "clean", i + 1) for i in range(5)]
        msgs = format_stacked_messages(candidates, "clean", _when())
        assert len(msgs) > 1
        # Each message must end with a Stop line (the last line of a block).
        for msg in msgs:
            assert msg.rstrip().splitlines()[-1].startswith("• Stop:")
    finally:
        alerter_mod._DISCORD_MAX_CHARS = original


# ── _format_candidate_block ───────────────────────────────────────────────────


def test_candidate_block_uses_preferred_entry_and_max_entry() -> None:
    block = _format_candidate_block(1, _candidate("BTC", "clean", 1))
    # The fixture has preferred_entry=50_000.0, max_entry=50_500.0.
    assert "Entry:" in block
    assert "50,000" in block
    assert "(Max 50,500" in block


def test_candidate_block_field_order_is_entry_exit_stop() -> None:
    """Four-line block: title + Entry + Exit + Stop. Size is in the title,
    not a separate line."""
    block = _format_candidate_block(1, _candidate("BTC", "clean", 1))
    lines = block.splitlines()
    assert len(lines) == 4
    assert lines[1].startswith("• Entry:")
    assert lines[2].startswith("• Exit:")
    assert lines[3].startswith("• Stop:")


def test_candidate_block_no_separate_size_line() -> None:
    """Size moved to the title; no line should start with '• Size'."""
    block = _format_candidate_block(1, _candidate("BTC", "clean", 1))
    for line in block.splitlines():
        assert not line.startswith("• Size")


def test_candidate_block_title_contains_prob_and_size() -> None:
    """Title line: '#R SYM • Prob P% • Size BUCKET'. No 'Gain' on the title."""
    block = _format_candidate_block(2, _candidate("ETH", "ugly", 2))
    title = block.splitlines()[0]
    assert title.startswith("#2 ETH")
    assert "• Prob " in title
    assert "• Size " in title
    # Bucket value comes through.
    assert "5k-10k" in title  # default fixture bucket


def test_candidate_block_no_gain_field_anywhere() -> None:
    """The legacy 'Gain' field is gone; profit is shown inline on Exit."""
    block = _format_candidate_block(1, _candidate("BTC", "clean", 1))
    assert "Gain" not in block


def test_candidate_block_profit_derived_from_entry_exit() -> None:
    """Profit % must be derived from preferred_entry / exit_price geometry,
    not read from tp.expected_gain_pct (which could drift)."""
    c = _candidate("BTC", "clean", 1)
    c.trade.preferred_entry = 100.0
    c.trade.exit_price = 120.0
    c.trade.stop_loss = 85.0
    c.trade.expected_gain_pct = 99.9  # deliberately wrong; must be ignored
    block = _format_candidate_block(1, c)
    # 20% profit, 15% risk — derived from prices, not from 99.9.
    assert "(Profit +20%)" in block
    assert "(Risk -15%)" in block
    assert "99" not in block  # nothing referenced 99.9


def test_candidate_block_risk_is_negative() -> None:
    """Risk is rendered with its natural negative sign."""
    c = _candidate("BTC", "clean", 1)
    c.trade.preferred_entry = 100.0
    c.trade.exit_price = 110.0
    c.trade.stop_loss = 92.0
    block = _format_candidate_block(1, c)
    assert "(Risk -8%)" in block


def test_candidate_block_value_columns_aligned() -> None:
    """Entry/Exit/Stop value columns all start at the same offset (col 10)
    so the prices line up vertically."""
    block = _format_candidate_block(1, _candidate("BTC", "clean", 1))
    lines = block.splitlines()
    # Skip the title line. Each field line: '• ' + 8-char-padded label.
    for line in lines[1:]:
        prefix = line[:10]
        # First 10 chars are the bullet+label+padding.
        assert prefix in ("• Entry:  ", "• Exit:   ", "• Stop:   "), (
            f"unexpected prefix: {prefix!r}"
        )


def test_candidate_block_omits_setup_abbreviation() -> None:
    """Setup abbreviations like PULL/RCL/BRK must not appear in the
    candidate title line — they were rejected as cryptic in the alert."""
    block = _format_candidate_block(1, _candidate("BTC", "clean", 1))
    title = block.splitlines()[0]
    for token in ("PULL", "RCL", "BRK"):
        assert token not in title


def test_candidate_block_no_notes_or_signature() -> None:
    block = _format_candidate_block(1, _candidate("BTC", "clean", 1))
    # The fixture's notes field is "trend:up | rsi:60". Notes must not
    # appear in the alert body, nor must any "Kraken Signal" signature.
    assert "trend:up" not in block
    assert "Kraken Signal" not in block


def test_candidate_block_raises_loudly_when_probability_is_none() -> None:
    """Invariant: alerted clean/ugly candidates must have a non-null
    probability_pct. The block builder fails loudly rather than rendering
    a degraded alert."""
    bad = _candidate("BTC", "clean", 1)
    bad.score.probability_pct = None
    with pytest.raises(ValueError) as exc:
        _format_candidate_block(1, bad)
    assert "probability_pct is None" in str(exc.value)


# ── Golden sample-output ────────────────────────────────────────────────────


def _make_inj() -> ScoredCandidate:
    """Fixture matching the locked target output: INJ with the exact
    prices/probability shown in the PR 22 plan. Profit is derived from
    entry/exit and rounds to +30%; risk derives to -11%."""
    c = _candidate("INJ", "ugly", 1)
    c.score.probability_pct = 77.0
    c.trade.preferred_entry = 4.8883
    c.trade.max_entry = 4.9620
    c.trade.exit_price = 6.3487
    c.trade.stop_loss = 4.3385
    c.trade.expected_gain_pct = 30.0
    c.trade.suggested_size_bucket = "2k-5k"
    return c


def _make_useless() -> ScoredCandidate:
    """USELESS fixture. Profit derives to +41%, risk to -15%."""
    c = _candidate("USELESS", "ugly", 2)
    c.score.probability_pct = 69.0
    c.trade.preferred_entry = 0.05907
    c.trade.max_entry = 0.05996
    c.trade.exit_price = 0.08342
    c.trade.stop_loss = 0.05046
    c.trade.expected_gain_pct = 41.0
    c.trade.suggested_size_bucket = "2k-5k"
    return c


_GOLDEN_BODY = (
    "🟡 Ugly Candidates — 2 (<t:1778728500:R>)\n"
    "\n"
    "#1 INJ • Prob 77% • Size 2k-5k\n"
    "• Entry:  4.8883 (Max 4.9620)\n"
    "• Exit:   6.3487 (Profit +30%)\n"
    "• Stop:   4.3385 (Risk -11%)\n"
    "\n"
    "#2 USELESS • Prob 69% • Size 2k-5k\n"
    "• Entry:  0.05907 (Max 0.05996)\n"
    "• Exit:   0.08342 (Profit +41%)\n"
    "• Stop:   0.05046 (Risk -15%)"
)


def test_format_stacked_messages_matches_golden_output() -> None:
    msgs = format_stacked_messages([_make_inj(), _make_useless()], "ugly", _when())
    assert len(msgs) == 1
    assert msgs[0] == _GOLDEN_BODY


# ── build_embed_payload ─────────────────────────────────────────────────────


def test_build_embed_payload_clean_color() -> None:
    payload = build_embed_payload("body", "clean")
    assert payload["embeds"][0]["color"] == _COLOR_CLEAN
    assert payload["embeds"][0]["description"] == "body"


def test_build_embed_payload_ugly_color() -> None:
    payload = build_embed_payload("body", "ugly")
    assert payload["embeds"][0]["color"] == _COLOR_UGLY


def test_build_embed_payload_has_no_title_or_footer() -> None:
    """The header line is part of the body. No bot/product signature."""
    payload = build_embed_payload("body", "clean")
    embed = payload["embeds"][0]
    assert "title" not in embed
    assert "footer" not in embed


def test_run_alerter_posts_embed_payload_not_content() -> None:
    """The dispatcher must send {'embeds': [...]} rather than {'content': ...}."""
    client = _client()
    sel = SelectionResult(clean=[_candidate("BTC", "clean")])
    with patch("scanner.alerter._post_to_webhook") as mock_post:
        run_alerter(client, "run-id", {"BTC": "uuid-btc"}, sel, _CFG)
    payload = mock_post.call_args[0][1]
    assert "embeds" in payload
    assert "content" not in payload
    assert payload["embeds"][0]["color"] == _COLOR_CLEAN


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

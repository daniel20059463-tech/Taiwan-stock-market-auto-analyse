from __future__ import annotations

import datetime

from trading.market_state import CandleBar, MarketState


def _ts_minute(minute: int) -> int:
    dt = datetime.datetime(2026, 4, 6, 9, minute, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def test_update_tick_tracks_open_last_and_current_bar_close() -> None:
    state = MarketState()

    state.update_tick("2330", price=100.0, volume=10, ts_ms=_ts_minute(0))
    state.update_tick("2330", price=101.0, volume=5, ts_ms=_ts_minute(0))

    assert state.open_price("2330") == 100.0
    assert state.last_price("2330") == 101.0

    bar = state.latest_bar("2330")
    assert bar == CandleBar(
        ts_min=_ts_minute(0) // 60_000,
        open=100.0,
        high=101.0,
        low=100.0,
        close=101.0,
        volume=15,
    )


def test_average_volume_is_none_until_five_closed_bars_exist() -> None:
    state = MarketState()

    for minute in range(4):
        state.update_tick("2330", price=100.0 + minute, volume=10 + minute, ts_ms=_ts_minute(minute))

    assert state.average_volume("2330") is None

    state.update_tick("2330", price=104.0, volume=14, ts_ms=_ts_minute(4))
    assert state.average_volume("2330") is None

    state.update_tick("2330", price=105.0, volume=15, ts_ms=_ts_minute(5))

    assert state.average_volume("2330") == 12.0


def test_calculate_atr_returns_exact_value_from_closed_bars() -> None:
    state = MarketState()

    prices = [100.0, 102.0, 99.0, 103.0, 98.0, 104.0]
    for minute, price in enumerate(prices):
        state.update_tick("2330", price=price, volume=10 + minute, ts_ms=_ts_minute(minute))

    assert state.calculate_atr("2330") == 3.5

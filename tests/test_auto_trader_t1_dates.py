from __future__ import annotations

from auto_trader import AutoTrader


def _bare_trader(current_date: str, *, with_daily_cache: bool = False) -> AutoTrader:
    trader = object.__new__(AutoTrader)
    trader._current_date = current_date
    trader._daily_price_cache = object() if with_daily_cache else None
    return trader


def test_swing_trade_date_uses_previous_open_trading_day():
    trader = _bare_trader("2026-04-21")

    assert trader._swing_trade_date() == "2026-04-20"


def test_swing_trade_date_skips_weekend_to_previous_open_day():
    trader = _bare_trader("2026-04-27")

    assert trader._swing_trade_date() == "2026-04-24"


def test_prev_trade_date_for_daily_indicators_stays_on_yesterday():
    trader = _bare_trader("2026-04-21", with_daily_cache=True)

    assert trader._prev_trade_date() == "2026-04-20"

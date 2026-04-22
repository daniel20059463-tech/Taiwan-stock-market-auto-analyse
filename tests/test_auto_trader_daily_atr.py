from __future__ import annotations

from auto_trader import AutoTrader


class _FakeDailyPriceCache:
    def atr(self, symbol: str, period: int, as_of_date: str) -> float:
        return 1.23


def test_daily_atr_uses_instance_prev_trade_date_without_name_error():
    trader = object.__new__(AutoTrader)
    trader._daily_price_cache = _FakeDailyPriceCache()
    trader._current_date = "2026-04-22"
    trader._calc_atr = lambda symbol: None
    trader._prev_trade_date = lambda: "2026-04-21"

    assert trader._daily_atr("2330") == 1.23

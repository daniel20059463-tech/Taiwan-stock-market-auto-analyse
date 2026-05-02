from __future__ import annotations

from auto_trader import AutoTrader


def test_buy_slippage_uses_large_cap_tier() -> None:
    trader = object.__new__(AutoTrader)
    trader._average_daily_value_20d = lambda symbol: 600_000_000.0
    trader._latest_bar_notional = lambda symbol: 30_000_000.0

    assert trader._resolve_slippage_bps("2330", price=100.0, shares=1000) == 5


def test_buy_slippage_uses_mid_liquidity_tier() -> None:
    trader = object.__new__(AutoTrader)
    trader._average_daily_value_20d = lambda symbol: 200_000_000.0
    trader._latest_bar_notional = lambda symbol: 30_000_000.0

    assert trader._resolve_slippage_bps("2330", price=100.0, shares=1000) == 10


def test_buy_slippage_uses_low_liquidity_tier() -> None:
    trader = object.__new__(AutoTrader)
    trader._average_daily_value_20d = lambda symbol: 50_000_000.0
    trader._latest_bar_notional = lambda symbol: 30_000_000.0

    assert trader._resolve_slippage_bps("2330", price=100.0, shares=1000) == 20


def test_buy_slippage_adds_pressure_penalty_when_order_is_too_large() -> None:
    trader = object.__new__(AutoTrader)
    trader._average_daily_value_20d = lambda symbol: 600_000_000.0
    trader._latest_bar_notional = lambda symbol: 1_000_000.0

    assert trader._resolve_slippage_bps("2330", price=100.0, shares=1000) == 15

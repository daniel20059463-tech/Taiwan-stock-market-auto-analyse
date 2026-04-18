from __future__ import annotations

import types

import pytest

from auto_trader import AutoTrader


class _FakeRiskManager:
    def __init__(self) -> None:
        self.daily_pnl = 0.0
        self.rolling_5day_pnl = 0.0
        self.is_halted = False
        self.is_weekly_halted = False
        self.is_in_cooldown = False
        self.consecutive_losses = 0
        self.just_entered_cooldown = False
        self.min_net_profit_pct = 1.085

    def can_buy(self, symbol: str, price: float, shares: int, current_positions: int) -> tuple[bool, str]:
        return True, "OK"

    def calc_stop_price(self, price: float, atr: float | None) -> float:
        return round(price * 0.97, 2)

    def calc_target_price(self, price: float, stop_price: float) -> float:
        risk = price - stop_price
        return round(price + risk * 2, 2)

    def calc_position_shares(self, price: float, stop_price: float, lot_size: int = 1000) -> int:
        return lot_size

    def on_buy(self, symbol: str, price: float, shares: int) -> None:
        return None

    def on_sell(self, symbol: str, pnl: float) -> None:
        self.daily_pnl += pnl

    def calc_net_pnl(self, entry_price: float, sell_price: float, shares: int) -> float:
        return round((sell_price - entry_price) * shares, 2)

    def status_dict(self) -> dict[str, object]:
        return {
            "date": "2026-04-11",
            "dailyPnl": round(self.daily_pnl, 0),
            "dailyLossLimit": -20_000.0,
            "isHalted": self.is_halted,
            "rolling5DayPnl": round(self.rolling_5day_pnl, 0),
            "rolling5DayLimit": -50_000.0,
            "isWeeklyHalted": self.is_weekly_halted,
            "dailyTradeCount": 0,
            "maxPositions": 5,
            "maxSinglePosition": 100_000.0,
            "txCostRoundtripPct": 0.585,
        }


async def _noop(*args, **kwargs) -> None:
    return None


def _make_trader() -> AutoTrader:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=None,
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._persist_position_open = types.MethodType(_noop, trader)
    trader._persist_position_close = types.MethodType(_noop, trader)
    trader._last_prices["2330"] = 504.0
    trader._open_prices["2330"] = 500.0
    trader._prev_close_cache["2330"] = 500.0
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.2, trader)
    return trader


@pytest.mark.asyncio
async def test_execute_manual_trade_buy_delegates_to_execution_service() -> None:
    trader = _make_trader()
    calls: list[tuple[str, str]] = []

    class _FakeExecution:
        async def execute_buy(self, **kwargs):
            calls.append(("BUY", kwargs["symbol"]))

        async def execute_sell(self, **kwargs):
            raise AssertionError("unexpected sell")

        async def execute_short(self, **kwargs):
            raise AssertionError("unexpected short")

        async def execute_cover(self, **kwargs):
            raise AssertionError("unexpected cover")

    trader._execution = _FakeExecution()

    await trader.execute_manual_trade(symbol="2330", action="BUY", shares=1000, ts_ms=1_775_600_000_000)

    assert calls == [("BUY", "2330")]


@pytest.mark.asyncio
async def test_execute_manual_trade_buy_creates_long_position() -> None:
    trader = _make_trader()

    snapshot = await trader.execute_manual_trade(symbol="2330", action="BUY", shares=1000, ts_ms=1_775_600_000_000)

    assert "2330" in trader._positions
    assert snapshot["positions"][0]["symbol"] == "2330"
    assert snapshot["recentTrades"][-1]["action"] == "BUY"


@pytest.mark.asyncio
async def test_execute_manual_trade_sell_closes_existing_long_position() -> None:
    trader = _make_trader()
    await trader.execute_manual_trade(symbol="2330", action="BUY", shares=1000, ts_ms=1_775_600_000_000)

    snapshot = await trader.execute_manual_trade(symbol="2330", action="SELL", shares=1000, ts_ms=1_775_600_060_000)

    assert "2330" not in trader._positions
    assert snapshot["positions"] == []
    assert snapshot["recentTrades"][-1]["action"] == "SELL"


@pytest.mark.asyncio
async def test_execute_manual_trade_sell_requires_existing_long_position() -> None:
    trader = _make_trader()

    with pytest.raises(ValueError, match="long_position_required"):
        await trader.execute_manual_trade(symbol="2330", action="SELL", shares=1000, ts_ms=1_775_600_000_000)

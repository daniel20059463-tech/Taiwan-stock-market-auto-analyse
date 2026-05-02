"""Tests for limit-lock state detection."""
from __future__ import annotations

import types

from auto_trader import AutoTrader


class _FakeRiskManager:
    def __init__(self) -> None:
        self.daily_pnl = 0.0
        self.rolling_5day_pnl = 0.0
        self.is_halted = False
        self.is_weekly_halted = False
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
            "date": "2026-04-06",
            "dailyPnl": 0.0,
            "dailyLossLimit": -20_000.0,
            "isHalted": False,
            "rolling5DayPnl": 0.0,
            "rolling5DayLimit": -50_000.0,
            "isWeeklyHalted": False,
            "dailyTradeCount": 0,
            "maxPositions": 5,
            "maxSinglePosition": 100_000.0,
            "txCostRoundtripPct": 0.585,
        }


class _FakeSentimentFilter:
    def is_buy_blocked(self, symbol: str) -> bool:
        return False

    def get_score(self, symbol: str) -> float | None:
        return None


async def _noop(*args, **kwargs) -> None:
    return None


def _make_trader() -> AutoTrader:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(),
        db_session_factory=None,
    )
    trader._send = types.MethodType(_noop, trader)
    return trader


def test_limit_up_lock_detected() -> None:
    trader = _make_trader()
    trader._update_limit_lock_state("2330", 10.0, {"nearLimitUp": True, "nearLimitDown": False})
    assert trader._limit_locked.get("2330") == "up"


def test_limit_down_lock_detected() -> None:
    trader = _make_trader()
    trader._update_limit_lock_state("2330", -10.0, {"nearLimitUp": False, "nearLimitDown": True})
    assert trader._limit_locked.get("2330") == "down"


def test_limit_lock_clears_when_not_locked() -> None:
    trader = _make_trader()
    trader._limit_locked["2330"] = "up"
    trader._update_limit_lock_state("2330", 5.0, {"nearLimitUp": False, "nearLimitDown": False})
    assert "2330" not in trader._limit_locked


def test_near_limit_up_but_not_at_threshold() -> None:
    trader = _make_trader()
    trader._update_limit_lock_state("2330", 8.5, {"nearLimitUp": True, "nearLimitDown": False})
    assert "2330" not in trader._limit_locked

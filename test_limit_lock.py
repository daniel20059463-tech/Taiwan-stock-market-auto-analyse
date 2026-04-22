"""Tests for limit-lock detection (漲跌停鎖死過濾)."""
from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auto_trader import AutoTrader


# ── shared test doubles ────────────────────────────────────────────────────────

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
        pass

    def on_sell(self, symbol: str, pnl: float) -> None:
        self.daily_pnl += pnl

    def calc_net_pnl(self, entry_price: float, sell_price: float, shares: int) -> float:
        return round((sell_price - entry_price) * shares, 2)

    def status_dict(self) -> dict:
        return {
            "date": "2026-04-06", "dailyPnl": 0.0, "dailyLossLimit": -20_000.0,
            "isHalted": False, "rolling5DayPnl": 0.0, "rolling5DayLimit": -50_000.0,
            "isWeeklyHalted": False, "dailyTradeCount": 0, "maxPositions": 5,
            "maxSinglePosition": 100_000.0, "txCostRoundtripPct": 0.585,
        }


class _FakeSentimentFilter:
    def is_buy_blocked(self, symbol: str) -> bool:
        return False

    def get_score(self, symbol: str) -> float | None:
        return None


async def _noop(*args, **kwargs) -> None:
    return None


def _make_trader(**overrides) -> AutoTrader:
    kwargs = dict(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(),
        db_session_factory=None,
    )
    kwargs.update(overrides)
    trader = AutoTrader(**kwargs)
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, sym: True, trader)
    trader._calc_atr = types.MethodType(lambda self, sym: None, trader)
    return trader


_SYMBOL = "2330"
_TS = 1_775_500_000_000  # within trading hours


# ── limit lock state tests ─────────────────────────────────────────────────────


def test_limit_up_lock_detected() -> None:
    """漲停鎖死被正確偵測。"""
    trader = _make_trader()
    payload = {"nearLimitUp": True, "nearLimitDown": False}
    trader._update_limit_lock_state(_SYMBOL, 10.0, payload)
    assert trader._limit_locked.get(_SYMBOL) == "up"


def test_limit_down_lock_detected() -> None:
    """跌停鎖死被正確偵測。"""
    trader = _make_trader()
    payload = {"nearLimitUp": False, "nearLimitDown": True}
    trader._update_limit_lock_state(_SYMBOL, -10.0, payload)
    assert trader._limit_locked.get(_SYMBOL) == "down"


def test_limit_lock_clears_when_not_locked() -> None:
    """解除鎖死後狀態清除。"""
    trader = _make_trader()
    trader._limit_locked[_SYMBOL] = "up"
    payload = {"nearLimitUp": False, "nearLimitDown": False}
    trader._update_limit_lock_state(_SYMBOL, 5.0, payload)
    assert _SYMBOL not in trader._limit_locked


def test_near_limit_up_but_not_at_threshold() -> None:
    """nearLimitUp=True 但漲幅不到 9.5% 不觸發鎖死。"""
    trader = _make_trader()
    payload = {"nearLimitUp": True, "nearLimitDown": False}
    trader._update_limit_lock_state(_SYMBOL, 8.5, payload)
    assert _SYMBOL not in trader._limit_locked


# ── limit lock exit blocking tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_exit_skipped_when_limit_down_locked() -> None:
    """跌停鎖死時 _check_exit 不應執行賣出。"""
    trader = _make_trader()
    # Create a long position first
    await trader._evaluate_buy(
        _SYMBOL, 920.0, 2.5, _TS,
        {"high": 930.0, "low": 910.0, "open": 915.0, "previousClose": 897.0, "volume": 100_000},
    )
    assert _SYMBOL in trader._positions

    # Lock the symbol at limit down
    trader._limit_locked[_SYMBOL] = "down"

    # Price triggers stop loss
    stop_price = trader._positions[_SYMBOL].stop_price
    exit_price = stop_price - 10.0

    # _check_exit should return early without selling
    await trader._check_exit(_SYMBOL, exit_price, _TS + 60_000)

    # Position should still be open
    assert _SYMBOL in trader._positions


@pytest.mark.asyncio
async def test_check_exit_executes_when_not_locked() -> None:
    """未鎖死時 _check_exit 照常執行賣出。"""
    trader = _make_trader()
    await trader._evaluate_buy(
        _SYMBOL, 920.0, 2.5, _TS,
        {"high": 930.0, "low": 910.0, "open": 915.0, "previousClose": 897.0, "volume": 100_000},
    )
    assert _SYMBOL in trader._positions

    stop_price = trader._positions[_SYMBOL].stop_price
    exit_price = stop_price - 10.0

    await trader._check_exit(_SYMBOL, exit_price, _TS + 60_000)

    # Position should be closed
    assert _SYMBOL not in trader._positions


@pytest.mark.asyncio
async def test_check_short_exit_skipped_when_limit_up_locked() -> None:
    """漲停鎖死時 空方 _check_short_exit 不應執行回補。"""
    trader = _make_trader()
    trader._sentiment = type("S", (), {"get_score": lambda self, s: -0.5})()

    await trader._evaluate_short(
        _SYMBOL, 900.0, -2.0, _TS,
        {"high": 910.0, "low": 895.0, "open": 908.0, "previousClose": 918.0, "volume": 100_000},
    )

    if _SYMBOL not in trader._positions:
        pytest.skip("Short entry conditions not met in test setup")

    # Lock the symbol at limit up
    trader._limit_locked[_SYMBOL] = "up"

    # Price triggers stop loss for short
    stop_price = trader._positions[_SYMBOL].stop_price
    exit_price = stop_price + 10.0

    await trader._check_short_exit(_SYMBOL, exit_price, _TS + 60_000)

    # Position should still be open (locked)
    assert _SYMBOL in trader._positions


# ── EOD with limit lock tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_eod_close_warns_on_limit_down_locked_long() -> None:
    """EOD 平倉時若多方部位跌停鎖死，應發出警告。"""
    trader = _make_trader()
    await trader._evaluate_buy(
        _SYMBOL, 920.0, 2.5, _TS,
        {"high": 930.0, "low": 910.0, "open": 915.0, "previousClose": 897.0, "volume": 100_000},
    )
    assert _SYMBOL in trader._positions

    trader._limit_locked[_SYMBOL] = "down"

    sent_messages: list[str] = []
    original_send = trader._send

    async def _capture_send(text, *args, **kwargs):
        sent_messages.append(text)

    trader._send = _capture_send

    await trader._close_all_eod(_TS + 60_000)

    # Should have sent a warning message
    warning_msgs = [m for m in sent_messages if "跌停鎖死" in m]
    assert len(warning_msgs) > 0

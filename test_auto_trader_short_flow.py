"""Tests for short-selling (SHORT / COVER) flow in AutoTrader.

Covers: entry, skip, stop-loss cover, take-profit cover, EOD forced cover.
"""
from __future__ import annotations

import types

import pytest

from auto_trader import AutoTrader


# ── shared test doubles ────────────────────────────────────────────────────────


class _FakeRiskManager:
    def __init__(self) -> None:
        self.daily_pnl = 0.0
        self.rolling_5day_pnl = 0.0
        self.is_halted = False
        self.is_weekly_halted = False

    def can_buy(self, symbol: str, price: float, shares: int, current_positions: int) -> tuple[bool, str]:
        return True, "OK"

    def calc_stop_price(self, price: float, atr: float | None) -> float:
        return round(price * 0.97, 2)

    def calc_target_price(self, price: float, stop_price: float) -> float:
        risk = price - stop_price
        return round(price + risk * 2, 2)

    def on_buy(self, symbol: str, price: float, shares: int) -> None:
        pass

    def on_sell(self, symbol: str, pnl: float) -> None:
        self.daily_pnl += pnl

    def calc_net_pnl(self, entry_price: float, sell_price: float, shares: int) -> float:
        return round((sell_price - entry_price) * shares, 2)

    def status_dict(self) -> dict[str, object]:
        return {
            "date": "2026-04-04",
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


class _FakeSentimentFilter:
    def __init__(self, score: float | None = None, blocked: bool = False) -> None:
        self._score = score
        self._blocked = blocked

    def is_buy_blocked(self, symbol: str) -> bool:
        return self._blocked

    def get_score(self, symbol: str) -> float | None:
        return self._score


async def _noop(*args, **kwargs) -> None:
    return None


_SHORT_PAYLOAD = {
    "high": 1312.0,
    "low": 1280.0,
    "open": 1308.0,
    "previousClose": 1315.0,
    "volume": 80_000,
}
_SHORT_SYMBOL = "2454"
_SHORT_PRICE = 1288.0
_SHORT_CHANGE_PCT = -2.1
_SHORT_TS = 1_775_500_700_000


def _make_trader(sentiment_score: float = -0.55) -> AutoTrader:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=sentiment_score, blocked=False),
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.2, trader)
    return trader


# ── tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_short_entry_creates_short_position_and_trade_record() -> None:
    trader = _make_trader(sentiment_score=-0.55)

    await trader._evaluate_short(
        _SHORT_SYMBOL, _SHORT_PRICE, _SHORT_CHANGE_PCT, _SHORT_TS, _SHORT_PAYLOAD
    )

    assert _SHORT_SYMBOL in trader._positions
    position = trader._positions[_SHORT_SYMBOL]
    assert position.side == "short"
    assert position.entry_price == round(_SHORT_PRICE * 0.9995, 2)

    snapshot = trader.get_portfolio_snapshot()
    last_trade = snapshot["recentTrades"][-1]
    assert last_trade["action"] == "SHORT"
    assert last_trade["symbol"] == _SHORT_SYMBOL

    last_decision = snapshot["recentDecisions"][-1]
    assert last_decision["decisionType"] == "short"
    assert last_decision["orderResult"]["status"] == "executed"


@pytest.mark.asyncio
async def test_short_signal_skipped_when_sentiment_not_negative_enough() -> None:
    trader = _make_trader(sentiment_score=-0.10)  # above -0.25 threshold

    await trader._evaluate_short(
        _SHORT_SYMBOL, _SHORT_PRICE, _SHORT_CHANGE_PCT, _SHORT_TS, _SHORT_PAYLOAD
    )

    assert _SHORT_SYMBOL not in trader._positions
    snapshot = trader.get_portfolio_snapshot()
    assert snapshot["recentTrades"] == []

    last_decision = snapshot["recentDecisions"][-1]
    assert last_decision["decisionType"] == "skip"
    assert last_decision["finalReason"] == "sentiment_not_negative"


@pytest.mark.asyncio
async def test_short_stop_loss_covers_when_price_rebounds() -> None:
    trader = _make_trader()

    await trader._evaluate_short(
        _SHORT_SYMBOL, _SHORT_PRICE, _SHORT_CHANGE_PCT, _SHORT_TS, _SHORT_PAYLOAD
    )

    # With _FakeRiskManager: stop_price(1288) = 1249.36
    # short_stop = 1288 + (1288 - 1249.36) = 1326.64 → price 1335 triggers stop-loss
    rebound_price = 1335.0
    await trader._check_short_exit(_SHORT_SYMBOL, rebound_price, _SHORT_TS + 60_000)

    assert _SHORT_SYMBOL not in trader._positions
    snapshot = trader.get_portfolio_snapshot()
    last_trade = snapshot["recentTrades"][-1]
    assert last_trade["action"] == "COVER"
    assert last_trade["reason"] == "STOP_LOSS"
    assert last_trade["netPnl"] < 0  # stop-loss → loss


@pytest.mark.asyncio
async def test_short_take_profit_covers_when_price_drops_to_target() -> None:
    trader = _make_trader()

    await trader._evaluate_short(
        _SHORT_SYMBOL, _SHORT_PRICE, _SHORT_CHANGE_PCT, _SHORT_TS, _SHORT_PAYLOAD
    )

    # With _FakeRiskManager: short_target = 1288 - 77.28 = 1210.72 → price 1200 triggers take-profit
    target_price = 1200.0
    await trader._check_short_exit(_SHORT_SYMBOL, target_price, _SHORT_TS + 60_000)

    assert _SHORT_SYMBOL not in trader._positions
    snapshot = trader.get_portfolio_snapshot()
    last_trade = snapshot["recentTrades"][-1]
    assert last_trade["action"] == "COVER"
    assert last_trade["reason"] == "TAKE_PROFIT"
    assert last_trade["netPnl"] > 0  # take-profit → profit


@pytest.mark.asyncio
async def test_short_position_is_forced_covered_at_eod() -> None:
    trader = _make_trader()

    await trader._evaluate_short(
        _SHORT_SYMBOL, _SHORT_PRICE, _SHORT_CHANGE_PCT, _SHORT_TS, _SHORT_PAYLOAD
    )

    assert _SHORT_SYMBOL in trader._positions
    await trader._close_all_eod(_SHORT_TS + 60_000)

    assert _SHORT_SYMBOL not in trader._positions
    snapshot = trader.get_portfolio_snapshot()
    last_trade = snapshot["recentTrades"][-1]
    assert last_trade["action"] == "COVER"
    assert last_trade["reason"] == "EOD"


@pytest.mark.asyncio
async def test_short_unrealized_pnl_is_positive_when_price_drops() -> None:
    trader = _make_trader()

    await trader._evaluate_short(
        _SHORT_SYMBOL, _SHORT_PRICE, _SHORT_CHANGE_PCT, _SHORT_TS, _SHORT_PAYLOAD
    )

    trader._last_prices[_SHORT_SYMBOL] = 1200.0
    snapshot = trader.get_portfolio_snapshot()

    assert snapshot["positions"]
    position = snapshot["positions"][0]
    assert position["side"] == "short"
    assert position["pnl"] > 0
    assert position["pct"] > 0

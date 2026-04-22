"""Tests for portfolio-level AnalystContext enrichment and analyst scoring."""
from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auto_trader import AutoTrader
from multi_analyst import AnalystContext, RiskAnalyst, TechnicalAnalyst


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_base_context(**overrides) -> AnalystContext:
    defaults = dict(
        symbol="2330",
        ts=1_775_500_000_000,
        decision_type="buy",
        trigger_type="price",
        price=920.0,
        change_pct=2.5,
        volume_confirmed=True,
        sentiment_score=0.0,
        market_change_pct=0.3,
        risk_allowed=True,
        risk_reason="OK",
        risk_flags=[],
    )
    defaults.update(overrides)
    return AnalystContext(**defaults)


class _FakeRiskManager:
    def __init__(self, daily_pnl: float = 0.0) -> None:
        self._daily_pnl = daily_pnl
        self.min_net_profit_pct = 1.085

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    def can_buy(self, symbol, price, shares, current_positions):
        return True, "OK"

    def calc_stop_price(self, price, atr):
        return round(price * 0.97, 2)

    def calc_target_price(self, price, stop_price):
        return round(price + (price - stop_price) * 2, 2)

    def calc_position_shares(self, price, stop_price, lot_size=1000):
        return lot_size

    def on_buy(self, symbol, price, shares):
        pass

    def on_sell(self, symbol, pnl):
        pass

    def calc_net_pnl(self, entry_price, sell_price, shares):
        return round((sell_price - entry_price) * shares, 2)

    def status_dict(self) -> dict:
        return {
            "date": "2026-04-06",
            "dailyPnl": self._daily_pnl,
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
    def is_buy_blocked(self, symbol):
        return False

    def get_score(self, symbol):
        return None


async def _noop(*args, **kwargs):
    return None


def _make_trader(daily_pnl: float = 0.0) -> AutoTrader:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(daily_pnl=daily_pnl),
        sentiment_filter=_FakeSentimentFilter(),
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, sym: True, trader)
    trader._calc_atr = types.MethodType(lambda self, sym: None, trader)
    return trader


# ── AnalystContext defaults ────────────────────────────────────────────────────


def test_analyst_context_portfolio_fields_have_zero_defaults() -> None:
    """AnalystContext 的組合欄位必須有零值預設，保持向後相容。"""
    ctx = _make_base_context()
    assert ctx.portfolio_positions_count == 0
    assert ctx.portfolio_unrealized_pnl == 0.0
    assert ctx.portfolio_daily_win_rate == 0.0
    assert ctx.portfolio_risk_budget_used_pct == 0.0


# ── _build_portfolio_context ───────────────────────────────────────────────────


def test_build_portfolio_context_empty_state() -> None:
    """無持倉、無成交時，所有欄位應為零。"""
    trader = _make_trader()
    ctx = trader._build_portfolio_context()
    assert ctx["portfolio_positions_count"] == 0
    assert ctx["portfolio_unrealized_pnl"] == 0.0
    assert ctx["portfolio_daily_win_rate"] == 0.0
    assert ctx["portfolio_risk_budget_used_pct"] == 0.0


def test_build_portfolio_context_positions_count() -> None:
    """持倉數應正確反映 _positions 的大小。"""
    trader = _make_trader()
    # 直接注入假持倉（不需要實際下單流程）
    from trading.positions import PaperPosition
    for sym in ("2330", "2317", "2454"):
        trader._positions[sym] = PaperPosition(
            symbol=sym, side="long", entry_price=100.0, shares=1000,
            entry_ts=1_000_000, entry_change_pct=2.0,
            stop_price=97.0, target_price=106.0,
        )

    ctx = trader._build_portfolio_context()
    assert ctx["portfolio_positions_count"] == 3


def test_build_portfolio_context_risk_budget_used() -> None:
    """日損已用比例計算：dailyPnl / dailyLossLimit（負數相除取正）。"""
    # daily_pnl=-10000, daily_loss_limit=-20000 → 50%
    trader = _make_trader(daily_pnl=-10_000.0)
    ctx = trader._build_portfolio_context()
    assert abs(ctx["portfolio_risk_budget_used_pct"] - 0.5) < 1e-6


def test_build_portfolio_context_win_rate() -> None:
    """已成交中有獲利的比例應正確計算。"""
    from trading.positions import TradeRecord
    trader = _make_trader()
    trader._trade_history.append(TradeRecord(symbol="A", action="SELL", price=100.0, shares=1000, pnl=500.0, reason="TAKE_PROFIT", ts=1, stop_price=97.0))
    trader._trade_history.append(TradeRecord(symbol="B", action="SELL", price=100.0, shares=1000, pnl=-200.0, reason="STOP_LOSS", ts=2, stop_price=97.0))
    trader._trade_history.append(TradeRecord(symbol="C", action="SELL", price=100.0, shares=1000, pnl=300.0, reason="TAKE_PROFIT", ts=3, stop_price=97.0))

    ctx = trader._build_portfolio_context()
    assert abs(ctx["portfolio_daily_win_rate"] - 2 / 3) < 1e-6


# ── RiskAnalyst portfolio-aware scoring ───────────────────────────────────────


def test_risk_analyst_penalizes_high_position_count() -> None:
    """持倉數 >= 4 時，RiskAnalyst 應降分並加入 opposing_factor。"""
    analyst = RiskAnalyst()
    ctx = _make_base_context(portfolio_positions_count=4, portfolio_risk_budget_used_pct=0.0)
    view = analyst.analyze(ctx)

    labels = [f.label for f in view.opposing_factors]
    assert "持倉接近上限" in labels
    # Score should be below 70 (normal allowed score) due to penalty
    assert view.score < 70


def test_risk_analyst_blocks_when_budget_exhausted() -> None:
    """風控預算耗盡（>=80%）時，RiskAnalyst 應設定 blocking=True。"""
    analyst = RiskAnalyst()
    ctx = _make_base_context(portfolio_risk_budget_used_pct=0.85)
    view = analyst.analyze(ctx)

    assert view.blocking is True
    labels = [f.label for f in view.opposing_factors]
    assert "風控預算耗盡" in labels


def test_risk_analyst_penalizes_when_budget_half_consumed() -> None:
    """風控預算超過 50% 但未達 80% 時，應降分但不阻擋。"""
    analyst = RiskAnalyst()
    ctx = _make_base_context(portfolio_risk_budget_used_pct=0.6)
    view = analyst.analyze(ctx)

    assert view.blocking is False
    labels = [f.label for f in view.opposing_factors]
    assert "風控預算過半" in labels
    assert view.score < 70


def test_risk_analyst_no_penalty_when_budget_low() -> None:
    """風控預算未超過 50% 時，不應加入任何預算相關的 opposing_factor。"""
    analyst = RiskAnalyst()
    ctx = _make_base_context(portfolio_risk_budget_used_pct=0.3)
    view = analyst.analyze(ctx)

    labels = [f.label for f in view.opposing_factors]
    assert "風控預算耗盡" not in labels
    assert "風控預算過半" not in labels


# ── TechnicalAnalyst portfolio-aware scoring ──────────────────────────────────


def test_technical_analyst_penalizes_heavy_unrealized_loss() -> None:
    """整體未實現損益 < -5000 時，TechnicalAnalyst 應降分並加入 opposing_factor。"""
    analyst = TechnicalAnalyst()
    ctx = _make_base_context(portfolio_unrealized_pnl=-8000.0)
    view = analyst.analyze(ctx)

    labels = [f.label for f in view.opposing_factors]
    assert "組合浮虧偏重" in labels


def test_technical_analyst_no_penalty_when_pnl_acceptable() -> None:
    """未實現損益 > -5000 時，不應加入浮虧相關的 opposing_factor。"""
    analyst = TechnicalAnalyst()
    ctx = _make_base_context(portfolio_unrealized_pnl=-2000.0)
    view = analyst.analyze(ctx)

    labels = [f.label for f in view.opposing_factors]
    assert "組合浮虧偏重" not in labels


# ── Integration: portfolio context injected into decision bundle ───────────────


def test_portfolio_context_fed_into_risk_analyst() -> None:
    """_build_portfolio_context 的結果應能驅動 RiskAnalyst 的評分。"""
    trader = _make_trader(daily_pnl=-12_000.0)  # 60% budget used

    # 注入 3 個假持倉
    from trading.positions import PaperPosition
    for sym in ("2330", "2317", "2454"):
        trader._positions[sym] = PaperPosition(
            symbol=sym, side="long", entry_price=100.0, shares=1000,
            entry_ts=1_000_000, entry_change_pct=2.0,
            stop_price=97.0, target_price=106.0,
        )

    portfolio = trader._build_portfolio_context()
    assert portfolio["portfolio_positions_count"] == 3
    assert abs(portfolio["portfolio_risk_budget_used_pct"] - 0.6) < 1e-6

    # Verify RiskAnalyst uses these values correctly
    analyst = RiskAnalyst()
    ctx = _make_base_context(
        portfolio_risk_budget_used_pct=portfolio["portfolio_risk_budget_used_pct"],
        portfolio_positions_count=portfolio["portfolio_positions_count"],
    )
    view = analyst.analyze(ctx)
    labels = [f.label for f in view.opposing_factors]
    assert "風控預算過半" in labels

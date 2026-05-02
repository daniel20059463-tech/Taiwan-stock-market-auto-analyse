from __future__ import annotations

import asyncio
import datetime as dt
import types

import pytest

from auto_trader import AutoTrader
from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow
from retail_flow_strategy import RetailFlowSwingStrategy
from trading import DecisionFactor as TradingDecisionFactor
from trading import DecisionReport as TradingDecisionReport
from trading.decision_reports import DecisionFactor, DecisionReport


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
        self.buy_calls: list[tuple[str, float, int]] = []
        self.sell_calls: list[tuple[str, float]] = []

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
        self.buy_calls.append((symbol, price, shares))

    def on_sell(self, symbol: str, pnl: float) -> None:
        self.sell_calls.append((symbol, pnl))
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
            "dailyTradeCount": len(self.buy_calls),
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


class _FakeDailyReporter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_and_send(self, *, day_payload: dict[str, object]) -> object:
        self.calls.append(day_payload)
        return {"text": "ok"}


class _TrackingRetailFlowSwingStrategy(RetailFlowSwingStrategy):
    def __init__(self) -> None:
        self.classify_calls: list[dict[str, object]] = []

    def classify_watch_state(
        self,
        *,
        flow_score: float,
        above_ma10: bool,
        volume_confirmed: bool,
        recent_runup_pct: float,
        consecutive_trust_days: int = 0,
    ) -> str:
        self.classify_calls.append(
            {
                "flow_score": flow_score,
                "above_ma10": above_ma10,
                "volume_confirmed": volume_confirmed,
                "recent_runup_pct": recent_runup_pct,
                "consecutive_trust_days": consecutive_trust_days,
            }
        )
        return "ready_to_buy"


async def _noop(*args, **kwargs) -> None:
    return None


def test_decision_reports_are_exported_and_serialized() -> None:
    factor = DecisionFactor(kind="support", label="trend", detail="price is rising")
    report = DecisionReport(
        report_id="abc-123",
        symbol="2330",
        ts=1_775_500_400_000,
        decision_type="buy",
        trigger_type="mixed",
        confidence=88,
        final_reason="fast_entry_confirmed",
        summary="example",
        supporting_factors=[factor],
        opposing_factors=[],
        risk_flags=["tight_stop"],
        source_events=[{"source": "price_momentum"}],
        order_result={"status": "executed"},
        bull_case="bull",
        bear_case="bear",
        risk_case="risk",
        bull_argument="bull arg",
        bear_argument="bear arg",
        referee_verdict="verdict",
        debate_winner="bull",
    )

    assert TradingDecisionFactor is DecisionFactor
    assert TradingDecisionReport is DecisionReport

    data = report.to_dict()
    assert data["reportId"] == "abc-123"
    assert data["supportingFactors"] == [
        {"kind": "support", "label": "trend", "detail": "price is rising"}
    ]
    assert data["bullCase"] == "bull"
    assert data["bearCase"] == "bear"
    assert data["riskCase"] == "risk"
    assert data["bullArgument"] == "bull arg"
    assert data["bearArgument"] == "bear arg"
    assert data["refereeVerdict"] == "verdict"
    assert data["debateWinner"] == "bull"


@pytest.mark.asyncio
async def test_manual_buy_and_sell_decision_reports_are_structured() -> None:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=0.42, blocked=False),
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._persist_position_open = types.MethodType(_noop, trader)
    trader._persist_position_close = types.MethodType(_noop, trader)
    trader._last_prices["2330"] = 504.0
    trader._open_prices["2330"] = 500.0
    trader._prev_close_cache["2330"] = 500.0
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.5, trader)

    buy_ts = 1_775_500_400_000
    await trader.execute_manual_trade(symbol="2330", action="BUY", shares=1000, ts_ms=buy_ts)
    await trader.execute_manual_trade(symbol="2330", action="SELL", shares=1000, ts_ms=buy_ts + 60_000)

    snapshot = trader.get_portfolio_snapshot()
    assert len(snapshot["recentTrades"]) == 2
    assert len(snapshot["recentDecisions"]) >= 2

    buy_trade = snapshot["recentTrades"][0]
    sell_trade = snapshot["recentTrades"][1]
    buy_report = buy_trade["decisionReport"]
    sell_report = sell_trade["decisionReport"]

    assert buy_report["decisionType"] == "buy"
    assert buy_report["triggerType"] == "manual"
    assert buy_report["orderResult"]["status"] == "executed"
    assert sell_report["decisionType"] == "sell"
    assert sell_report["orderResult"]["status"] == "executed"
    assert sell_report["finalReason"] == "manual"


@pytest.mark.asyncio
async def test_eod_report_uses_completed_manual_sell_trades() -> None:
    reporter = _FakeDailyReporter()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=0.35, blocked=False),
        daily_reporter=reporter,
        eod_report_delay_seconds=0.01,
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._persist_position_open = types.MethodType(_noop, trader)
    trader._persist_position_close = types.MethodType(_noop, trader)
    trader._last_prices["2330"] = 504.0
    trader._open_prices["2330"] = 500.0
    trader._prev_close_cache["2330"] = 500.0
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.0, trader)

    ts_ms = 1_775_500_400_000
    await trader.execute_manual_trade(symbol="2330", action="BUY", shares=1000, ts_ms=ts_ms)
    await trader.execute_manual_trade(symbol="2330", action="SELL", shares=1000, ts_ms=ts_ms + 1_000)
    await trader._run_eod_report_after_delay(ts_ms + 120_000)

    assert len(reporter.calls) == 1
    assert reporter.calls[0]["tradeCount"] == 1


@pytest.mark.asyncio
async def test_swing_strategy_uses_retail_flow_entry_logic() -> None:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-20",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=1000,
                investment_trust_net_buy=500,
                major_net_buy=800,
            )
        ],
    )
    strategy = _TrackingRetailFlowSwingStrategy()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=0.2, blocked=False),
        strategy_mode="retail_flow_swing",
        retail_flow_strategy=strategy,
        institutional_flow_cache=cache,
    )

    class _FakeExecution:
        async def execute_buy(self, **kwargs) -> None:
            buy_calls.append((kwargs["symbol"], kwargs["price"], kwargs["ts_ms"]))

        async def execute_sell(self, **kwargs) -> None:
            raise AssertionError("unexpected sell")

    buy_calls: list[tuple[str, float, int]] = []
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._execution = _FakeExecution()
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.5, trader)

    base_ts = int(dt.datetime(2026, 4, 21, 9, 1, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp() * 1000)
    for i, price in enumerate([100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0, 103.5, 104.0, 104.5, 105.0]):
        await trader.on_tick(
            {
                "symbol": "2330",
                "price": price,
                "volume": 1000,
                "ts": base_ts + i * 60_000,
                "previousClose": 99.0,
                "open": 99.5,
                "high": price,
                "low": 99.0,
            }
        )

    assert strategy.classify_calls
    assert buy_calls
    assert trader._swing_runtime.watch_states["2330"] == "entered"


@pytest.mark.asyncio
async def test_swing_strategy_only_buys_once_when_state_stays_ready() -> None:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-20",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=1000,
                investment_trust_net_buy=500,
                major_net_buy=800,
            )
        ],
    )

    class _TransitionStrategy(RetailFlowSwingStrategy):
        def __init__(self) -> None:
            self.states = ["watch", "ready_to_buy", "ready_to_buy"]

        def classify_watch_state(self, **kwargs) -> str:
            if self.states:
                return self.states.pop(0)
            return "ready_to_buy"

    strategy = _TransitionStrategy()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=0.2, blocked=False),
        strategy_mode="retail_flow_swing",
        retail_flow_strategy=strategy,
        institutional_flow_cache=cache,
    )

    class _FakeExecution:
        async def execute_buy(self, **kwargs) -> None:
            buy_calls.append((kwargs["symbol"], kwargs["price"], kwargs["ts_ms"]))

        async def execute_sell(self, **kwargs) -> None:
            raise AssertionError("unexpected sell")

    buy_calls: list[tuple[str, float, int]] = []
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._execution = _FakeExecution()
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.5, trader)

    base_ts = int(dt.datetime(2026, 4, 21, 9, 1, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp() * 1000)
    for i, price in enumerate([100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0, 103.5, 104.0, 104.5, 105.0, 105.5]):
        await trader.on_tick(
            {
                "symbol": "2330",
                "price": price,
                "volume": 1000,
                "ts": base_ts + i * 60_000,
                "previousClose": 99.0,
                "open": 99.5,
                "high": price,
                "low": 99.0,
            }
        )

    assert len(buy_calls) == 1
    assert trader._swing_runtime.watch_states["2330"] == "entered"

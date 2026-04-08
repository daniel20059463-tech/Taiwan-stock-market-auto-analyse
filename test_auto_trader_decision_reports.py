from __future__ import annotations

import asyncio
import types

import pytest

from auto_trader import AutoTrader
from trading import DecisionFactor as TradingDecisionFactor
from trading import DecisionReport as TradingDecisionReport
from trading.decision_reports import DecisionFactor, DecisionReport


class _FakeRiskManager:
    def __init__(self) -> None:
        self.daily_pnl = 0.0
        self.rolling_5day_pnl = 0.0
        self.is_halted = False
        self.is_weekly_halted = False
        self.buy_calls: list[tuple[str, float, int]] = []
        self.sell_calls: list[tuple[str, float]] = []

    def can_buy(self, symbol: str, price: float, shares: int, current_positions: int) -> tuple[bool, str]:
        return True, "OK"

    def calc_stop_price(self, price: float, atr: float | None) -> float:
        return round(price * 0.97, 2)

    def calc_target_price(self, price: float, stop_price: float) -> float:
        risk = price - stop_price
        return round(price + risk * 2, 2)

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
async def test_portfolio_snapshot_includes_structured_decision_reports_for_buy_and_sell() -> None:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=0.42, blocked=False),
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_near_day_high = types.MethodType(lambda self, symbol, price, payload: False, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.5, trader)

    buy_ts = 1_775_500_400_000
    payload = {
        "high": 104.0,
        "low": 99.5,
        "open": 100.2,
        "previousClose": 99.0,
        "volume": 45_000,
    }

    await trader._evaluate_buy("2330", 101.0, 2.02, buy_ts, payload)
    await trader._paper_sell("2330", 106.5, "TAKE_PROFIT", 5.45, buy_ts + 60_000)

    snapshot = trader.get_portfolio_snapshot()

    assert len(snapshot["recentTrades"]) == 2
    assert len(snapshot["recentDecisions"]) >= 2

    buy_trade = snapshot["recentTrades"][0]
    sell_trade = snapshot["recentTrades"][1]
    buy_report = buy_trade["decisionReport"]
    sell_report = sell_trade["decisionReport"]

    assert buy_report["decisionType"] == "buy"
    assert buy_report["triggerType"] == "mixed"
    assert buy_report["orderResult"]["status"] == "executed"
    assert any(factor["kind"] == "support" for factor in buy_report["supportingFactors"])
    assert buy_report["confidence"] > 0
    assert "多方觀點" in buy_report["bullCase"]
    assert "空方觀點" in buy_report["bearCase"]
    assert "風控觀點" in buy_report["riskCase"]
    assert "多方論點" in buy_report["bullArgument"]
    assert "空方論點" in buy_report["bearArgument"]
    assert "裁決結論" in buy_report["refereeVerdict"]
    assert buy_report["debateWinner"] in {"bull", "bear", "tie"}

    assert sell_report["decisionType"] == "sell"
    assert sell_report["finalReason"] == "take_profit"
    assert sell_report["orderResult"]["status"] == "executed"
    assert any(flag == "target_hit" for flag in sell_report["riskFlags"])
    assert "多方觀點" in sell_report["bullCase"]
    assert "空方觀點" in sell_report["bearCase"]
    assert "風控觀點" in sell_report["riskCase"]
    assert "多方論點" in sell_report["bullArgument"]
    assert "空方論點" in sell_report["bearArgument"]
    assert "裁決結論" in sell_report["refereeVerdict"]


@pytest.mark.asyncio
async def test_buy_skip_is_recorded_as_replayable_decision_report() -> None:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=-0.72, blocked=True),
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_near_day_high = types.MethodType(lambda self, symbol, price, payload: False, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.2, trader)

    await trader._evaluate_buy(
        "2454",
        1288.0,
        2.6,
        1_775_500_700_000,
        {
            "high": 1292.0,
            "low": 1258.0,
            "open": 1261.0,
            "previousClose": 1255.0,
            "volume": 80_000,
        },
    )

    snapshot = trader.get_portfolio_snapshot()

    assert snapshot["recentTrades"] == []
    assert snapshot["recentDecisions"], "expected skip decision to be replayable"

    latest = snapshot["recentDecisions"][-1]
    assert latest["decisionType"] == "skip"
    assert latest["finalReason"] == "sentiment_blocked"
    assert latest["orderResult"]["status"] == "skipped"
    assert any(factor["kind"] == "oppose" for factor in latest["opposingFactors"])
    assert "多方觀點" in latest["bullCase"]
    assert "空方觀點" in latest["bearCase"]
    assert "風控觀點" in latest["riskCase"]
    assert "多方論點" in latest["bullArgument"]
    assert "空方論點" in latest["bearArgument"]
    assert "裁決結論" in latest["refereeVerdict"]


@pytest.mark.asyncio
async def test_auto_trader_triggers_delayed_eod_report_once_positions_closed() -> None:
    reporter = _FakeDailyReporter()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=0.35, blocked=False),
        daily_reporter=reporter,
        eod_report_delay_seconds=0.01,
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_near_day_high = types.MethodType(lambda self, symbol, price, payload: False, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.0, trader)

    ts_ms = 1_775_500_400_000
    payload = {
        "high": 104.0,
        "low": 99.5,
        "open": 100.2,
        "previousClose": 99.0,
        "volume": 45_000,
    }

    await trader._evaluate_buy("2330", 101.0, 2.02, ts_ms, payload)
    await trader._close_all_eod(ts_ms + 1_000)
    await asyncio.sleep(0.05)

    assert len(reporter.calls) == 1
    assert reporter.calls[0]["tradeCount"] >= 1


@pytest.mark.asyncio
async def test_eod_report_counts_cover_trades_for_short_only_day() -> None:
    reporter = _FakeDailyReporter()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=-0.55, blocked=False),
        daily_reporter=reporter,
        eod_report_delay_seconds=0.01,
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.2, trader)

    ts_ms = 1_775_500_700_000
    payload = {
        "high": 1312.0,
        "low": 1280.0,
        "open": 1308.0,
        "previousClose": 1315.0,
        "volume": 80_000,
    }

    await trader._evaluate_short("2454", 1288.0, -2.1, ts_ms, payload)
    await trader._paper_cover("2454", 1200.0, "TAKE_PROFIT", 6.83, ts_ms + 60_000)
    await trader._run_eod_report_after_delay(ts_ms + 120_000)

    assert len(reporter.calls) == 1
    assert reporter.calls[0]["tradeCount"] == 1
    assert reporter.calls[0]["winRate"] == 100.0


@pytest.mark.asyncio
async def test_short_and_cover_decision_reports_have_correct_types() -> None:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=-0.55, blocked=False),
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.2, trader)

    ts_ms = 1_775_500_700_000
    payload = {
        "high": 1312.0,
        "low": 1280.0,
        "open": 1308.0,
        "previousClose": 1315.0,
        "volume": 80_000,
    }

    await trader._evaluate_short("2454", 1288.0, -2.1, ts_ms, payload)
    await trader._paper_cover("2454", 1200.0, "TAKE_PROFIT", 6.83, ts_ms + 60_000)

    snapshot = trader.get_portfolio_snapshot()

    short_trade = snapshot["recentTrades"][0]
    cover_trade = snapshot["recentTrades"][1]
    short_report = short_trade["decisionReport"]
    cover_report = cover_trade["decisionReport"]

    assert short_trade["action"] == "SHORT"
    assert short_report["decisionType"] == "short"
    assert short_report["orderResult"]["status"] == "executed"
    assert "空方觀點" in short_report["bearCase"]

    assert cover_trade["action"] == "COVER"
    assert cover_report["decisionType"] == "cover"
    assert cover_report["orderResult"]["status"] == "executed"

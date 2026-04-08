"""Tests for DispositionFilter (處置股/全額交割預警過濾器)."""
from __future__ import annotations

import json
import os
import tempfile
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from disposition_filter import DispositionFilter
from auto_trader import AutoTrader


# ── DispositionFilter unit tests ───────────────────────────────────────────────


def test_is_blocked_with_loaded_symbols() -> None:
    """載入後 is_blocked 正確辨識處置股。"""
    df = DispositionFilter(symbols={"1234", "5678"})
    assert df.is_blocked("1234") is True
    assert df.is_blocked("5678") is True
    assert df.is_blocked("2330") is False


def test_is_blocked_empty_by_default() -> None:
    """未載入時所有代號都不被阻擋。"""
    df = DispositionFilter()
    assert df.is_blocked("1234") is False
    assert df.count == 0


def test_add_and_remove() -> None:
    """手動 add/remove 正常運作。"""
    df = DispositionFilter()
    df.add("1234")
    assert df.is_blocked("1234") is True
    df.remove("1234")
    assert df.is_blocked("1234") is False


def test_case_insensitive_matching() -> None:
    """代號比對不分大小寫。"""
    df = DispositionFilter(symbols={"abc"})
    assert df.is_blocked("ABC") is True
    assert df.is_blocked("abc") is True


def test_load_from_json_file() -> None:
    """從 JSON 檔案載入處置股清單。"""
    data = {
        "updated_at": "2026-04-06",
        "symbols": ["1234", "5678", "9999"],
        "notes": "test",
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f)
        filepath = f.name

    try:
        df = DispositionFilter(filepath=filepath)
        count = df.load()
        assert count == 3
        assert df.is_blocked("1234") is True
        assert df.is_blocked("9999") is True
        assert df.updated_at == "2026-04-06"
    finally:
        os.unlink(filepath)


def test_load_returns_zero_when_file_missing() -> None:
    """檔案不存在時靜默回傳 0。"""
    df = DispositionFilter(filepath="/nonexistent/path.json")
    count = df.load()
    assert count == 0
    assert df.is_blocked("1234") is False


def test_snapshot_returns_sorted_symbols() -> None:
    """snapshot() 回傳排序後的代號清單。"""
    df = DispositionFilter(symbols={"5678", "1234"})
    snap = df.snapshot()
    assert snap["count"] == 2
    assert snap["symbols"] == ["1234", "5678"]


# ── AutoTrader integration with disposition filter ─────────────────────────────

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


_TS = 1_775_500_000_000


@pytest.mark.asyncio
async def test_evaluate_buy_blocked_by_disposition_filter() -> None:
    """處置股不應被允許買入。"""
    df = DispositionFilter(symbols={"2330"})
    trader = _make_trader(disposition_filter=df)

    await trader._evaluate_buy(
        "2330", 920.0, 2.5, _TS,
        {"high": 930.0, "low": 910.0, "open": 915.0, "previousClose": 897.0, "volume": 100_000},
    )

    # Should NOT have opened a position
    assert "2330" not in trader._positions

    # Should have recorded a skip decision
    skips = [d for d in trader._decision_history if d.final_reason == "disposition_blocked"]
    assert len(skips) == 1


@pytest.mark.asyncio
async def test_evaluate_buy_allowed_without_disposition_filter() -> None:
    """無處置股過濾器時正常買入。"""
    trader = _make_trader(disposition_filter=None)

    await trader._evaluate_buy(
        "2330", 920.0, 2.5, _TS,
        {"high": 930.0, "low": 910.0, "open": 915.0, "previousClose": 897.0, "volume": 100_000},
    )

    # Should have opened a position
    assert "2330" in trader._positions


@pytest.mark.asyncio
async def test_evaluate_buy_allowed_for_non_disposition_stock() -> None:
    """非處置股正常買入。"""
    df = DispositionFilter(symbols={"9999"})
    trader = _make_trader(disposition_filter=df)

    await trader._evaluate_buy(
        "2330", 920.0, 2.5, _TS,
        {"high": 930.0, "low": 910.0, "open": 915.0, "previousClose": 897.0, "volume": 100_000},
    )

    assert "2330" in trader._positions


@pytest.mark.asyncio
async def test_evaluate_short_blocked_by_disposition_filter() -> None:
    """處置股不應被允許放空。"""
    df = DispositionFilter(symbols={"2330"})
    trader = _make_trader(disposition_filter=df)
    trader._sentiment = type("S", (), {"get_score": lambda self, s: -0.5})()

    await trader._evaluate_short(
        "2330", 900.0, -2.0, _TS,
        {"high": 910.0, "low": 895.0, "open": 908.0, "previousClose": 918.0, "volume": 100_000},
    )

    assert "2330" not in trader._positions

    skips = [d for d in trader._decision_history if d.final_reason == "disposition_blocked"]
    assert len(skips) == 1

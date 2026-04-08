"""Tests for position persistence (open → DB write, close → DB delete, restart → restore)."""
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
        db_session_factory=object(),  # truthy so _db is set
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, sym: True, trader)
    trader._calc_atr = types.MethodType(lambda self, sym: None, trader)
    return trader


_BUY_SYMBOL = "2330"
_BUY_PRICE = 920.0
_BUY_CHANGE_PCT = 2.5
_BUY_TS = 1_775_500_000_000
_BUY_PAYLOAD = {
    "high": 930.0,
    "low": 910.0,
    "open": 915.0,
    "previousClose": 897.0,
    "volume": 100_000,
}

# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_position_calls_upsert() -> None:
    """開倉後應呼叫 upsert_paper_position 寫入 DB。"""
    trader = _make_trader()
    upsert_mock = AsyncMock()

    # Functions are imported inside the method body, so patch at the models module level
    with patch("models.upsert_paper_position", upsert_mock), \
         patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)

        await trader._evaluate_buy(_BUY_SYMBOL, _BUY_PRICE, _BUY_CHANGE_PCT, _BUY_TS, _BUY_PAYLOAD)

    assert _BUY_SYMBOL in trader._positions
    upsert_mock.assert_called_once()
    call_kwargs = upsert_mock.call_args.kwargs
    assert call_kwargs["symbol"] == _BUY_SYMBOL
    assert call_kwargs["side"] == "long"
    assert call_kwargs["entry_price"] == round(_BUY_PRICE * 1.0005, 2)


@pytest.mark.asyncio
async def test_close_position_calls_delete() -> None:
    """平倉後應呼叫 delete_paper_position 從 DB 刪除。"""
    trader = _make_trader()
    upsert_mock = AsyncMock()
    delete_mock = AsyncMock()

    with patch("models.upsert_paper_position", upsert_mock), \
         patch("models.delete_paper_position", delete_mock), \
         patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)

        await trader._evaluate_buy(_BUY_SYMBOL, _BUY_PRICE, _BUY_CHANGE_PCT, _BUY_TS, _BUY_PAYLOAD)
        assert _BUY_SYMBOL in trader._positions

        # trigger stop-loss exit
        stop_price = trader._positions[_BUY_SYMBOL].stop_price
        exit_price = stop_price - 5.0
        await trader._check_exit(_BUY_SYMBOL, exit_price, _BUY_TS + 60_000)

    assert _BUY_SYMBOL not in trader._positions
    delete_mock.assert_called_once()
    call_kwargs = delete_mock.call_args.kwargs
    assert call_kwargs["symbol"] == _BUY_SYMBOL


@pytest.mark.asyncio
async def test_restore_positions_injects_into_position_book() -> None:
    """restore_positions 應從 DB 讀取並注入 _positions。"""
    trader = _make_trader()
    fake_rows = [
        {
            "symbol": "2330",
            "side": "long",
            "entry_price": 920.0,
            "shares": 1000,
            "entry_ts": _BUY_TS,
            "entry_change_pct": 2.5,
            "stop_price": 892.0,
            "target_price": 976.0,
            "peak_price": 920.0,
            "trail_stop_price": 892.0,
            "entry_atr": None,
        }
    ]

    with patch("models.load_today_positions", AsyncMock(return_value=fake_rows)), \
         patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)

        count = await trader.restore_positions("20260406")

    assert count == 1
    assert "2330" in trader._positions
    pos = trader._positions["2330"]
    assert pos.side == "long"
    assert pos.entry_price == 920.0
    assert pos.shares == 1000
    assert pos.stop_price == 892.0


@pytest.mark.asyncio
async def test_restore_positions_returns_zero_when_db_is_none() -> None:
    """若 db_session_factory 為 None，restore_positions 應靜默跳過並回傳 0。"""
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(),
        db_session_factory=None,
    )
    count = await trader.restore_positions("20260406")
    assert count == 0
    assert len(trader._positions) == 0


@pytest.mark.asyncio
async def test_restore_positions_filters_by_trade_date() -> None:
    """load_today_positions 應被呼叫時帶入正確的 trade_date。"""
    trader = _make_trader()
    load_mock = AsyncMock(return_value=[])

    with patch("models.load_today_positions", load_mock), \
         patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)

        await trader.restore_positions("20260406")

    load_mock.assert_called_once()
    assert load_mock.call_args.kwargs.get("trade_date") == "20260406"


@pytest.mark.asyncio
async def test_persist_position_skipped_when_db_is_none() -> None:
    """若 _db 為 None，_persist_position_open 應靜默跳過不拋出例外。"""
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(),
        db_session_factory=None,
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    # Should complete without error even with no DB
    await trader._persist_position_open("2330")

"""Tests for position persistence."""
from __future__ import annotations

import json
import logging
import types
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _prime_quote(trader: AutoTrader, symbol: str, price: float) -> None:
    trader._last_prices[symbol] = price
    trader._open_prices[symbol] = price
    trader._prev_close_cache[symbol] = price


def _make_trader(*, local_positions_path: str | None = None, db_enabled: bool = True) -> AutoTrader:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(),
        db_session_factory=object() if db_enabled else None,
        local_positions_path=local_positions_path,
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._calc_atr = types.MethodType(lambda self, sym: None, trader)
    _prime_quote(trader, "2330", 920.0)
    return trader


_BUY_SYMBOL = "2330"
_BUY_PRICE = 920.0
_BUY_TS = 1_775_500_000_000
_BUY_TRADE_DATE = "20260407"


@pytest.mark.asyncio
async def test_open_position_calls_upsert() -> None:
    trader = _make_trader()
    upsert_mock = AsyncMock()

    with patch("models.upsert_paper_position", upsert_mock), patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)

        await trader.execute_manual_trade(symbol=_BUY_SYMBOL, action="BUY", shares=1000, ts_ms=_BUY_TS)

    assert _BUY_SYMBOL in trader._positions
    upsert_mock.assert_called_once()
    call_kwargs = upsert_mock.call_args.kwargs
    assert call_kwargs["symbol"] == _BUY_SYMBOL
    assert call_kwargs["side"] == "long"
    # No daily value data in mock → falls to 20 bps tier (lowest liquidity tier)
    assert call_kwargs["entry_price"] == round(_BUY_PRICE * (1 + 20 / 10000), 2)
    assert "session_id" not in call_kwargs


@pytest.mark.asyncio
async def test_close_position_calls_delete() -> None:
    trader = _make_trader()
    upsert_mock = AsyncMock()
    delete_mock = AsyncMock()

    with patch("models.upsert_paper_position", upsert_mock), patch("models.delete_paper_position", delete_mock), patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)

        await trader.execute_manual_trade(symbol=_BUY_SYMBOL, action="BUY", shares=1000, ts_ms=_BUY_TS)
        await trader.execute_manual_trade(symbol=_BUY_SYMBOL, action="SELL", shares=1000, ts_ms=_BUY_TS + 60_000)

    assert _BUY_SYMBOL not in trader._positions
    delete_mock.assert_called_once()
    assert delete_mock.call_args.kwargs["symbol"] == _BUY_SYMBOL


@pytest.mark.asyncio
async def test_restore_positions_injects_into_position_book() -> None:
    trader = _make_trader()
    fake_rows = [
        {
            "symbol": "2330",
            "side": "long",
            "entry_price": 920.0,
            "shares": 1000,
            "entry_ts": _BUY_TS,
            "entry_change_pct": 0.0,
            "stop_price": 892.0,
            "target_price": 976.0,
            "peak_price": 920.0,
            "trail_stop_price": 892.0,
            "entry_atr": None,
        }
    ]

    with patch("models.load_today_positions", AsyncMock(return_value=fake_rows)), patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)
        count = await trader.restore_positions("20260406")

    assert count == 1
    assert "2330" in trader._positions
    assert trader._positions["2330"].shares == 1000


@pytest.mark.asyncio
async def test_restore_positions_returns_zero_when_db_is_none() -> None:
    trader = _make_trader(db_enabled=False)
    count = await trader.restore_positions("20260406")
    assert count == 0
    assert trader._positions == {}


@pytest.mark.asyncio
async def test_restore_positions_filters_by_trade_date() -> None:
    trader = _make_trader()
    load_mock = AsyncMock(return_value=[])

    with patch("models.load_today_positions", load_mock), patch("models.get_session") as gs_mock:
        gs_mock.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        gs_mock.return_value.__aexit__ = AsyncMock(return_value=False)
        await trader.restore_positions("20260406")

    assert load_mock.call_args.kwargs["trade_date"] == "20260406"


@pytest.mark.asyncio
async def test_persist_position_skipped_when_db_is_none() -> None:
    trader = _make_trader(db_enabled=False)
    await trader._persist_position_open("2330")


@pytest.mark.asyncio
async def test_trade_persistence_is_disabled_after_connection_failure(caplog) -> None:
    trader = _make_trader()
    trader._persist_trade = types.MethodType(AutoTrader._persist_trade, trader)
    record = types.SimpleNamespace(
        symbol="2330",
        action="BUY",
        price=100.0,
        shares=100,
        reason="MANUAL",
        pnl=0.0,
        gross_pnl=0.0,
        ts=1_775_500_000_000,
        stop_price=97.0,
        target_price=106.0,
    )

    @asynccontextmanager
    async def _broken_get_session():
        raise OSError(1225, "connection refused")
        yield  # pragma: no cover

    with patch("models.get_session", _broken_get_session):
        with caplog.at_level(logging.WARNING, logger="auto_trader"):
            await trader._persist_trade(record)
            await trader._persist_trade(record)

    warning_messages = [message for message in caplog.messages if "Trade persistence failed" in message]
    assert len(warning_messages) == 1
    assert trader._db is None


@pytest.mark.asyncio
async def test_open_position_falls_back_to_local_snapshot_when_db_connection_fails(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "paper_positions.json"
    trader = _make_trader(local_positions_path=str(snapshot_path))
    trader._persist_trade = types.MethodType(AutoTrader._persist_trade, trader)

    @asynccontextmanager
    async def _broken_get_session():
        raise OSError(1225, "connection refused")
        yield  # pragma: no cover

    with patch("models.get_session", _broken_get_session):
        await trader.execute_manual_trade(symbol=_BUY_SYMBOL, action="BUY", shares=1000, ts_ms=_BUY_TS)

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["trade_date"] == _BUY_TRADE_DATE
    assert payload["positions"]["2330"]["side"] == "long"
    assert trader._db is None


@pytest.mark.asyncio
async def test_restore_positions_reads_local_snapshot_when_db_is_unavailable(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "paper_positions.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "trade_date": _BUY_TRADE_DATE,
                "positions": {
                    "2330": {
                        "symbol": "2330",
                        "side": "long",
                        "entry_price": 920.0,
                        "shares": 1000,
                        "entry_ts": _BUY_TS,
                        "entry_change_pct": 0.0,
                        "stop_price": 892.0,
                        "target_price": 976.0,
                        "peak_price": 920.0,
                        "trail_stop_price": 892.0,
                        "entry_atr": None,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    trader = _make_trader(local_positions_path=str(snapshot_path))

    @asynccontextmanager
    async def _broken_get_session():
        raise OSError(1225, "connection refused")
        yield  # pragma: no cover

    with patch("models.get_session", _broken_get_session):
        count = await trader.restore_positions(_BUY_TRADE_DATE)

    assert count == 1
    assert trader._positions["2330"].shares == 1000

from __future__ import annotations

import datetime
import types

import pytest

from auto_trader import AutoTrader
from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow
from retail_flow_strategy import RetailFlowSwingStrategy


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
            "date": "2026-04-20",
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


def _build_cache() -> InstitutionalFlowCache:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-20",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="台積電",
                foreign_net_buy=1000,
                investment_trust_net_buy=500,
                major_net_buy=800,
            ),
            InstitutionalFlowRow(
                symbol="2317",
                name="鴻海",
                foreign_net_buy=500,
                investment_trust_net_buy=300,
                major_net_buy=200,
            ),
        ],
    )
    cache.store(
        trade_date="2026-04-19",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="台積電",
                foreign_net_buy=800,
                investment_trust_net_buy=200,
                major_net_buy=100,
            ),
            InstitutionalFlowRow(
                symbol="2317",
                name="鴻海",
                foreign_net_buy=300,
                investment_trust_net_buy=100,
                major_net_buy=50,
            ),
        ],
    )
    return cache


@pytest.mark.asyncio
async def test_retail_flow_observability_exposes_watch_state_and_last_non_entry_reason() -> None:
    cache = _build_cache()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        strategy_mode="retail_flow_swing",
        retail_flow_strategy=RetailFlowSwingStrategy(),
        institutional_flow_cache=cache,
    )

    async def _noop(*args, **kwargs) -> None:
        return None

    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: False, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.5, trader)

    ts_ms = int(
        datetime.datetime(
            2026,
            4,
            20,
            9,
            1,
            tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
        ).timestamp()
        * 1000
    )
    await trader.on_tick(
        {
            "symbol": "2330",
            "price": 101.0,
            "volume": 1000,
            "ts": ts_ms,
            "previousClose": 99.0,
            "open": 99.5,
            "high": 101.0,
            "low": 99.0,
        }
    )

    assert trader.get_retail_flow_watch_state("2330") == "watch"
    assert trader.get_retail_flow_last_non_entry_reason("2330") == "watch_state_watch"


def test_retail_flow_observability_exports_candidates_and_watchlist() -> None:
    cache = _build_cache()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        strategy_mode="retail_flow_swing",
        retail_flow_strategy=RetailFlowSwingStrategy(),
        institutional_flow_cache=cache,
    )
    trader._current_date = "2026-04-21"

    trader._build_preopen_watchlist()

    assert trader.get_retail_flow_candidates() == ["2317", "2330"]
    assert trader.get_retail_flow_watchlist() == ["2317", "2330"]


def test_portfolio_snapshot_includes_retail_flow_observability_block() -> None:
    cache = _build_cache()
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        strategy_mode="retail_flow_swing",
        retail_flow_strategy=RetailFlowSwingStrategy(),
        institutional_flow_cache=cache,
    )
    trader._current_date = "2026-04-21"
    trader._swing_runtime.watch_states["2330"] = "ready_to_buy"
    trader._build_preopen_watchlist()
    trader._retail_flow_non_entry_reasons["2330"] = "duplicate_ready_state"

    snapshot = trader.get_portfolio_snapshot()

    assert snapshot["retailFlow"]["watchStates"]["2330"] == "ready_to_buy"
    assert snapshot["retailFlow"]["lastNonEntryReasons"]["2330"] == "duplicate_ready_state"
    assert snapshot["retailFlow"]["candidates"] == ["2317", "2330"]
    assert snapshot["retailFlow"]["watchlist"] == ["2317", "2330"]

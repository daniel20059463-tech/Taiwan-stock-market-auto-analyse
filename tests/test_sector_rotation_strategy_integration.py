from __future__ import annotations

import datetime as dt
import types

import pytest

from auto_trader import AutoTrader
from daily_price_cache import DailyBar, DailyPriceCache
from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow
from retail_flow_strategy import RetailFlowSwingStrategy
from sector_rotation_signal_cache import SectorSignalCache, SectorSignalRecord
from trading import PaperPosition


class _FakeRiskManager:
    account_capital = 1_000_000.0

    def can_buy(self, symbol: str, price: float, shares: int, current_positions: int) -> tuple[bool, str]:
        return True, "OK"

    def calc_stop_price(self, price: float, atr: float | None) -> float:
        return round(price * 0.97, 2)

    def calc_target_price(self, price: float, stop_price: float) -> float:
        risk = price - stop_price
        return round(price + risk * 2, 2)

    def calc_position_shares(self, price: float, stop_price: float, lot_size: int = 1000) -> int:
        return lot_size


def _seed_bars(cache: DailyPriceCache, symbol: str, *, start: float, step: float, volume: int = 2_000_000) -> None:
    for index in range(61):
        close = start + (step * index)
        cache.add_bar(
            symbol,
            DailyBar(
                date=f"2026-02-{index + 1:02d}",
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=volume,
            ),
        )


def _build_daily_cache() -> DailyPriceCache:
    cache = DailyPriceCache()
    _seed_bars(cache, "TAIEX", start=100.0, step=0.2)
    _seed_bars(cache, "2330", start=100.0, step=0.5)
    return cache


def _build_flow_cache() -> InstitutionalFlowCache:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-27",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=1_000,
                investment_trust_net_buy=800,
                major_net_buy=600,
                avg_daily_volume_20d=10_000,
            )
        ],
    )
    cache.store(
        trade_date="2026-04-26",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=900,
                investment_trust_net_buy=700,
                major_net_buy=500,
                avg_daily_volume_20d=10_000,
            )
        ],
    )
    return cache


def _build_sector_cache(state: str) -> SectorSignalCache:
    cache = SectorSignalCache()
    cache.store(
        trade_date="2026-04-27",
        sectors={
            "24 半導體業": SectorSignalRecord(
                sector="24 半導體業",
                state=state,
                sector_flow_score=0.8,
                chip_score=0.8,
                relative_strength_20=2.0,
                relative_strength_60=1.0,
                breadth_positive_return_pct=0.7,
                breadth_above_ma10_pct=0.7,
                breadth_positive_flow_pct=0.7,
                top_symbols=["2330"],
            )
        },
    )
    return cache


def _build_trader_with_sector_state(state: str) -> AutoTrader:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        strategy_mode="retail_flow_swing",
        retail_flow_strategy=RetailFlowSwingStrategy(),
        institutional_flow_cache=_build_flow_cache(),
        daily_price_cache=_build_daily_cache(),
    )
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_above_ma10 = types.MethodType(lambda self, symbol, price: True, trader)
    trader._daily_atr = types.MethodType(lambda self, symbol: 1.5, trader)
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-27", trader)
    trader._sector_signal_cache = _build_sector_cache(state)
    trader._symbol_sectors["2330"] = "24 半導體業"
    trader._retail_flow_strategy = types.SimpleNamespace(
        compute_flow_score=lambda flow_row: 0.9,
        classify_watch_state=lambda **kwargs: "ready_to_buy",
        should_enter_position=lambda *, watch_state: True,
    )
    trader._swing_runtime = types.SimpleNamespace(
        classify_entry_state=lambda **kwargs: "ready_to_buy",
        should_trigger_entry=lambda symbol, watch_state: True,
        mark_entered=lambda symbol: None,
        watch_states={},
    )
    return trader


@pytest.mark.asyncio
async def test_active_sector_allows_retail_flow_entry() -> None:
    trader = _build_trader_with_sector_state("active")

    class _FakeExecution:
        def __init__(self) -> None:
            self.buy_calls: list[dict[str, object]] = []

        async def execute_buy(self, **kwargs) -> None:
            self.buy_calls.append(kwargs)

    fake_execution = _FakeExecution()
    trader._execution = fake_execution

    await trader._evaluate_retail_flow_entry(
        symbol="2330",
        price=100.0,
        change_pct=1.0,
        ts_ms=int(dt.datetime(2026, 4, 28, 9, 5, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp() * 1000),
        payload={"symbol": "2330", "sector": "24 半導體業"},
    )

    assert len(fake_execution.buy_calls) == 1


@pytest.mark.asyncio
async def test_watch_sector_blocks_retail_flow_entry() -> None:
    trader = _build_trader_with_sector_state("watch")

    class _FakeExecution:
        def __init__(self) -> None:
            self.buy_calls: list[dict[str, object]] = []

        async def execute_buy(self, **kwargs) -> None:
            self.buy_calls.append(kwargs)

    fake_execution = _FakeExecution()
    trader._execution = fake_execution

    await trader._evaluate_retail_flow_entry(
        symbol="2330",
        price=100.0,
        change_pct=1.0,
        ts_ms=int(dt.datetime(2026, 4, 28, 9, 5, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp() * 1000),
        payload={"symbol": "2330", "sector": "24 半導體業"},
    )

    assert fake_execution.buy_calls == []
    assert trader.get_retail_flow_last_non_entry_reason("2330") == "sector_state_watch"


@pytest.mark.asyncio
async def test_exit_sector_forces_retail_flow_exit() -> None:
    trader = _build_trader_with_sector_state("exit")
    trader._book.positions["2330"] = PaperPosition(
        symbol="2330",
        side="long",
        entry_price=100.0,
        shares=1_000,
        entry_ts=int(dt.datetime(2026, 4, 24, 9, 5, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp() * 1000),
        entry_change_pct=1.0,
        stop_price=97.0,
        target_price=106.0,
        entry_atr=1.5,
        peak_price=108.0,
        trail_stop_price=101.0,
    )

    class _FakeExecution:
        def __init__(self) -> None:
            self.sell_calls: list[dict[str, object]] = []

        async def execute_sell(self, **kwargs) -> None:
            self.sell_calls.append(kwargs)

    fake_execution = _FakeExecution()
    trader._execution = fake_execution

    await trader._check_retail_flow_exit(
        symbol="2330",
        price=108.0,
        ts_ms=int(dt.datetime(2026, 4, 28, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp() * 1000),
    )

    assert len(fake_execution.sell_calls) == 1
    assert fake_execution.sell_calls[0]["reason"] == "SECTOR_EXIT"

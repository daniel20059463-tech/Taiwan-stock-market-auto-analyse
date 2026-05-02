from __future__ import annotations

import datetime as dt
import types

import pytest

from auto_trader import AutoTrader
from daily_price_cache import DailyBar, DailyPriceCache
from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow
from retail_flow_strategy import RetailFlowSwingStrategy


class _FakeRiskManager:
    def can_buy(self, symbol: str, price: float, shares: int, current_positions: int) -> tuple[bool, str]:
        return True, "OK"

    def calc_stop_price(self, price: float, atr: float | None) -> float:
        return round(price * 0.97, 2)

    def calc_target_price(self, price: float, stop_price: float) -> float:
        risk = price - stop_price
        return round(price + risk * 2, 2)

    def calc_position_shares(self, price: float, stop_price: float, lot_size: int = 1000) -> int:
        return lot_size


def _seed_bars(cache: DailyPriceCache, symbol: str, closes: list[float]) -> None:
    for index, close in enumerate(closes, start=1):
        cache.add_bar(
            symbol,
            DailyBar(
                date=f"2026-02-{index:02d}",
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=2_000_000,
            ),
        )


def _build_daily_cache() -> DailyPriceCache:
    cache = DailyPriceCache()
    market = [100.0 + i * 0.2 for i in range(61)]
    strong = [100.0 + i * 0.5 for i in range(61)]
    weak = [100.0 + i * 0.05 for i in range(61)]
    _seed_bars(cache, "TAIEX", market)
    _seed_bars(cache, "2330", strong)
    _seed_bars(cache, "1101", weak)
    return cache


def test_relative_strength_requires_stock_to_outperform_market_on_20_and_60_day_windows() -> None:
    trader = object.__new__(AutoTrader)
    trader._daily_price_cache = _build_daily_cache()
    trader._prev_trade_date = lambda: "2026-02-61"

    assert trader._passes_relative_strength_filter("2330") is True
    assert trader._passes_relative_strength_filter("1101") is False


@pytest.mark.asyncio
async def test_retail_flow_strategy_sets_non_entry_reason_when_relative_strength_is_weak() -> None:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-20",
        rows=[
            InstitutionalFlowRow(
                symbol="1101",
                name="Cement",
                foreign_net_buy=1000,
                investment_trust_net_buy=800,
                major_net_buy=600,
            )
        ],
    )
    cache.store(
        trade_date="2026-04-19",
        rows=[
            InstitutionalFlowRow(
                symbol="1101",
                name="Cement",
                foreign_net_buy=900,
                investment_trust_net_buy=700,
                major_net_buy=500,
            )
        ],
    )
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        strategy_mode="retail_flow_swing",
        retail_flow_strategy=RetailFlowSwingStrategy(),
        institutional_flow_cache=cache,
        daily_price_cache=_build_daily_cache(),
    )
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_above_ma10 = types.MethodType(lambda self, symbol, price: True, trader)
    trader._daily_atr = types.MethodType(lambda self, symbol: 1.5, trader)
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-20", trader)
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

    class _FakeExecution:
        def __init__(self) -> None:
            self.buy_calls: list[dict[str, object]] = []

        async def execute_buy(self, **kwargs) -> None:
            self.buy_calls.append(kwargs)

    fake_execution = _FakeExecution()
    trader._execution = fake_execution

    await trader._evaluate_retail_flow_entry(
        symbol="1101",
        price=100.0,
        change_pct=1.0,
        ts_ms=int(dt.datetime(2026, 4, 21, 9, 5, tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp() * 1000),
        payload={"symbol": "1101", "sector": "01 水泥工業"},
    )

    assert fake_execution.buy_calls == []
    assert trader.get_retail_flow_last_non_entry_reason("1101") == "relative_strength_weak"

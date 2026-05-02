from __future__ import annotations

import datetime
import types

import pytest

from auto_trader import AutoTrader
from daily_price_cache import DailyBar, DailyPriceCache
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


def _build_daily_cache(*, close: float, volume: int, days: int = 20) -> DailyPriceCache:
    cache = DailyPriceCache()
    for offset in range(days):
        day = 1 + offset
        cache.add_bar(
            "2330",
            DailyBar(
                date=f"2026-04-{day:02d}",
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=volume,
            ),
        )
        cache.add_bar(
            "2882",
            DailyBar(
                date=f"2026-04-{day:02d}",
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=volume,
            ),
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
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-20", trader)

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
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-20", trader)

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
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-20", trader)
    trader._swing_runtime.watch_states["2330"] = "ready_to_buy"
    trader._build_preopen_watchlist()
    trader._retail_flow_non_entry_reasons["2330"] = "duplicate_ready_state"

    snapshot = trader.get_portfolio_snapshot()

    assert snapshot["retailFlow"]["watchStates"]["2330"] == "ready_to_buy"
    assert snapshot["retailFlow"]["lastNonEntryReasons"]["2330"] == "duplicate_ready_state"
    assert snapshot["retailFlow"]["candidates"] == ["2317", "2330"]
    assert snapshot["retailFlow"]["watchlist"] == ["2317", "2330"]


@pytest.mark.asyncio
async def test_retail_flow_strategy_skips_financial_sector_symbols() -> None:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-20",
        rows=[
            InstitutionalFlowRow(
                symbol="2882",
                name="國泰金",
                foreign_net_buy=1500,
                investment_trust_net_buy=600,
                major_net_buy=900,
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
    )

    class _FakeExecution:
        def __init__(self) -> None:
            self.buy_calls: list[dict[str, object]] = []

        async def execute_buy(self, **kwargs) -> None:
            self.buy_calls.append(kwargs)

    fake_execution = _FakeExecution()
    trader._execution = fake_execution
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_above_ma10 = types.MethodType(lambda self, symbol, price: True, trader)
    trader._daily_atr = types.MethodType(lambda self, symbol: 1.5, trader)
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-20", trader)
    trader._symbol_sectors["2882"] = "金融保險業"
    trader._retail_flow_strategy = types.SimpleNamespace(
        compute_flow_score=lambda flow_row: 90.0,
        classify_watch_state=lambda **kwargs: "ready_to_buy",
        should_enter_position=lambda *, watch_state: True,
    )
    trader._swing_runtime = types.SimpleNamespace(
        classify_entry_state=lambda **kwargs: "ready_to_buy",
        should_trigger_entry=lambda symbol, watch_state: True,
        mark_entered=lambda symbol: None,
    )

    await trader._evaluate_retail_flow_entry(
        symbol="2882",
        price=55.0,
        change_pct=1.2,
        ts_ms=int(datetime.datetime(2026, 4, 21, 9, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp() * 1000),
        payload={"symbol": "2882", "sector": "金融保險業"},
    )

    assert fake_execution.buy_calls == []
    assert trader.get_retail_flow_last_non_entry_reason("2882") == "financial_sector"


@pytest.mark.asyncio
async def test_retail_flow_strategy_skips_low_liquidity_symbols() -> None:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-20",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=1500,
                investment_trust_net_buy=800,
                major_net_buy=900,
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
        daily_price_cache=_build_daily_cache(close=100.0, volume=10_000),
    )

    class _FakeExecution:
        def __init__(self) -> None:
            self.buy_calls: list[dict[str, object]] = []

        async def execute_buy(self, **kwargs) -> None:
            self.buy_calls.append(kwargs)

    fake_execution = _FakeExecution()
    trader._execution = fake_execution
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_above_ma10 = types.MethodType(lambda self, symbol, price: True, trader)
    trader._daily_atr = types.MethodType(lambda self, symbol: 1.5, trader)
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-20", trader)

    await trader._evaluate_retail_flow_entry(
        symbol="2330",
        price=100.0,
        change_pct=1.2,
        ts_ms=int(datetime.datetime(2026, 4, 21, 9, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp() * 1000),
        payload={"symbol": "2330", "sector": "24 半導體業"},
    )

    assert fake_execution.buy_calls == []
    assert trader.get_retail_flow_last_non_entry_reason("2330") == "liquidity_below_threshold"


@pytest.mark.asyncio
async def test_retail_flow_strategy_skips_entry_when_market_regime_is_weak() -> None:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-20",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=1500,
                investment_trust_net_buy=800,
                major_net_buy=900,
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
        daily_price_cache=_build_daily_cache(close=100.0, volume=2_000_000),
    )
    trader.update_market_index(-2.2)

    class _FakeExecution:
        def __init__(self) -> None:
            self.buy_calls: list[dict[str, object]] = []

        async def execute_buy(self, **kwargs) -> None:
            self.buy_calls.append(kwargs)

    fake_execution = _FakeExecution()
    trader._execution = fake_execution
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_above_ma10 = types.MethodType(lambda self, symbol, price: True, trader)
    trader._daily_atr = types.MethodType(lambda self, symbol: 1.5, trader)
    trader._swing_trade_date = types.MethodType(lambda self: "2026-04-20", trader)

    await trader._evaluate_retail_flow_entry(
        symbol="2330",
        price=100.0,
        change_pct=1.2,
        ts_ms=int(datetime.datetime(2026, 4, 21, 9, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp() * 1000),
        payload={"symbol": "2330", "sector": "24 半導體業"},
    )

    assert fake_execution.buy_calls == []
    assert trader.get_retail_flow_last_non_entry_reason("2330") == "market_regime_blocked"

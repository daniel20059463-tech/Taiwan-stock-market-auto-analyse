from __future__ import annotations

import datetime
import pytest

from auto_trader import AutoTrader
from trading.paper_execution import PaperExecutionService


@pytest.mark.asyncio
async def test_paper_execution_service_only_supports_buy_and_sell() -> None:
    calls: list[tuple[str, str]] = []

    async def _buy_executor(**kwargs) -> None:
        calls.append(("buy", kwargs["symbol"]))

    async def _sell_executor(**kwargs) -> None:
        calls.append(("sell", kwargs["symbol"]))

    execution = PaperExecutionService(
        buy_executor=_buy_executor,
        sell_executor=_sell_executor,
    )

    await execution.execute_buy(symbol="2330")
    await execution.execute_sell(symbol="2330")

    assert calls == [("buy", "2330"), ("sell", "2330")]

    # execute_short / execute_cover exist but raise RuntimeError to prevent accidental use
    with pytest.raises(RuntimeError, match="not supported"):
        await execution.execute_short(symbol="2330")
    with pytest.raises(RuntimeError, match="not supported"):
        await execution.execute_cover(symbol="2330")


def test_auto_trader_no_longer_exposes_legacy_strategy_branches() -> None:
    legacy_methods = (
        "_evaluate_buy",
        "_check_exit",
        "_evaluate_short",
        "_paper_short",
        "_check_short_exit",
        "_paper_cover",
        "_close_all_eod",
    )

    for method_name in legacy_methods:
        assert not hasattr(AutoTrader, method_name), method_name


@pytest.mark.asyncio
async def test_auto_trader_rejects_unsupported_strategy_mode_at_runtime() -> None:
    trader = AutoTrader(telegram_token="", chat_id="", strategy_mode="intraday")
    ts_ms = int(
        datetime.datetime(2026, 4, 30, 9, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp()
        * 1000
    )

    with pytest.raises(RuntimeError, match="Unsupported strategy_mode"):
        await trader.on_tick(
            {
                "symbol": "2330",
                "price": 950.0,
                "volume": 1000,
                "ts": ts_ms,
                "previousClose": 940.0,
            }
        )

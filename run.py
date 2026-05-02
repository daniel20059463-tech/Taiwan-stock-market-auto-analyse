from __future__ import annotations

import asyncio
import datetime
import importlib
import logging
import os
from typing import Any

from dotenv import load_dotenv
from formal_simulation import run_formal_simulation_preflight
from market_calendar import is_known_open_trading_datetime

from main import create_supervisor_from_runtime
import runtime_bootstrap as _runtime_bootstrap
import strategy_runtime as _strategy_runtime

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")

FLOW_CACHE_PATH = _strategy_runtime.FLOW_CACHE_PATH

RuntimeComponents = _runtime_bootstrap.RuntimeComponents
ReadyStateStore = _runtime_bootstrap.ReadyStateStore
ReadyNotifier = _runtime_bootstrap.ReadyNotifier
AnalyzerServiceAdapter = _runtime_bootstrap.AnalyzerServiceAdapter
CollectorRuntimeAdapter = _runtime_bootstrap.CollectorRuntimeAdapter
MockCollector = _runtime_bootstrap.MockCollector


def _today_trade_date() -> str:
    return _strategy_runtime._today_trade_date()


def _build_strategy_dependencies(strategy_mode: str) -> dict[str, Any]:
    return _strategy_runtime.build_strategy_dependencies(strategy_mode)


def _prime_institutional_flow_cache(dependencies: dict[str, Any]) -> None:
    _strategy_runtime.prime_institutional_flow_cache(
        dependencies,
        cache_path=FLOW_CACHE_PATH,
        today_trade_date_fn=_today_trade_date,
    )


def _load_dynamic_shioaji_universe_from_env() -> dict[str, dict[str, Any]]:
    return _runtime_bootstrap._load_dynamic_shioaji_universe_from_env()


def resolve_symbols(raw_symbols: str) -> list[str]:
    return _runtime_bootstrap.resolve_symbols(raw_symbols)


def resolve_runtime_symbols(
    *,
    raw_symbols: str = "",
    use_mock: bool,
    auto_universe_loader: Any | None = None,
) -> list[str]:
    return _runtime_bootstrap.resolve_runtime_symbols(
        raw_symbols=raw_symbols,
        use_mock=use_mock,
        auto_universe_loader=auto_universe_loader or _load_dynamic_shioaji_universe_from_env,
    )


def _inject_daily_price_cache(auto_trader: Any, symbols: list[str]) -> None:
    _runtime_bootstrap.inject_daily_price_cache(auto_trader, symbols)


def _load_auto_trader(enabled: bool, *, strategy_mode: str = "retail_flow_swing") -> Any | None:
    return _runtime_bootstrap.load_auto_trader(
        enabled,
        strategy_mode=strategy_mode,
        build_strategy_dependencies_fn=_build_strategy_dependencies,
        prime_institutional_flow_cache_fn=_prime_institutional_flow_cache,
    )


def build_runtime_components(
    *,
    raw_symbols: str,
    ws_host: str,
    ws_port: int,
    use_mock: bool,
) -> RuntimeComponents:
    return _runtime_bootstrap.build_runtime_components(
        raw_symbols=raw_symbols,
        ws_host=ws_host,
        ws_port=ws_port,
        use_mock=use_mock,
        resolve_runtime_symbols_fn=resolve_runtime_symbols,
        load_auto_trader_fn=_load_auto_trader,
        inject_daily_price_cache_fn=_inject_daily_price_cache,
    )


async def main() -> None:
    raw_symbols = os.getenv("VITE_SYMBOLS", "").strip()
    ws_host = os.getenv("WS_HOST", "127.0.0.1")
    ws_port = int(os.getenv("WS_PORT", "8765"))
    use_mock = os.getenv("SINOPAC_MOCK", "false").lower() == "true"

    if not use_mock and not is_known_open_trading_datetime():
        logger.warning("Skipping live engine startup: today is not a confirmed TWSE trading day.")
        return
    if not use_mock:
        preflight = run_formal_simulation_preflight()
        if not preflight.ok:
            logger.error("Formal simulation preflight failed: %s", "; ".join(preflight.errors))
            return
        logger.info(
            "Formal simulation preflight passed capital=%.0f sector=%s",
            preflight.account_capital,
            preflight.latest_sector_trade_date or "missing",
        )

    runtime = build_runtime_components(
        raw_symbols=raw_symbols,
        ws_host=ws_host,
        ws_port=ws_port,
        use_mock=use_mock,
    )

    if runtime.auto_trader is not None:
        today = datetime.datetime.now(tz=_TZ_TW).strftime("%Y%m%d")
        restored = await runtime.auto_trader.restore_positions(today)
        if restored:
            logger.info("Restored %d open position(s) from today's DB snapshot", restored)

    supervisor = create_supervisor_from_runtime(runtime)
    logger.info(
        "Collector running on ws://%s:%d symbols=%d. Press Ctrl+C to stop.",
        ws_host,
        ws_port,
        len(runtime.symbols),
    )
    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())

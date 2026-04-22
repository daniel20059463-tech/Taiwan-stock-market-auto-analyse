from __future__ import annotations

import datetime
import importlib
import logging
import os
from typing import Any

from market_calendar import is_known_open_trading_date

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
logger = logging.getLogger("run")


def _today_trade_date() -> str:
    return datetime.datetime.now(tz=_TZ_TW).strftime("%Y-%m-%d")


FLOW_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "flow_cache.json")


def _previous_known_open_trading_date(date_str: str) -> str:
    current = datetime.date.fromisoformat(date_str)
    for offset in range(1, 15):
        candidate = current - datetime.timedelta(days=offset)
        if is_known_open_trading_date(candidate.isoformat()):
            return candidate.isoformat()
    return (current - datetime.timedelta(days=1)).isoformat()


def resolve_flow_cache_trade_date(
    dependencies: dict[str, Any],
    *,
    today_trade_date_fn: Any | None = None,
) -> str:
    resolved_today_trade_date = today_trade_date_fn or _today_trade_date
    trade_date = resolved_today_trade_date()
    if dependencies.get("strategy_mode") == "retail_flow_swing":
        return _previous_known_open_trading_date(trade_date)
    return trade_date


def build_strategy_dependencies(strategy_mode: str) -> dict[str, Any]:
    provider_module = importlib.import_module("institutional_flow_provider")
    cache_module = importlib.import_module("institutional_flow_cache")
    base: dict[str, Any] = {
        "institutional_flow_provider": provider_module.InstitutionalFlowProvider(),
        "institutional_flow_cache": cache_module.InstitutionalFlowCache(),
        "strategy_mode": strategy_mode,
    }
    if strategy_mode == "retail_flow_swing":
        strategy_module = importlib.import_module("retail_flow_strategy")
        base["retail_flow_strategy"] = strategy_module.RetailFlowSwingStrategy()
    return base


def prime_institutional_flow_cache(
    dependencies: dict[str, Any],
    *,
    cache_path: str | None = None,
    today_trade_date_fn: Any | None = None,
) -> None:
    resolved_cache_path = cache_path or FLOW_CACHE_PATH
    target_trade_date = resolve_flow_cache_trade_date(
        dependencies,
        today_trade_date_fn=today_trade_date_fn,
    )
    cache = dependencies.get("institutional_flow_cache")
    if cache is None:
        return
    cache.load(resolved_cache_path)
    provider = dependencies.get("institutional_flow_provider")
    if provider is None:
        return
    try:
        rows = provider.fetch_rank_rows()
        if rows:
            cache.store(trade_date=target_trade_date, rows=rows)
            cache.prune()
            os.makedirs(os.path.dirname(resolved_cache_path), exist_ok=True)
            cache.save(resolved_cache_path)
    except Exception as exc:
        logger.warning("Institutional flow fetch failed: %s", exc)

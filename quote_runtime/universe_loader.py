from __future__ import annotations

from typing import Any

_NON_ORDINARY_STOCK_MARKERS = {
    "ETF",
    "ETN",
    "WARRANT",
    "權證",
    "牛證",
    "熊證",
    "指數",
    "INDEX",
    "債",
    "BOND",
    "特別股",
    "PREFERRED",
}


def _iter_contract_collection(collection: Any) -> list[tuple[str, Any]]:
    if collection is None:
        return []

    items = getattr(collection, "items", None)
    if callable(items):
        try:
            return [
                (str(symbol).strip(), contract)
                for symbol, contract in items()
                if str(symbol).strip()
            ]
        except Exception:
            return []

    try:
        results: list[tuple[str, Any]] = []
        for contract in collection:
            symbol = str(getattr(contract, "code", "") or getattr(contract, "symbol", "") or "").strip()
            if symbol:
                results.append((symbol, contract))
        return results
    except TypeError:
        return []


def _is_ordinary_stock_contract(contract: Any) -> bool:
    symbol = str(getattr(contract, "code", "") or getattr(contract, "symbol", "") or "").strip()
    if not (len(symbol) == 4 and symbol.isdigit()):
        return False
    if symbol.startswith("00"):
        return False

    fields = [
        str(getattr(contract, "type", "") or ""),
        str(getattr(contract, "category", "") or ""),
        str(getattr(contract, "name", "") or ""),
    ]
    text = " ".join(fields).upper()
    return not any(marker in text for marker in _NON_ORDINARY_STOCK_MARKERS)


def load_shioaji_stock_universe(api: Any) -> dict[str, dict[str, Any]]:
    contracts = getattr(api, "Contracts", None)
    stocks = getattr(contracts, "Stocks", None)
    universe: dict[str, dict[str, Any]] = {}

    for market in ("TSE", "OTC"):
        market_contracts = getattr(stocks, market, None)
        for symbol, contract in _iter_contract_collection(market_contracts):
            if not _is_ordinary_stock_contract(contract):
                continue
            if symbol != str(getattr(contract, "code", "") or getattr(contract, "symbol", "") or "").strip():
                continue

            universe[symbol] = {
                "symbol": symbol,
                "name": str(getattr(contract, "name", symbol) or symbol),
                "market": market,
                "sector": str(getattr(contract, "category", "") or "Market"),
                "category": str(getattr(contract, "category", "") or ""),
            }

    return universe

from __future__ import annotations

from typing import Any


class VisibleSubscriptionManager:
    def __init__(
        self,
        *,
        symbols: list[str],
        get_api: Any,
        get_contract_sync: Any,
        symbol_contracts: dict[str, Any],
        visible_symbols: set[str],
        subscribed_visible_symbols: set[str],
        logger: Any,
    ) -> None:
        self._symbols = symbols
        self._get_api = get_api
        self._get_contract_sync = get_contract_sync
        self._symbol_contracts = symbol_contracts
        self.visible_symbols = visible_symbols
        self.subscribed_visible_symbols = subscribed_visible_symbols
        self._logger = logger

    def set_visible_symbols(self, symbols: list[str]) -> None:
        desired = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
        current = set(self.subscribed_visible_symbols)
        self.visible_symbols.clear()
        self.visible_symbols.update(desired)
        if desired != current:
            self.sync()

    def sync(self) -> None:
        api = self._get_api()
        if api is None:
            return

        quote = getattr(api, "quote", None)
        if quote is None:
            return

        try:
            from shioaji.constant import QuoteType, QuoteVersion
        except Exception:
            QuoteType = type("_QuoteType", (), {"Tick": "Tick", "BidAsk": "BidAsk"})
            QuoteVersion = type("_QuoteVersion", (), {"v1": "v1"})

        desired = {symbol for symbol in self.visible_symbols if symbol in self._symbol_contracts}
        current = set(self.subscribed_visible_symbols)
        if desired == current:
            return

        new_subscribed = set(current)
        unsubscribe = getattr(quote, "unsubscribe", None)
        for symbol in [symbol for symbol in self._symbols if symbol in current and symbol not in desired]:
            contract = self._symbol_contracts.get(symbol) or self._get_contract_sync(symbol)
            if contract is None or not callable(unsubscribe):
                continue
            unsubscribed = True
            for quote_type in (QuoteType.Tick, QuoteType.BidAsk):
                try:
                    unsubscribe(contract, quote_type=quote_type, version=QuoteVersion.v1)
                except Exception as exc:
                    unsubscribed = False
                    self._logger.warning("Unsubscribe failed for %s (%s): %s", symbol, quote_type, exc)
            if unsubscribed:
                new_subscribed.discard(symbol)

        for symbol in [symbol for symbol in self._symbols if symbol in desired and symbol not in current]:
            contract = self._symbol_contracts.get(symbol) or self._get_contract_sync(symbol)
            if contract is None:
                continue
            for quote_type in (QuoteType.Tick, QuoteType.BidAsk):
                try:
                    quote.subscribe(contract, quote_type=quote_type, version=QuoteVersion.v1)
                except Exception as exc:
                    self._logger.warning("Subscription failed for %s (%s): %s", symbol, quote_type, exc)
                    break
            else:
                new_subscribed.add(symbol)

        self.subscribed_visible_symbols.clear()
        self.subscribed_visible_symbols.update(new_subscribed)

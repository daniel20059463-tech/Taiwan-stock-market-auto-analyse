from __future__ import annotations

import json
import logging
from typing import Any


logger = logging.getLogger(__name__)


class QuoteDetailBroadcaster:
    def __init__(
        self,
        *,
        clients: set[Any],
        subscriptions: dict[Any, str | None],
        build_order_book_snapshot: Any,
        build_trade_tape_snapshot: Any,
    ) -> None:
        self._clients = clients
        self._subscriptions = subscriptions
        self._build_order_book_snapshot = build_order_book_snapshot
        self._build_trade_tape_snapshot = build_trade_tape_snapshot

    async def broadcast_quote_detail(self, symbol: str) -> None:
        for client, subscribed_symbol in list(self._subscriptions.items()):
            if subscribed_symbol != symbol:
                continue
            try:
                await self.send_quote_detail_snapshots(client, symbol)
            except Exception:
                self._clients.discard(client)
                self._subscriptions.pop(client, None)

    async def send_quote_detail_snapshots(self, websocket: Any, symbol: str) -> None:
        await websocket.send(json.dumps(self._build_order_book_snapshot(symbol), separators=(",", ":")))
        await websocket.send(json.dumps(self._build_trade_tape_snapshot(symbol), separators=(",", ":")))

    def queue_quote_detail_refresh(self, *, loop: Any, symbol: str) -> None:
        if loop is None or loop.is_closed():
            return
        try:
            loop.create_task(self.broadcast_quote_detail(symbol))
        except Exception:
            logger.debug("Quote detail refresh scheduling failed for %s", symbol)

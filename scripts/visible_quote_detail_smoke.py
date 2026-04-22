from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import websockets

WORKSPACE = Path(__file__).resolve().parents[1]
SYMBOL = "2330"
WS_PORT = 9879
TIMEOUT_SECONDS = 45

if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))


def _extract_quote_hit(payload: Any) -> bool:
    if not isinstance(payload, list):
        return False
    for item in payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol", "")).strip() != SYMBOL:
            continue
        try:
            return float(item.get("price", 0) or 0) > 0
        except Exception:
            return False
    return False


async def _run() -> int:
    from sinopac_bridge import collector_from_env

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    load_dotenv(WORKSPACE / ".env")
    os.environ["WS_PORT"] = str(WS_PORT)
    collector = collector_from_env([SYMBOL], auto_trader=None)

    got_quote = False
    got_order_book = False
    got_trade_tape = False
    order_book_rows = 0
    trade_tape_rows = 0
    started_at = time.time()

    try:
        await collector.start()

        async with websockets.connect(f"ws://127.0.0.1:{WS_PORT}") as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "type": "set_visible_symbols",
                        "symbols": [SYMBOL],
                    },
                    separators=(",", ":"),
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "type": "subscribe_quote_detail",
                        "symbol": SYMBOL,
                    },
                    separators=(",", ":"),
                )
            )

            deadline = time.time() + TIMEOUT_SECONDS
            while time.time() < deadline:
                remaining = deadline - time.time()
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=max(1.0, remaining))
                except TimeoutError:
                    break

                payload = json.loads(raw)

                if _extract_quote_hit(payload):
                    got_quote = True
                    continue

                if not isinstance(payload, dict):
                    continue

                if payload.get("type") == "ORDER_BOOK_SNAPSHOT" and payload.get("symbol") == SYMBOL:
                    asks = payload.get("asks") or []
                    bids = payload.get("bids") or []
                    order_book_rows = len(asks) + len(bids)
                    got_order_book = bool(asks and bids)
                    continue

                if payload.get("type") == "TRADE_TAPE_SNAPSHOT" and payload.get("symbol") == SYMBOL:
                    rows = payload.get("rows") or []
                    trade_tape_rows = len(rows)
                    got_trade_tape = bool(rows)
                    continue

                if got_quote and got_order_book and got_trade_tape:
                    break

        visible_symbols = sorted(list(getattr(collector, "visible_symbols", set())))
        subscribed_visible_symbols = sorted(list(getattr(collector, "_subscribed_visible_symbols", set())))

        summary = {
            "symbol": SYMBOL,
            "visible_symbols": visible_symbols,
            "subscribed_visible_symbols": subscribed_visible_symbols,
            "got_quote": got_quote,
            "got_order_book": got_order_book,
            "got_trade_tape": got_trade_tape,
            "order_book_rows": order_book_rows,
            "trade_tape_rows": trade_tape_rows,
            "duration_seconds": round(time.time() - started_at, 2),
        }
        print(json.dumps(summary, ensure_ascii=False))

        if (
            visible_symbols == [SYMBOL]
            and subscribed_visible_symbols == [SYMBOL]
            and got_quote
            and got_order_book
            and got_trade_tape
        ):
            return 0
        return 1
    finally:
        await collector.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise SystemExit(130)

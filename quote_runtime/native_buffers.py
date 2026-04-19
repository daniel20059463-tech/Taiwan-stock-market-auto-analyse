from __future__ import annotations

from collections import deque
import datetime
import time
from typing import Any


class NativeOrderBookBuffers:
    def __init__(self, *, timezone: datetime.tzinfo) -> None:
        self._timezone = timezone
        self._buffers: dict[str, dict[str, Any]] = {}

    @property
    def buffers(self) -> dict[str, dict[str, Any]]:
        return self._buffers

    def build_snapshot(self, symbol: str) -> dict[str, Any]:
        buffer = self._buffers.get(symbol)
        if buffer is None:
            buffer = {"timestamp": 0, "asks": [], "bids": []}
        return {
            "type": "ORDER_BOOK_SNAPSHOT",
            "symbol": symbol,
            "timestamp": int(buffer.get("timestamp") or 0),
            "asks": list(buffer.get("asks", [])),
            "bids": list(buffer.get("bids", [])),
        }

    def apply_bidask(self, bidask: Any) -> str | None:
        symbol = str(getattr(bidask, "code", "") or "")
        if not symbol:
            return None
        timestamp_raw = getattr(bidask, "datetime", None)
        if hasattr(timestamp_raw, "timestamp"):
            timestamp = int(timestamp_raw.timestamp() * 1000)
        else:
            timestamp = 0
        self._buffers[symbol] = {
            "timestamp": timestamp,
            "asks": self.extract_levels(bidask, "ask"),
            "bids": self.extract_levels(bidask, "bid"),
        }
        return symbol

    def extract_levels(self, bidask: Any, side: str) -> list[dict[str, Any]]:
        price_attr = f"{side}_price"
        volume_attr = f"{side}_volume"

        if isinstance(bidask, dict):
            prices_raw = bidask.get(price_attr)
            volumes_raw = bidask.get(volume_attr)
        else:
            prices_raw = getattr(bidask, price_attr, None)
            volumes_raw = getattr(bidask, volume_attr, None)

        if prices_raw is None:
            return []

        prices = [prices_raw] if not isinstance(prices_raw, (list, tuple)) else list(prices_raw)
        if volumes_raw is None:
            volumes: list[Any] = []
        elif isinstance(volumes_raw, (list, tuple)):
            volumes = list(volumes_raw)
        else:
            volumes = [volumes_raw]

        levels: list[dict[str, Any]] = []
        for index, price in enumerate(prices):
            if price is None:
                continue
            volume = volumes[index] if index < len(volumes) else None
            if volume is None:
                continue
            try:
                levels.append(
                    {
                        "level": index + 1,
                        "price": round(float(price), 2),
                        "volume": int(volume),
                    }
                )
            except Exception:
                continue
        return levels


class NativeTradeTapeBuffers:
    def __init__(self, *, symbols: list[str], timezone: datetime.tzinfo, epoch_ms_converter: Any, safe_number: Any, coalesce_number: Any) -> None:
        self._timezone = timezone
        self._to_epoch_milliseconds = epoch_ms_converter
        self._safe_number = safe_number
        self._coalesce_number = coalesce_number
        self._buffers: dict[str, deque[dict[str, Any]]] = {symbol: deque(maxlen=20) for symbol in symbols}
        self._last_trade_prices: dict[str, float] = {}

    @property
    def buffers(self) -> dict[str, deque[dict[str, Any]]]:
        return self._buffers

    @property
    def last_trade_prices(self) -> dict[str, float]:
        return self._last_trade_prices

    def build_snapshot(self, symbol: str) -> dict[str, Any]:
        return {
            "type": "TRADE_TAPE_SNAPSHOT",
            "symbol": symbol,
            "timestamp": int(time.time() * 1000),
            "rows": list(self._buffers.get(symbol, ())),
        }

    def record_trade_tape(self, symbol: str, *, price: float, volume: int, ts_ms: int) -> None:
        if not symbol or volume <= 0:
            return
        previous_price = self._last_trade_prices.get(symbol, price)
        if price > previous_price:
            side = "outer"
        elif price < previous_price:
            side = "inner"
        else:
            side = "neutral"
        self._last_trade_prices[symbol] = price
        timestamp = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=self._timezone)
        self._buffers.setdefault(symbol, deque(maxlen=20)).append(
            {
                "time": timestamp.strftime("%H:%M:%S"),
                "price": round(price, 2),
                "volume": int(volume // 1000 if volume >= 1000 else volume),
                "side": side,
            }
        )

    def record_native_tick_tape(self, tick: Any) -> str | None:
        symbol = str(getattr(tick, "code", "") or "")
        if not symbol:
            return None

        price = self._coalesce_number(
            self._safe_number(tick, ("close",)),
            self._safe_number(tick, ("price",)),
        )
        if price is None:
            return None

        volume_raw = self._coalesce_number(
            self._safe_number(tick, ("volume",)),
            self._safe_number(tick, ("trade_volume",)),
        )
        if volume_raw is None:
            return None
        volume = int(volume_raw)
        if volume <= 0:
            return None

        ts_raw = getattr(tick, "ts", None)
        if ts_raw is None:
            return None
        ts_ms = self._to_epoch_milliseconds(ts_raw)
        self.record_trade_tape(symbol, price=float(price), volume=volume, ts_ms=ts_ms)
        return symbol

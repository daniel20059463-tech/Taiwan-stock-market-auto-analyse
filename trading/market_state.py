from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Optional


ATR_BARS_NEEDED = 5


@dataclass
class CandleBar:
    ts_min: int
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketState:
    def __init__(self) -> None:
        self._open_prices: dict[str, float] = {}
        self._last_prices: dict[str, float] = {}
        self._current_bar: dict[str, CandleBar] = {}
        self._bar_history: dict[str, collections.deque[CandleBar]] = {}
        self._volume_history: dict[str, collections.deque[int]] = {}

    @property
    def open_prices(self) -> dict[str, float]:
        return self._open_prices

    @property
    def current_bar(self) -> dict[str, CandleBar]:
        return self._current_bar

    @property
    def bar_history(self) -> dict[str, collections.deque[CandleBar]]:
        return self._bar_history

    @property
    def volume_history(self) -> dict[str, collections.deque[int]]:
        return self._volume_history

    def update_tick(self, symbol: str, *, price: float, volume: int, ts_ms: int) -> None:
        ts_min = ts_ms // 60_000

        if symbol not in self._open_prices:
            self._open_prices[symbol] = price

        self._last_prices[symbol] = price

        bar = self._current_bar.get(symbol)
        if bar is None:
            self._current_bar[symbol] = CandleBar(
                ts_min=ts_min,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
            return

        if bar.ts_min != ts_min:
            self._bar_history.setdefault(symbol, collections.deque(maxlen=20)).append(bar)
            self._volume_history.setdefault(symbol, collections.deque(maxlen=10)).append(bar.volume)
            self._current_bar[symbol] = CandleBar(
                ts_min=ts_min,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
            return

        bar.high = max(bar.high, price)
        bar.low = min(bar.low, price)
        bar.close = price
        bar.volume += volume

    def reset_intraday(self) -> None:
        """Clear per-day open prices and active bars; keep ATR/volume history."""
        self._open_prices.clear()
        self._current_bar.clear()

    def open_price(self, symbol: str) -> Optional[float]:
        return self._open_prices.get(symbol)

    def last_price(self, symbol: str) -> Optional[float]:
        return self._last_prices.get(symbol)

    @property
    def last_prices(self) -> dict[str, float]:
        return self._last_prices

    def latest_bar(self, symbol: str) -> Optional[CandleBar]:
        return self._current_bar.get(symbol)

    def average_volume(self, symbol: str) -> Optional[float]:
        volumes = self._volume_history.get(symbol)
        if volumes is None or len(volumes) < ATR_BARS_NEEDED:
            return None
        recent = list(volumes)[-ATR_BARS_NEEDED:]
        return sum(recent) / len(recent)

    def calculate_atr(self, symbol: str) -> Optional[float]:
        history = self._bar_history.get(symbol)
        if history is None or len(history) < ATR_BARS_NEEDED:
            return None

        bars = list(history)
        true_ranges: list[float] = []
        for index in range(1, len(bars)):
            prev_close = bars[index - 1].close
            bar = bars[index]
            true_ranges.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - prev_close),
                    abs(bar.low - prev_close),
                )
            )

        if not true_ranges:
            return None

        return round(sum(true_ranges) / len(true_ranges), 4)

    def calculate_rsi(self, symbol: str, period: int = 14) -> Optional[float]:
        """Calculate simple RSI from recent 1-minute bar closing prices."""
        history = self._bar_history.get(symbol)
        if history is None or len(history) < period + 1:
            return None

        closes = [bar.close for bar in list(history)[-(period + 1):]]
        gains: list[float] = []
        losses: list[float] = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1 + rs)), 2)

"""
Daily OHLCV price cache for swing-strategy indicators (MA, RSI).

Stores one bar per symbol per trading date. Persists to JSON so
MA10 / RSI calculations survive process restarts across days.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass

DAILY_CACHE_MAX_DAYS = 60


@dataclass
class DailyBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class DailyPriceCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, DailyBar]] = defaultdict(dict)

    # ── write ──────────────────────────────────────────────────────────────

    def add_bar(self, symbol: str, bar: DailyBar) -> None:
        self._data[symbol][bar.date] = bar

    def update_close(self, symbol: str, date: str, close: float) -> None:
        """Upsert the closing price for a given date (used at EOD)."""
        existing = self._data[symbol].get(date)
        if existing is not None:
            existing.close = close
        else:
            self._data[symbol][date] = DailyBar(
                date=date, open=close, high=close, low=close, close=close, volume=0
            )

    # ── read ───────────────────────────────────────────────────────────────

    def get_closes(
        self,
        symbol: str,
        as_of_date: str | None = None,
        n: int = 60,
    ) -> list[float]:
        """Return the last *n* daily closes up to *as_of_date* (inclusive)."""
        dates = sorted(self._data.get(symbol, {}).keys())
        if as_of_date:
            dates = [d for d in dates if d <= as_of_date]
        return [self._data[symbol][d].close for d in dates[-n:]]

    def get_bars(
        self,
        symbol: str,
        as_of_date: str | None = None,
        n: int = 60,
    ) -> list[DailyBar]:
        dates = sorted(self._data.get(symbol, {}).keys())
        if as_of_date:
            dates = [d for d in dates if d <= as_of_date]
        return [self._data[symbol][d] for d in dates[-n:]]

    def ma(
        self,
        symbol: str,
        period: int,
        as_of_date: str | None = None,
    ) -> float | None:
        closes = self.get_closes(symbol, as_of_date=as_of_date, n=period)
        if len(closes) < period:
            return None
        return sum(closes) / period

    def rsi(
        self,
        symbol: str,
        period: int = 14,
        as_of_date: str | None = None,
    ) -> float | None:
        closes = self.get_closes(symbol, as_of_date=as_of_date, n=period + 1)
        if len(closes) < period + 1:
            return None
        gains: list[float] = []
        losses: list[float] = []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(0.0, delta))
            losses.append(max(0.0, -delta))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1 + rs)), 2)

    def atr(
        self,
        symbol: str,
        period: int = 14,
        as_of_date: str | None = None,
    ) -> float | None:
        """Return ATR using True Range (high-low, high-prev_close, low-prev_close)."""
        dates = sorted(self._data.get(symbol, {}).keys())
        if as_of_date:
            dates = [d for d in dates if d <= as_of_date]
        # Need period+1 bars so every bar has a previous bar for prev_close
        bars = [self._data[symbol][d] for d in dates[-(period + 1):]]
        if len(bars) < period + 1:
            return None
        true_ranges: list[float] = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            bar = bars[i]
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            true_ranges.append(tr)
        return sum(true_ranges) / period

    def average_volume(
        self,
        symbol: str,
        period: int = 20,
        as_of_date: str | None = None,
    ) -> float | None:
        bars = self.get_bars(symbol, as_of_date=as_of_date, n=period)
        if len(bars) < period:
            return None
        return sum(bar.volume for bar in bars) / period

    def average_value(
        self,
        symbol: str,
        period: int = 20,
        as_of_date: str | None = None,
    ) -> float | None:
        bars = self.get_bars(symbol, as_of_date=as_of_date, n=period)
        if len(bars) < period:
            return None
        return sum(bar.close * bar.volume for bar in bars) / period

    def has_enough_data(self, symbol: str, min_bars: int) -> bool:
        return len(self._data.get(symbol, {})) >= min_bars

    def symbols(self) -> list[str]:
        return list(self._data.keys())

    def latest_date(self, symbol: str) -> str | None:
        dates = sorted(self._data.get(symbol, {}).keys())
        return dates[-1] if dates else None

    # ── persistence ────────────────────────────────────────────────────────

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            symbol: {date: asdict(bar) for date, bar in bars.items()}
            for symbol, bars in self._data.items()
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            for symbol, bars in raw.items():
                for date, bar_dict in bars.items():
                    try:
                        self._data[symbol][date] = DailyBar(**bar_dict)
                    except Exception:
                        pass
        except Exception:
            pass

    def prune(self, keep_days: int = DAILY_CACHE_MAX_DAYS) -> None:
        for symbol in list(self._data.keys()):
            dates = sorted(self._data[symbol].keys(), reverse=True)
            for old_date in dates[keep_days:]:
                del self._data[symbol][old_date]

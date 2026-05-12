"""
TWSE / TPEX historical daily OHLCV fetcher for backtesting.

TWSE API (上市): https://www.twse.com.tw/exchangeReport/STOCK_DAY
TPEX API (上櫃): https://www.tpex.org.tw/www/zh-tw/stock/historicalPrice
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import json
import datetime
from dataclasses import dataclass
from typing import Any


@dataclass
class BacktestBar:
    symbol: str
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    previous_close: float


_TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
_TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/stock/historicalPrice"
_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
_RETRY_DELAYS = (1.0, 3.0, 7.0)


def _tw_date_to_ms(date_str: str) -> int:
    """'YYYY-MM-DD' → UTC midnight Unix ms（台灣時區 00:00）。"""
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=datetime.timezone(datetime.timedelta(hours=8))
    )
    return int(dt.timestamp() * 1000)


def _month_range(start_date: str, end_date: str) -> list[tuple[int, int]]:
    """產生 (year, month) 列表，從 start_date 到 end_date（含）。"""
    start = datetime.date.fromisoformat(start_date)
    end = datetime.date.fromisoformat(end_date)
    months: list[tuple[int, int]] = []
    current = start.replace(day=1)
    while current <= end:
        months.append((current.year, current.month))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return months


def _fetch_json(url: str, params: dict[str, str]) -> Any:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; backtester/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_with_retry(url: str, params: dict[str, str]) -> Any:
    last_exc: Exception | None = None
    for delay in (0.0, *_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return _fetch_json(url, params)
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"fetch failed after retries: {last_exc}") from last_exc


def _parse_twse_month(symbol: str, data: Any, start_date: str, end_date: str) -> list[BacktestBar]:
    """解析 TWSE STOCK_DAY JSON，回傳指定日期範圍內的 BacktestBar。"""
    if not isinstance(data, dict):
        return []
    status = data.get("stat", "")
    if status != "OK":
        return []
    raw_rows = data.get("data", [])
    bars: list[BacktestBar] = []
    for row in raw_rows:
        if len(row) < 7:
            continue
        try:
            # TWSE 日期格式：民國年/月/日，例如 "113/01/15"
            tw_parts = row[0].strip().split("/")
            year = int(tw_parts[0]) + 1911
            month = int(tw_parts[1])
            day = int(tw_parts[2])
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            if date_str < start_date or date_str > end_date:
                continue

            def _clean(s: str) -> float:
                return float(s.replace(",", "").strip())

            open_ = _clean(row[3])
            high = _clean(row[4])
            low = _clean(row[5])
            close = _clean(row[6])
            volume = int(row[1].replace(",", "").strip())  # 成交股數（股）→ 轉千股
            bars.append(BacktestBar(
                symbol=symbol,
                ts_ms=_tw_date_to_ms(date_str),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume // 1000,
                previous_close=0.0,  # 由呼叫端填入
            ))
        except (ValueError, IndexError):
            continue
    return bars


def _parse_tpex_month(symbol: str, data: Any, start_date: str, end_date: str) -> list[BacktestBar]:
    """解析 TPEX historicalPrice JSON，回傳指定日期範圍內的 BacktestBar。"""
    if not isinstance(data, dict):
        return []
    tables = data.get("tables", [])
    if not tables:
        return []
    rows = tables[0].get("data", [])
    bars: list[BacktestBar] = []
    for row in rows:
        if len(row) < 8:
            continue
        try:
            # TPEX 日期格式：民國年/月/日
            tw_parts = row[0].strip().split("/")
            year = int(tw_parts[0]) + 1911
            month = int(tw_parts[1])
            day = int(tw_parts[2])
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            if date_str < start_date or date_str > end_date:
                continue

            def _clean(s: str) -> float:
                return float(s.replace(",", "").strip())

            open_ = _clean(row[4])
            high = _clean(row[5])
            low = _clean(row[6])
            close = _clean(row[3])
            volume = int(float(row[7].replace(",", "").strip()) * 1000) // 1000  # 千股
            bars.append(BacktestBar(
                symbol=symbol,
                ts_ms=_tw_date_to_ms(date_str),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                previous_close=0.0,
            ))
        except (ValueError, IndexError):
            continue
    return bars


def _fetch_yahoo_bars(symbol: str, start_date: str, end_date: str) -> list[BacktestBar]:
    """Yahoo Finance fallback：當 TWSE/TPEX API 拿不到資料時使用。
    先嘗試 {symbol}.TWO（上櫃），再嘗試 {symbol}.TW（上市）。
    """
    start_dt = datetime.date.fromisoformat(start_date)
    end_dt = datetime.date.fromisoformat(end_date)
    period1 = int(datetime.datetime(start_dt.year, start_dt.month, start_dt.day,
                                    tzinfo=datetime.timezone.utc).timestamp())
    period2 = int(datetime.datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59,
                                    tzinfo=datetime.timezone.utc).timestamp())

    for suffix in (".TWO", ".TW"):
        ticker = f"{symbol}{suffix}"
        url = (f"{_YAHOO_URL}{ticker}?interval=1d"
               f"&period1={period1}&period2={period2}")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; backtester/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            quote = result["indicators"]["quote"][0]
            tz_tw = datetime.timezone(datetime.timedelta(hours=8))
            bars: list[BacktestBar] = []
            for i, ts in enumerate(timestamps):
                o = quote["open"][i]
                h = quote["high"][i]
                l = quote["low"][i]
                c = quote["close"][i]
                v = quote["volume"][i]
                if any(x is None for x in (o, h, l, c, v)):
                    continue
                dt = datetime.datetime.fromtimestamp(ts, tz=tz_tw)
                date_str = dt.strftime("%Y-%m-%d")
                if date_str < start_date or date_str > end_date:
                    continue
                bars.append(BacktestBar(
                    symbol=symbol,
                    ts_ms=_tw_date_to_ms(date_str),
                    open=round(float(o), 2),
                    high=round(float(h), 2),
                    low=round(float(l), 2),
                    close=round(float(c), 2),
                    volume=int(v) // 1000,
                    previous_close=0.0,
                ))
            if bars:
                return bars
        except Exception:
            continue
    return []


class TWSEHistoricalFetcher:
    """TWSE / TPEX 歷史日 K 資料抓取器，供回測使用。"""

    def fetch_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[BacktestBar]:
        """
        抓取指定股票在 [start_date, end_date] 之間的日 K 資料。

        Args:
            symbol: 股票代碼（4 碼），例如 "2330"
            start_date: 起始日（含），格式 "YYYY-MM-DD"
            end_date: 結束日（含），格式 "YYYY-MM-DD"

        Returns:
            按日期升冪排列的 BacktestBar 列表，previous_close 已填入。
        """
        months = _month_range(start_date, end_date)
        all_bars: list[BacktestBar] = []
        exchange: str | None = None  # 第一次成功後固定交易所，避免重複探測

        for year, month in months:
            time.sleep(0.3)  # 避免頻率過快被封
            try:
                if exchange == "twse":
                    bars = self._fetch_twse_month(symbol, year, month, start_date, end_date)
                elif exchange == "tpex":
                    bars = self._fetch_tpex_month(symbol, year, month, start_date, end_date)
                else:
                    # 先試 TPEX；沒資料再 fallback TWSE（prefix 判斷不可靠）
                    bars = self._fetch_tpex_month(symbol, year, month, start_date, end_date)
                    if not bars:
                        bars = self._fetch_twse_month(symbol, year, month, start_date, end_date)
                        if bars:
                            exchange = "twse"
                    else:
                        exchange = "tpex"
                all_bars.extend(bars)
            except Exception:
                continue

        if not all_bars:
            all_bars = _fetch_yahoo_bars(symbol, start_date, end_date)

        all_bars.sort(key=lambda b: b.ts_ms)
        self._fill_previous_close(all_bars)
        return all_bars

    def _fetch_twse_month(
        self, symbol: str, year: int, month: int, start_date: str, end_date: str
    ) -> list[BacktestBar]:
        date_param = f"{year}{month:02d}01"
        data = _fetch_with_retry(_TWSE_URL, {
            "date": date_param,
            "stockNo": symbol,
            "response": "json",
        })
        return _parse_twse_month(symbol, data, start_date, end_date)

    def _fetch_tpex_month(
        self, symbol: str, year: int, month: int, start_date: str, end_date: str
    ) -> list[BacktestBar]:
        tw_year = year - 1911
        start_tw = f"{tw_year}/{month:02d}/01"
        last_day = (
            datetime.date(year, month, 1).replace(
                month=month % 12 + 1, year=year + (1 if month == 12 else 0)
            ) - datetime.timedelta(days=1)
        ).day
        end_tw = f"{tw_year}/{month:02d}/{last_day:02d}"
        data = _fetch_with_retry(_TPEX_URL, {
            "startDate": start_tw,
            "endDate": end_tw,
            "stockNo": symbol,
            "response": "json",
        })
        return _parse_tpex_month(symbol, data, start_date, end_date)

    @staticmethod
    def _fill_previous_close(bars: list[BacktestBar]) -> None:
        """用前一根收盤價填入 previous_close（第一根以 open 代替）。"""
        for i, bar in enumerate(bars):
            if i == 0:
                bar.previous_close = bar.open
            else:
                bar.previous_close = bars[i - 1].close

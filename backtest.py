"""
Backtest runner for paper-trading strategies.

Feeds historical OHLCV bars as synthetic ticks into an AutoTrader instance
and computes performance metrics: win rate, total PnL, and max drawdown.

Usage:
    from backtest import BacktestRunner, BacktestBar, BacktestResult
    from auto_trader import AutoTrader
    from institutional_flow_provider import InstitutionalFlowRow

    def make_trader():
        return AutoTrader(telegram_token="", chat_id="", strategy_mode="intraday")

    runner = BacktestRunner(auto_trader_factory=make_trader)
    result = await runner.run(bars=my_bars, flow_rows_by_date={})
    print(result.win_rate, result.total_pnl)
"""
from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))


@dataclass
class BacktestBar:
    symbol: str
    ts_ms: int          # 分鐘 K 棒的時間戳（毫秒），代表 bar 的開始時間
    open: float
    high: float
    low: float
    close: float
    volume: int
    previous_close: float  # 前日收盤價，用來計算漲跌幅


@dataclass
class BacktestResult:
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate: float           # 0.0–1.0
    total_pnl: float          # 所有交易的淨損益總和（已扣手續費與稅）
    avg_pnl_per_trade: float
    max_drawdown_pct: float   # 從峰值的最大回撤 %
    trade_records: list[dict] = field(default_factory=list)


class BacktestRunner:
    """
    Replays historical bars through an AutoTrader and collects results.

    Each bar is expanded into 3 synthetic ticks (open, mid, close) so the
    trader's intraday logic can trigger both entries and exits within a bar.
    """

    def __init__(self, *, auto_trader_factory: Callable[[], Any]) -> None:
        self._factory = auto_trader_factory

    async def run(
        self,
        bars: list[BacktestBar],
        flow_rows_by_date: dict[str, list] | None = None,
        daily_price_cache: Any = None,
    ) -> BacktestResult:
        """
        Run the backtest.

        Args:
            bars: List of BacktestBar sorted by ts_ms (ascending).
            flow_rows_by_date: Optional dict mapping date strings ("YYYY-MM-DD")
                to lists of InstitutionalFlowRow, pre-loaded into the trader's
                institutional flow cache before replay starts.
            daily_price_cache: Optional DailyPriceCache instance. When provided,
                injected into the trader so ATR/MA/RSI calculations match live
                behaviour instead of falling back to the mid-stop default.
        """
        trader = self._factory()

        if flow_rows_by_date and hasattr(trader, "_institutional_flow_cache"):
            cache = trader._institutional_flow_cache
            if cache is not None:
                for date_str, rows in flow_rows_by_date.items():
                    cache.store(trade_date=date_str, rows=rows)

        if daily_price_cache is not None and hasattr(trader, "set_daily_price_cache"):
            trader.set_daily_price_cache(daily_price_cache)

        sorted_bars = sorted(bars, key=lambda b: b.ts_ms)
        for bar in sorted_bars:
            for tick in _bar_to_ticks(bar):
                await trader.on_tick(tick)

        initial_equity = float(
            getattr(getattr(trader, "_risk", None), "account_capital", 1_000_000.0)
        )
        return _compute_result(trader._book.trade_history, initial_equity=initial_equity)


def _bar_to_ticks(bar: BacktestBar) -> list[dict[str, Any]]:
    """Expand one OHLCV bar into 3 synthetic ticks: open, mid, close.

    Timestamps are anchored to 09:05 TW time so they fall inside the swing
    entry window (09:00–10:00).  Without this offset daily bars stored with
    a midnight epoch would never pass _is_swing_entry_window.
    """
    mid_price = round((bar.open + bar.close) / 2, 2)
    vol_each = max(1, bar.volume // 3)

    # Anchor to 09:05:00 TW (UTC+8) for the bar's calendar date
    dt_utc = datetime.datetime.fromtimestamp(bar.ts_ms / 1000, tz=datetime.timezone.utc)
    dt_tw = dt_utc.astimezone(_TZ_TW)
    open_tw = dt_tw.replace(hour=9, minute=5, second=0, microsecond=0)
    open_ts_ms = int(open_tw.timestamp() * 1000)

    ticks = []
    for i, price in enumerate([bar.open, mid_price, bar.close]):
        change_pct = (
            (price - bar.previous_close) / bar.previous_close * 100
            if bar.previous_close else 0.0
        )
        ticks.append({
            "symbol": bar.symbol,
            "price": price,
            "ts": open_ts_ms + i * 20_000,  # spread 20s apart within the bar
            "volume": vol_each,
            "previousClose": bar.previous_close,
            "high": bar.high,
            "low": bar.low,
            "nearLimitUp": change_pct >= 9.0,
            "nearLimitDown": change_pct <= -9.0,
        })
    return ticks


def _compute_result(trade_history: list, *, initial_equity: float = 1_000_000.0) -> BacktestResult:
    sells = [t for t in trade_history if getattr(t, "action", None) in {"SELL", "COVER"}]

    if not sells:
        return BacktestResult(
            total_trades=0,
            win_trades=0,
            loss_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            avg_pnl_per_trade=0.0,
            max_drawdown_pct=0.0,
        )

    win_trades = sum(1 for t in sells if t.pnl > 0)
    loss_trades = len(sells) - win_trades
    total_pnl = sum(t.pnl for t in sells)
    win_rate = win_trades / len(sells)
    avg_pnl = total_pnl / len(sells)
    max_dd = _calc_max_drawdown(sells, initial_equity=initial_equity)

    records = [
        {
            "symbol": t.symbol,
            "action": t.action,
            "price": t.price,
            "shares": t.shares,
            "pnl": t.pnl,
            "reason": t.reason,
        }
        for t in sells
    ]

    return BacktestResult(
        total_trades=len(sells),
        win_trades=win_trades,
        loss_trades=loss_trades,
        win_rate=win_rate,
        total_pnl=round(total_pnl, 2),
        avg_pnl_per_trade=round(avg_pnl, 2),
        max_drawdown_pct=round(max_dd, 2),
        trade_records=records,
    )


def _calc_max_drawdown(sells: list, *, initial_equity: float = 1_000_000.0) -> float:
    """Calculate max drawdown % from an equity curve anchored by initial equity."""
    if not sells:
        return 0.0
    equity = float(initial_equity)
    peak_equity = equity
    max_dd = 0.0
    for trade in sells:
        equity += float(trade.pnl)
        if equity > peak_equity:
            peak_equity = equity
        if peak_equity > 0:
            dd = (peak_equity - equity) / peak_equity * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd

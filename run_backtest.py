"""
CLI for running a strategy backtest on a single Taiwan stock symbol.

Usage:
    python run_backtest.py 2330
    python run_backtest.py 2330 2025-01-01 2025-03-31
    python run_backtest.py 2330 2025-01-01 2025-03-31 --mode intraday
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import sys

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))


def _today() -> str:
    return datetime.datetime.now(tz=_TZ_TW).date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.datetime.now(tz=_TZ_TW).date() - datetime.timedelta(days=n)).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest a strategy on a single symbol.")
    parser.add_argument("symbol", help="Taiwan stock code, e.g. 2330")
    parser.add_argument("start_date", nargs="?", default=None, help="YYYY-MM-DD (default: 90 days ago)")
    parser.add_argument("end_date", nargs="?", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--mode",
        default="retail_flow_swing",
        choices=["retail_flow_swing", "intraday"],
        help="Strategy mode (default: retail_flow_swing)",
    )
    return parser.parse_args()


def make_trader(mode: str):
    from auto_trader import AutoTrader
    from risk_manager import risk_manager_from_env

    risk = risk_manager_from_env()
    return AutoTrader(
        telegram_token="",
        chat_id="",
        strategy_mode=mode,
        risk_manager=risk,
    )


async def run(symbol: str, start_date: str, end_date: str, mode: str) -> None:
    from backtest import BacktestRunner
    from historical_data import TWSEHistoricalFetcher

    print(f"Fetching {symbol}  {start_date} → {end_date} ...")
    fetcher = TWSEHistoricalFetcher()
    bars = fetcher.fetch_bars(symbol, start_date, end_date)

    if not bars:
        print("No bars fetched. Check the symbol or date range.")
        sys.exit(1)

    print(f"Fetched {len(bars)} bars. Running backtest in [{mode}] mode ...")
    runner = BacktestRunner(auto_trader_factory=lambda: make_trader(mode))
    result = await runner.run(bars=bars)

    sep = "=" * 52
    print(f"\n{sep}")
    print(f"  BACKTEST  {symbol}  {start_date} → {end_date}  [{mode}]")
    print(sep)
    print(f"  總交易筆數  : {result.total_trades}")
    print(f"  獲利 / 虧損  : {result.win_trades} / {result.loss_trades}")
    print(f"  勝率        : {result.win_rate:.1%}")
    print(f"  總損益      : {result.total_pnl:+,.0f}")
    print(f"  平均每筆損益 : {result.avg_pnl_per_trade:+,.0f}")
    print(f"  最大回撤    : {result.max_drawdown_pct:.2f}%")
    print(sep)

    if result.trade_records:
        print("\n  最近 10 筆成交：")
        for t in result.trade_records[-10:]:
            pnl = t.get("pnl", 0)
            sign = "+" if pnl >= 0 else ""
            print(
                f"    {t.get('symbol'):>6}  {t.get('action'):<5}  "
                f"{t.get('reason', ''):<18}  PnL {sign}{pnl:,.0f}"
            )
        print()

        reasons: dict[str, int] = {}
        for t in result.trade_records:
            r = t.get("reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
        print("  出場原因分佈：")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            bar = "█" * count
            print(f"    {reason:<20} {bar} ({count})")
        print()


def main() -> None:
    args = parse_args()
    start = args.start_date or _days_ago(90)
    end = args.end_date or _today()
    asyncio.run(run(args.symbol, start, end, args.mode))


if __name__ == "__main__":
    main()

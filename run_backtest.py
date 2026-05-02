"""
CLI for running a strategy backtest on a single Taiwan stock symbol.

Usage:
    python run_backtest.py 2330
    python run_backtest.py 2330 2025-01-01 2025-03-31
    python run_backtest.py 2330 2025-01-01 2025-03-31 --mode retail_flow_swing

Results are saved automatically:
    backtest_results/YYYY-MM/<symbol>_<start>_<end>_<mode>.json  (full detail)
    backtest_results/summary.csv                                 (one row per run)

Old detail files are pruned after DETAIL_KEEP_DAYS (default 90).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import json
import os
import sys

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
_RESULTS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results")
DETAIL_KEEP_DAYS = 90


def _today() -> str:
    return datetime.datetime.now(tz=_TZ_TW).date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.datetime.now(tz=_TZ_TW).date() - datetime.timedelta(days=n)).isoformat()


def _month_dir(date_str: str) -> str:
    ym = date_str[:7]
    path = os.path.join(_RESULTS_ROOT, ym)
    os.makedirs(path, exist_ok=True)
    return path


def _save_detail(symbol: str, start: str, end: str, mode: str, result: object, bars_count: int) -> str:
    detail = {
        "symbol": symbol,
        "start_date": start,
        "end_date": end,
        "mode": mode,
        "bars": bars_count,
        "run_at": datetime.datetime.now(tz=_TZ_TW).isoformat(),
        "total_trades": result.total_trades,
        "win_trades": result.win_trades,
        "loss_trades": result.loss_trades,
        "win_rate": round(result.win_rate * 100, 1),
        "total_pnl": round(result.total_pnl, 0),
        "avg_pnl_per_trade": round(result.avg_pnl_per_trade, 0),
        "max_drawdown_pct": result.max_drawdown_pct,
        "trade_records": result.trade_records,
    }
    filename = f"{symbol}_{start}_{end}_{mode}.json"
    path = os.path.join(_month_dir(end), filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False, indent=2)
    return path


def _append_summary(symbol: str, start: str, end: str, mode: str, result: object, bars_count: int) -> None:
    os.makedirs(_RESULTS_ROOT, exist_ok=True)
    summary_path = os.path.join(_RESULTS_ROOT, "summary.csv")
    write_header = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(
                [
                    "run_at",
                    "symbol",
                    "start_date",
                    "end_date",
                    "mode",
                    "bars",
                    "total_trades",
                    "win_trades",
                    "loss_trades",
                    "win_rate_pct",
                    "total_pnl",
                    "avg_pnl",
                    "max_drawdown_pct",
                ]
            )
        writer.writerow(
            [
                datetime.datetime.now(tz=_TZ_TW).strftime("%Y-%m-%d %H:%M"),
                symbol,
                start,
                end,
                mode,
                bars_count,
                result.total_trades,
                result.win_trades,
                result.loss_trades,
                round(result.win_rate * 100, 1),
                round(result.total_pnl, 0),
                round(result.avg_pnl_per_trade, 0),
                result.max_drawdown_pct,
            ]
        )


def _prune_old_details(keep_days: int = DETAIL_KEEP_DAYS) -> int:
    cutoff = datetime.datetime.now(tz=_TZ_TW) - datetime.timedelta(days=keep_days)
    removed = 0
    if not os.path.isdir(_RESULTS_ROOT):
        return 0
    for entry in os.scandir(_RESULTS_ROOT):
        if not entry.is_dir():
            continue
        try:
            folder_date = datetime.datetime.strptime(entry.name, "%Y-%m").replace(
                tzinfo=_TZ_TW, day=1
            )
        except ValueError:
            continue
        if folder_date < cutoff.replace(day=1):
            for f in os.scandir(entry.path):
                if f.name.endswith(".json"):
                    os.remove(f.path)
                    removed += 1
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest a strategy on a single symbol.")
    parser.add_argument("symbol", help="Taiwan stock code, e.g. 2330")
    parser.add_argument("start_date", nargs="?", default=None, help="YYYY-MM-DD (default: 90 days ago)")
    parser.add_argument("end_date", nargs="?", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--mode",
        default="retail_flow_swing",
        choices=["retail_flow_swing"],
        help="Strategy mode (default: retail_flow_swing)",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=DETAIL_KEEP_DAYS,
        help=f"Days to keep detail JSON files (default: {DETAIL_KEEP_DAYS})",
    )
    parser.add_argument(
        "--slippage-multiplier",
        type=float,
        default=1.0,
        help="Multiplier applied to resolved execution slippage (default: 1.0)",
    )
    return parser.parse_args()


def make_trader(mode: str, slippage_multiplier: float):
    from auto_trader import AutoTrader
    from risk_manager import risk_manager_from_env

    risk = risk_manager_from_env()
    return AutoTrader(
        telegram_token="",
        chat_id="",
        strategy_mode=mode,
        risk_manager=risk,
        slippage_multiplier=slippage_multiplier,
    )


async def run(
    symbol: str,
    start_date: str,
    end_date: str,
    mode: str,
    keep_days: int,
    slippage_multiplier: float,
) -> None:
    from backtest import BacktestRunner
    from historical_data import TWSEHistoricalFetcher

    print(f"正在抓取 {symbol} {start_date} -> {end_date} ...")
    fetcher = TWSEHistoricalFetcher()
    bars = fetcher.fetch_bars(symbol, start_date, end_date)

    if not bars:
        print("No bars fetched. Check the symbol or date range.")
        sys.exit(1)

    # 抓取 0050（元大台灣50）作為大盤強弱代理，供市場篩選器使用
    print("正在抓取 0050（大盤代理）做市場強弱判斷 ...")
    market_index_by_date: dict[str, float] = {}
    try:
        taiex_bars = fetcher.fetch_bars("0050", start_date, end_date)
        for tbar in taiex_bars:
            if tbar.previous_close and tbar.previous_close > 0:
                change_pct = (tbar.close - tbar.previous_close) / tbar.previous_close * 100
                dt = datetime.datetime.fromtimestamp(tbar.ts_ms / 1000, tz=_TZ_TW)
                market_index_by_date[dt.strftime("%Y-%m-%d")] = round(change_pct, 2)
        print(f"  已載入 {len(market_index_by_date)} 個交易日的大盤資料。")
    except Exception as exc:
        print(f"  警告：無法抓取 0050（{exc}），大盤篩選器將停用。")

    print(f"已抓到 {len(bars)} 根 K 棒，開始執行 [{mode}] 回測 ...")
    runner = BacktestRunner(
        auto_trader_factory=lambda: make_trader(mode, slippage_multiplier)
    )
    result = await runner.run(bars=bars, market_index_by_date=market_index_by_date or None)

    sep = "=" * 52
    print(f"\n{sep}")
    print(f"  BACKTEST  {symbol}  {start_date} -> {end_date}  [{mode}]")
    print(f"  滑價倍數      : {slippage_multiplier:.2f}x")
    print(sep)
    print(f"  總交易數     : {result.total_trades}")
    print(f"  勝場 / 敗場  : {result.win_trades} / {result.loss_trades}")
    print(f"  勝率         : {result.win_rate:.1%}")
    print(f"  總損益       : {result.total_pnl:+,.0f}")
    print(f"  平均每筆損益 : {result.avg_pnl_per_trade:+,.0f}")
    print(f"  最大回撤     : {result.max_drawdown_pct:.2f}%")
    print(sep)

    if result.trade_records:
        print("\n  最近 10 筆交易")
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
        print("  出場原因統計")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            bar = "#" * count
            print(f"    {reason:<20} {bar} ({count})")
        print()

    detail_path = _save_detail(symbol, start_date, end_date, mode, result, len(bars))
    _append_summary(symbol, start_date, end_date, mode, result, len(bars))
    pruned = _prune_old_details(keep_days)

    print(f"  已存明細：{detail_path}")
    print(f"  已更新摘要：{os.path.join(_RESULTS_ROOT, 'summary.csv')}")
    if pruned:
        print(f"  已清理 {pruned} 個超過 {keep_days} 天的舊明細檔")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = parse_args()
    start = args.start_date or _days_ago(90)
    end = args.end_date or _today()
    asyncio.run(
        run(
            args.symbol,
            start,
            end,
            args.mode,
            args.keep_days,
            args.slippage_multiplier,
        )
    )


if __name__ == "__main__":
    main()

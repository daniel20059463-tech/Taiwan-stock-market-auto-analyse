"""
參數掃描腳本：測試不同 flow_score 門檻和 ATR 停損倍數組合
目標：找出勝率 > 55% 且期望值 > 1.5R 的最佳參數

用法：python param_sweep.py
"""
from __future__ import annotations
import asyncio, json, os, sys, itertools, datetime
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))

# ── 資料設定 ─────────────────────────────────────────────────────────────────
FLOW_CACHE_PATH  = r"E:\claude code test\data\flow_cache.json"
MIN_FLOW_DAYS    = 5    # 至少 5 天投信買超才納入測試（24 天窗口）
MAX_TEST_SYMBOLS = 50   # 最多測試前 50 個股票（依籌碼日數排序，再隨機取樣以分散）
START_DATE = "2026-04-18"
END_DATE   = "2026-05-22"

# ── 掃描範圍 ──────────────────────────────────────────────────────────────────
FLOW_SCORE_THRESHOLDS = [0.40, 0.50, 0.55, 0.60, 0.65, 0.70]
ATR_MULTIPLIERS       = [1.5, 2.0, 2.5, 3.0]

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "backtest_results", "param_sweep.json")


def _select_symbols_from_cache() -> tuple[list[str], dict]:
    """從 flow_cache + daily_price_cache 選出有積極投信買超且流動性足夠的股票

    選股條件：
    1. 不是 ETF（不以 00 開頭）
    2. 投信連續買超最長天數 >= 2（策略 consecutive_trust_buy_days 門檻）
    3. 投信買超天數 >= MIN_FLOW_DAYS（在 flow_cache 期間至少 N 天）
    4. avg_daily_value >= 100M NTD（daily_price_cache 計算，volume 張×1000 換算為股）
    """
    with open(FLOW_CACHE_PATH, "r", encoding="utf-8") as f:
        fc = json.load(f)

    # Step 1: 從 daily_price_cache 計算各 symbol 的平均交易金額
    daily_cache_path = r"E:\claude code test\data\daily_price_cache.json"
    min_avg_value = 100_000_000  # 100M NTD（以股為單位）
    liquid_syms: set[str] = set()
    try:
        with open(daily_cache_path, "r", encoding="utf-8") as f2:
            dpc_raw = json.load(f2)
        for sym, dates_dict in dpc_raw.items():
            bars = sorted(dates_dict.values(), key=lambda b: b.get("date", ""))
            # 取最近 20 根計算，volume 張 → 股（×1000）
            vals = [b.get("close", 0) * b.get("volume", 0) * 1000
                    for b in bars[-20:] if isinstance(b, dict) and b.get("volume", 0) > 0]
            if len(vals) >= 5 and sum(vals) / len(vals) >= min_avg_value:
                liquid_syms.add(sym)
    except Exception as e:
        print(f"  警告：無法讀 daily_price_cache（{e}），流動性過濾停用")

    # Step 2: 從 flow_cache 找有積極投信買超的股票
    dates = sorted(fc.keys())
    all_syms: set[str] = set()
    for d in fc.values():
        all_syms.update(d.keys())

    candidates = []
    for sym in all_syms:
        if sym.startswith("00"):  # 排除 ETF
            continue
        streak = max_streak = trust_days = 0
        for d in dates:
            trust = 0
            if d in fc and sym in fc[d]:
                trust = int(fc[d][sym].get("investment_trust_net_buy", 0) or 0)
            if trust > 0:
                streak += 1
                trust_days += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        if max_streak >= 2 and trust_days >= MIN_FLOW_DAYS:
            # 優先選流動性 OK 的，但若無 daily_price_cache 資料也納入
            candidates.append((sym, trust_days, max_streak, sym in liquid_syms))

    # 流動性 OK 的排前面，再依投信買超天數降序
    candidates.sort(key=lambda x: (-int(x[3]), -x[1], -x[2], x[0]))
    selected = [sym for sym, _, _, _ in candidates[:MAX_TEST_SYMBOLS]]

    liquid_cnt = sum(1 for _, _, _, liq in candidates if liq)
    print(f"  flow_cache 涵蓋 {len(all_syms)} 個股票，daily_price_cache 流動性OK：{len(liquid_syms)} 個")
    print(f"  符合條件（連買≥2天、投信買≥{MIN_FLOW_DAYS}天）：{len(candidates)} 個（其中流動性OK：{liquid_cnt} 個）")
    print(f"  選取前 {len(selected)} 個：{', '.join(selected[:10])}{'...' if len(selected) > 10 else ''}")
    return selected, fc


def _fetch_bars(symbol: str, start: str, end: str):
    from historical_data import TWSEHistoricalFetcher
    print(f"  抓取 {symbol} 價格資料 {start}~{end} ...")
    fetcher = TWSEHistoricalFetcher()
    return fetcher.fetch_bars(symbol, start, end)


def _fetch_market_index(start: str, end: str) -> dict[str, float]:
    from historical_data import TWSEHistoricalFetcher
    fetcher = TWSEHistoricalFetcher()
    result = {}
    try:
        bars = fetcher.fetch_bars("0050", start, end)
        for b in bars:
            if b.previous_close and b.previous_close > 0:
                pct = (b.close - b.previous_close) / b.previous_close * 100
                dt = datetime.datetime.fromtimestamp(b.ts_ms / 1000, tz=_TZ_TW)
                result[dt.strftime("%Y-%m-%d")] = round(pct, 2)
    except Exception as e:
        print(f"  警告：無法抓 0050（{e}），大盤篩選停用")
    return result


def _build_flow_cache_from_local(symbol: str, fc_dict: dict):
    """僅使用本地 flow_cache.json 建立 InstitutionalFlowCache，不補抓 TWSE"""
    from institutional_flow_cache import InstitutionalFlowCache
    from institutional_flow_provider import InstitutionalFlowRow

    cache = InstitutionalFlowCache()
    loaded = 0

    for date_str, stocks in fc_dict.items():
        if symbol not in stocks:
            continue
        d = stocks[symbol]
        row = InstitutionalFlowRow(
            symbol=symbol,
            name=d.get("name", symbol),
            foreign_net_buy=int(d.get("foreign_net_buy", d.get("foreign_net", 0)) or 0),
            investment_trust_net_buy=int(d.get("investment_trust_net_buy", d.get("trust_net", 0)) or 0),
            major_net_buy=int(d.get("major_net_buy", d.get("major_net", 0)) or 0),
            avg_daily_volume_20d=d.get("avg_daily_volume_20d"),
        )
        cache.store(trade_date=date_str, rows=[row])
        loaded += 1

    return cache, loaded


def _make_trader(flow_score_threshold: float, atr_multiplier: float, flow_cache, account_capital: float):
    import retail_flow_strategy as rfs
    from auto_trader import AutoTrader
    from risk_manager import RiskManager

    rfs.MIN_ENTRY_FLOW_SCORE = flow_score_threshold

    risk = RiskManager(
        account_capital=account_capital,
        atr_multiplier=atr_multiplier,
    )
    return AutoTrader(
        telegram_token="",
        chat_id="",
        strategy_mode="retail_flow_swing",
        risk_manager=risk,
        slippage_multiplier=1.0,
        institutional_flow_cache=flow_cache,
    )


async def run_single(
    symbol: str,
    bars,
    market_index: dict,
    flow_cache,
    account_capital: float,
    flow_thresh: float,
    atr_mult: float,
    daily_price_cache=None,
) -> dict:
    from backtest import BacktestRunner

    flow_rows_by_date = {
        d: flow_cache.rows_for_date(d) for d in flow_cache.available_dates()
    }

    runner = BacktestRunner(
        auto_trader_factory=lambda: _make_trader(flow_thresh, atr_mult, flow_cache, account_capital)
    )
    result = await runner.run(
        bars=bars,
        market_index_by_date=market_index or None,
        flow_rows_by_date=flow_rows_by_date or None,
        daily_price_cache=daily_price_cache,
    )

    win_pnls  = [t["pnl"] for t in result.trade_records if t.get("pnl", 0) > 0]
    loss_pnls = [abs(t["pnl"]) for t in result.trade_records if t.get("pnl", 0) < 0]
    avg_win   = sum(win_pnls)  / len(win_pnls)  if win_pnls  else 0
    avg_loss  = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
    ev_r      = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    return {
        "symbol":      symbol,
        "flow_thresh": flow_thresh,
        "atr_mult":    atr_mult,
        "trades":      result.total_trades,
        "win_rate":    round(result.win_rate * 100, 1),
        "ev_r":        ev_r,
        "total_pnl":   round(result.total_pnl, 0),
        "avg_pnl":     round(result.avg_pnl_per_trade, 0),
        "max_dd":      result.max_drawdown_pct,
    }


def _load_daily_price_cache():
    """載入本地 daily_price_cache.json，供流動性過濾和 MA/ATR 計算使用"""
    from daily_price_cache import DailyPriceCache, DailyBar
    dpc = DailyPriceCache()
    cache_path = r"E:\claude code test\data\daily_price_cache.json"
    try:
        import json as _json
        with open(cache_path, "r", encoding="utf-8") as f:
            raw = _json.load(f)
        for sym, dates in raw.items():
            for date_str, bar in dates.items():
                dpc.add_bar(sym, DailyBar(
                    date=date_str,
                    open=bar.get("open", bar.get("close", 0)),
                    high=bar.get("high", bar.get("close", 0)),
                    low=bar.get("low", bar.get("close", 0)),
                    close=bar.get("close", 0),
                    volume=bar.get("volume", 0),
                ))
        total = sum(len(v) for v in raw.values())
        print(f"  載入 daily_price_cache：{len(raw)} 個股票，共 {total} 筆日線")
    except Exception as e:
        print(f"  警告：無法載入 daily_price_cache（{e}），流動性過濾可能全擋")
    return dpc


async def main():
    print("=" * 60)
    print("  參數掃描：flow_score 門檻 × ATR 停損倍數")
    print(f"  期間：{START_DATE} ~ {END_DATE}（僅用本地 flow_cache）")
    print("=" * 60)

    # 從 flow_cache 自動選股
    test_symbols, fc_dict = _select_symbols_from_cache()

    # 載入 daily_price_cache（供流動性過濾和技術指標使用）
    daily_price_cache = _load_daily_price_cache()

    # 抓取所有標的的 K 棒資料（每個 symbol 一次性呼叫，不會 rate-limit）
    symbol_bars = {}
    for sym in test_symbols:
        bars = _fetch_bars(sym, START_DATE, END_DATE)
        if not bars:
            print(f"  ⚠️ {sym} 無 K 棒資料，跳過")
            continue
        symbol_bars[sym] = bars

    print(f"\n抓取大盤（0050）...")
    market_index = _fetch_market_index(START_DATE, END_DATE)

    # 把 K 棒填入 daily_price_cache（確保流動性過濾可以計算 20 日均量值）
    # 注意：TWSEHistoricalFetcher 的 volume 單位是「張」，實盤 tick 是「股」
    # MIN_AVG_DAILY_VALUE_20D 以股為基準，填入時 volume × 1000 換算
    from daily_price_cache import DailyBar as _DailyBar
    _TZ = datetime.timezone(datetime.timedelta(hours=8))
    for sym, bars in symbol_bars.items():
        for b in bars:
            date_str = datetime.datetime.fromtimestamp(b.ts_ms / 1000, tz=_TZ).strftime("%Y-%m-%d")
            daily_price_cache.add_bar(sym, _DailyBar(
                date=date_str,
                open=b.open, high=b.high, low=b.low,
                close=b.close, volume=b.volume * 1000,  # 張 → 股
            ))

    # 從本地 flow_cache 建立每個 symbol 的 cache（無 TWSE API 呼叫）
    symbol_caches = {}
    for sym in symbol_bars:
        cache, loaded = _build_flow_cache_from_local(sym, fc_dict)
        symbol_caches[sym] = cache
        print(f"  {sym} 本地籌碼：{loaded} 天")

    if not symbol_bars:
        print("⚠️ 無有效股票資料，中止")
        return None, None

    all_rows = []
    combos = list(itertools.product(FLOW_SCORE_THRESHOLDS, ATR_MULTIPLIERS))
    print(f"\n開始掃描 {len(combos)} 種參數組合 × {len(symbol_bars)} 個股票...\n")

    combo_totals: dict[tuple, list] = {}

    for flow_thresh, atr_mult in combos:
        key = (flow_thresh, atr_mult)
        combo_totals[key] = []
        for sym, bars in symbol_bars.items():
            max_price = max(b.close for b in bars)
            account_capital = max(1_000_000, max_price * 1000 / 0.10)
            result = await run_single(
                sym, bars, market_index, symbol_caches[sym],
                account_capital, flow_thresh, atr_mult, daily_price_cache
            )
            combo_totals[key].append(result)
            all_rows.append(result)

    # 彙總各參數組合跨股票平均
    print("\n" + "=" * 70)
    print(f"{'flow_thresh':>12}  {'atr_mult':>8}  {'trades':>6}  {'win_rate':>8}  {'ev_R':>6}  {'avg_pnl':>8}  {'pass':>5}")
    print("-" * 70)

    best_params = None
    best_score  = -999

    for (flow_thresh, atr_mult), rows in sorted(combo_totals.items()):
        rows_with_trades = [r for r in rows if r["trades"] > 0]
        if not rows_with_trades:
            continue
        avg_wr   = sum(r["win_rate"] for r in rows_with_trades) / len(rows_with_trades)
        avg_evr  = sum(r["ev_r"]     for r in rows_with_trades) / len(rows_with_trades)
        avg_pnl  = sum(r["avg_pnl"]  for r in rows_with_trades) / len(rows_with_trades)
        total_tr = sum(r["trades"]   for r in rows_with_trades)
        passed   = avg_wr > 55 and avg_evr > 1.5
        flag     = "✅" if passed else "  "
        print(f"  {flow_thresh:>10.2f}  {atr_mult:>8.1f}  {total_tr:>6}  {avg_wr:>7.1f}%  {avg_evr:>6.2f}  {avg_pnl:>8,.0f}  {flag}")
        if passed:
            score = avg_wr * 0.5 + avg_evr * 10
            if score > best_score:
                best_score = score
                best_params = (flow_thresh, atr_mult)

    print("=" * 70)

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "run_at": datetime.datetime.now(tz=_TZ_TW).isoformat(),
            "start": START_DATE, "end": END_DATE,
            "symbols": list(symbol_bars.keys()),
            "results": all_rows,
            "best_params": {"flow_thresh": best_params[0], "atr_mult": best_params[1]} if best_params else None,
        }, f, ensure_ascii=False, indent=2)

    if best_params:
        flow_thresh, atr_mult = best_params
        print(f"\n✅ 最佳參數找到：flow_thresh={flow_thresh}  atr_mult={atr_mult}")
        print(f"   → 準備更新 retail_flow_strategy.py 和 risk_manager.py")
        return flow_thresh, atr_mult
    else:
        print("\n⚠️ 未找到符合條件的參數組合，需要進一步調整")
        return None, None


if __name__ == "__main__":
    asyncio.run(main())

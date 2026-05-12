# -*- coding: utf-8 -*-
"""
更新 daily_price_cache.json 至最新交易日。

策略：
- 讀取 cache 中所有標的的最新日期
- 用 Yahoo Finance 補抓缺少的交易日
- 同時補抓 flow_cache 中的熱門標的（確保籌碼候選有技術數據）
- 保留 cache 中已有資料，只新增新日期

使用：python scripts/update_price_cache.py
"""
from __future__ import annotations
import json, sys, time, datetime, threading
from queue import Queue, Empty
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PRICE_CACHE_PATH = "data/daily_price_cache.json"
FLOW_CACHE_PATH  = "data/flow_cache.json"
START_DATE = "2026-05-05"   # 補抓起始（cache 停在 05-04）
END_DATE   = "2026-05-12"   # 今日
WORKERS    = 6               # 並行執行緒數
DAILY_CACHE_MAX_DAYS = 60

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from historical_data import _fetch_yahoo_bars


def load_caches() -> tuple[dict, dict]:
    with open(PRICE_CACHE_PATH, encoding="utf-8") as f:
        price_cache = json.load(f)
    with open(FLOW_CACHE_PATH, encoding="utf-8") as f:
        flow_all = json.load(f)
    return price_cache, flow_all


def get_target_symbols(price_cache: dict, flow_all: dict) -> list[str]:
    """現有 cache 標的 + flow_cache 最新日期前 100 名熱門標的。"""
    existing = set(price_cache.keys())

    flow_date = sorted(flow_all.keys())[-1]
    rows = flow_all[flow_date]
    flow_syms = set()
    for sym, r in rows.items():
        trust = abs(r.get("investment_trust_net_buy", 0) or 0)
        foreign = abs(r.get("foreign_net_buy", 0) or 0)
        if trust + foreign > 500_000:
            flow_syms.add(sym)

    all_syms = existing | flow_syms
    # 過濾 ETF
    return [s for s in all_syms if not s.startswith("00")]


def needs_update(price_cache: dict, sym: str, end_date: str) -> bool:
    bars = price_cache.get(sym, {})
    if not bars:
        return True
    latest = sorted(bars.keys())[-1]
    return latest < end_date


def fetch_and_update(sym: str, price_cache: dict, lock: threading.Lock) -> bool:
    try:
        bars = _fetch_yahoo_bars(sym, START_DATE, END_DATE)
        if not bars:
            return False
        with lock:
            if sym not in price_cache:
                price_cache[sym] = {}
            for b in bars:
                date_str = datetime.datetime.fromtimestamp(
                    b.ts_ms / 1000,
                    tz=datetime.timezone(datetime.timedelta(hours=8))
                ).strftime("%Y-%m-%d")
                price_cache[sym][date_str] = {
                    "date": date_str,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
            # 修剪超過 60 天的舊資料
            dates = sorted(price_cache[sym].keys())
            if len(dates) > DAILY_CACHE_MAX_DAYS:
                for old in dates[:-DAILY_CACHE_MAX_DAYS]:
                    del price_cache[sym][old]
        return True
    except Exception:
        return False


def worker(queue: Queue, price_cache: dict, lock: threading.Lock,
           counters: dict, print_lock: threading.Lock) -> None:
    while True:
        try:
            sym = queue.get_nowait()
        except Empty:
            break
        ok = fetch_and_update(sym, price_cache, lock)
        with print_lock:
            if ok:
                counters["ok"] += 1
            else:
                counters["skip"] += 1
            total = counters["ok"] + counters["skip"]
            if total % 50 == 0:
                print(f"  進度 {total}/{counters['total']}  成功 {counters['ok']} 跳過 {counters['skip']}")
        queue.task_done()
        time.sleep(0.1)


def main() -> None:
    print(f"更新 price cache → {START_DATE} 至 {END_DATE}")
    price_cache, flow_all = load_caches()

    all_syms = get_target_symbols(price_cache, flow_all)
    to_update = [s for s in all_syms if needs_update(price_cache, s, END_DATE)]
    skip_count = len(all_syms) - len(to_update)

    print(f"總標的 {len(all_syms)}，需更新 {len(to_update)}，已是最新 {skip_count}")
    print(f"使用 {WORKERS} 個並行執行緒...")

    queue: Queue = Queue()
    for s in to_update:
        queue.put(s)

    lock = threading.Lock()
    print_lock = threading.Lock()
    counters = {"ok": 0, "skip": 0, "total": len(to_update)}

    threads = [
        threading.Thread(
            target=worker,
            args=(queue, price_cache, lock, counters, print_lock),
            daemon=True,
        )
        for _ in range(WORKERS)
    ]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    elapsed = time.time() - t0
    print(f"\n完成：成功 {counters['ok']}，無資料 {counters['skip']}，耗時 {elapsed:.0f}s")

    # 驗證
    sample = ["2344", "2303", "2337", "2330"]
    print("\n抽查最新日期：")
    for sym in sample:
        bars = price_cache.get(sym, {})
        if bars:
            latest = sorted(bars.keys())[-1]
            c = bars[latest].get("close", "N/A")
            print(f"  {sym}: {latest}  close={c}")

    print("\n寫入 cache...")
    with open(PRICE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(price_cache, f, ensure_ascii=False)
    print("完成。")


if __name__ == "__main__":
    main()

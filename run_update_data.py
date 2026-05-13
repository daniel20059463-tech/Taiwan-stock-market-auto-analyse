# -*- coding: utf-8 -*-
"""
盤後資料更新：14:30 由工作排程器執行

功能：
1. 更新 daily_price_cache.json 至今日收盤
2. 自動設定更新範圍（cache 最新日 → 今日）
"""
from __future__ import annotations
import json, sys, time, datetime, threading
from queue import Queue, Empty
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
sys.path.insert(0, os.path.dirname(__file__))
from historical_data import _fetch_yahoo_bars

PRICE_CACHE_PATH = "data/daily_price_cache.json"
FLOW_CACHE_PATH  = "data/flow_cache.json"
DAILY_CACHE_MAX_DAYS = 60
WORKERS = 6
TZ_TW   = datetime.timezone(datetime.timedelta(hours=8))


def main() -> None:
    today = datetime.datetime.now(tz=TZ_TW).strftime("%Y-%m-%d")

    with open(PRICE_CACHE_PATH, encoding="utf-8") as f:
        price_cache = json.load(f)
    with open(FLOW_CACHE_PATH, encoding="utf-8") as f:
        flow_all = json.load(f)

    # 找出需要更新的起始日
    all_latest = [sorted(v.keys())[-1] for v in price_cache.values() if v]
    start_date = min(all_latest) if all_latest else today

    # 已是最新就跳過
    if start_date >= today:
        print(f"Price cache 已是最新（{today}），跳過。")
        return

    # 取得所有需更新標的
    existing  = set(price_cache.keys())
    flow_date = sorted(flow_all.keys())[-1]
    flow_syms = {
        sym for sym, r in flow_all[flow_date].items()
        if abs(r.get("investment_trust_net_buy", 0) or 0) > 200_000
    }
    all_syms  = [s for s in existing | flow_syms if not s.startswith("00")]
    to_update = [s for s in all_syms
                 if not price_cache.get(s) or sorted(price_cache[s].keys())[-1] < today]

    print(f"更新 {start_date} → {today}，共 {len(to_update)} 檔")

    queue: Queue = Queue()
    for s in to_update:
        queue.put(s)

    lock       = threading.Lock()
    print_lock = threading.Lock()
    counters   = {"ok": 0, "skip": 0, "total": len(to_update)}

    def worker() -> None:
        while True:
            try:
                sym = queue.get_nowait()
            except Empty:
                break
            try:
                bars = _fetch_yahoo_bars(sym, start_date, today)
                if bars:
                    with lock:
                        if sym not in price_cache:
                            price_cache[sym] = {}
                        for b in bars:
                            dt = datetime.datetime.fromtimestamp(
                                b.ts_ms / 1000,
                                tz=datetime.timezone(datetime.timedelta(hours=8))
                            ).strftime("%Y-%m-%d")
                            price_cache[sym][dt] = {
                                "date": dt, "open": b.open, "high": b.high,
                                "low": b.low, "close": b.close, "volume": b.volume,
                            }
                        dates = sorted(price_cache[sym].keys())
                        for old in dates[:-DAILY_CACHE_MAX_DAYS]:
                            del price_cache[sym][old]
                    with print_lock:
                        counters["ok"] += 1
                else:
                    with print_lock:
                        counters["skip"] += 1
            except Exception:
                with print_lock:
                    counters["skip"] += 1
            queue.task_done()
            time.sleep(0.1)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"完成：成功 {counters['ok']}，無資料 {counters['skip']}，耗時 {time.time()-t0:.0f}s")

    with open(PRICE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(price_cache, f, ensure_ascii=False)
    print("Price cache 已寫入。")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
trading_agent.py（別名：scan_tomorrow_signals.py）

自主掃描隔日多/空訊號。判斷邏輯：
  1. 籌碼分數（投信/外資買超強度）
  2. 技術指標（MA10 站上/跌破、RSI、近期動能）
  3. 產業過濾（排除金融、營建、旅遊、食品、傳產）
  4. 不依賴新聞，完全由數據驅動

使用：python scripts/scan_tomorrow_signals.py
"""
from __future__ import annotations
import json, sys, time, math, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CAPITAL = 1_000_000
MAX_POSITION_PCT = 0.20
TRUST_LONG_MIN  = 200_000   # 投信淨買 >= 20萬股
TRUST_SHORT_MIN = -300_000  # 投信淨賣 <= -30萬股
RSI_OVERSOLD  = 40
RSI_OVERBOUGHT = 70

# ── 排除產業（依股票代號前綴 / 已知清單）────────────────
EXCLUDED_SECTORS = {
    # 金融股
    "2801","2809","2812","2816","2820","2823","2824","2825","2826","2827",
    "2828","2829","2830","2831","2832","2834","2836","2837","2838","2841",
    "2842","2845","2847","2849","2850","2851","2852","2855","2856","2857",
    "2880","2881","2882","2883","2884","2885","2886","2887","2888","2889",
    "2890","2891","2892","2893","2894","2895","2897","2898","2899","5880",
    "6005","6008","6016","6020","6023","6024","6026","6012",
    # 營建
    "2501","2502","2503","2504","2505","2506","2507","2509","2511","2512",
    "2515","2516","2520","2521","2524","2527","2528","2530","2534","2536",
    "2537","2538","2539","2540","2542","2543","2545","2547","2548","2551",
    "2552","2555","2556","2557","2561","5522","5534","5560",
    # 旅遊/觀光
    "2601","2602","2603","2605","2606","2607","2608","2609","2610","2611",
    "2612","2613","2614","2615","2616","2617","2618","2636","5905",
    "2722","2723","2724","2726","2727","2729","2731","2732",
    # 食品
    "1201","1203","1204","1210","1213","1215","1216","1217","1218","1219",
    "1220","1221","1222","1223","1225","1227","1229","1230","1231","1232",
    "1233","1234","1235","1236","1702","4205","4207","4208","4210","4219",
    # 傳產（紡織/橡膠/化工/汽車/鋼鐵）
    "1301","1303","1304","1305","1307","1308","1309","1310","1313","1314",
    "1315","1319","1321","1323","1324","1325","1326","1401","1402","1403",
    "1404","1405","1406","1408","1409","1410","1413","1414","1416","1417",
    "1418","1419","1421","1423","1424","1425","1426","1429","1431","1434",
    "1435","1436","1437","1438","1439","1440","1441","1442","1443","1444",
    "1445","1446","1447","1449","1451","1452","1453","1454","1455","1456",
    "1457","1459","1460","1461","1462","1463","1464","1465","1466","1467",
    "1468","1469","1470","1471","1472","1473","1474","1475","1476","1477",
    "1503","1504","1507","1512","1513","1514","1515","1516","1517","1519",
    "1521","1522","1523","1524","1525","1526","1527","1528","1529","1530",
    "1531","1532","1533","1534","1535","1536","1537","1538","1539","1540",
    "1541","1542","1543","1544","1545","1546","1547","1548","1549","1550",
    "2002","2006","2007","2008","2010","2011","2012","2013","2014","2015",
    "2016","2017","2018","2019","2020","2022","2023","2024","2025","2026",
    "2027","2028","2029","2030","2031","2032","2033","2034","2035","2038",
    "2041","2042","2043","2044","2045","2048","2049","2050","2059","2062",
    "2063","2064","2065","2066","2067","2068","2069","2101","2102","2103",
    "2104","2105","2106","2107","2108","2109","2114","2115","2116","2117",
    "2118","2119","2121","2123","2125","2126","2127","2128","2129","2130",
    "2201","2202","2203","2204","2205","2206","2207","2208","2209","2210",
    "2211","2212","2213","2214","2215","2216","2217","2219","2220","2221",
    "2222","2223","2224","2227","2228","2229","2230","2231","2233","2235",
    "2236","2237","2238","2239","2240","2241","2243","2244","2245",
}

# ── 工具函數 ──────────────────────────────────────────────
def calc_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-period - 1 + i] - closes[-period - 1 + i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)

def calc_ma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n

def fetch_yahoo_close(sym: str) -> float | None:
    ticker = sym + ".TW"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        return next((v for v in reversed(closes) if v is not None), None)
    except Exception:
        return None

def score_long(trust: float, foreign: float, dealer: float,
               close: float, ma10: float, rsi: float | None) -> float:
    """0~1 分，越高越值得做多。"""
    s = 0.0
    # 籌碼 (權重 60%)
    max_trust = 5_000_000
    s += min(trust / max_trust, 1.0) * 0.35
    s += min(max(foreign, 0) / 20_000_000, 1.0) * 0.25
    # 技術 (40%)
    if close > ma10:
        s += 0.20
    if rsi is not None:
        if 50 <= rsi <= RSI_OVERBOUGHT:
            s += 0.20
        elif rsi < 50:
            s += max(0, (rsi - RSI_OVERSOLD) / 10) * 0.10
    return round(s, 3)

def score_short(trust: float, foreign: float, dealer: float,
                close: float, ma10: float, rsi: float | None) -> float:
    s = 0.0
    s += min(abs(min(trust, 0)) / 3_000_000, 1.0) * 0.35
    s += min(abs(min(foreign, 0)) / 10_000_000, 1.0) * 0.25
    if close < ma10:
        s += 0.20
    if rsi is not None and rsi > RSI_OVERBOUGHT:
        s += 0.20
    elif rsi is not None and rsi < 40:
        s += 0.10
    return round(s, 3)

# ── 主流程 ───────────────────────────────────────────────
with open("data/flow_cache.json", encoding="utf-8") as f:
    flow_all = json.load(f)
flow_date = sorted(flow_all.keys())[-1]
rows = flow_all[flow_date]

with open("data/daily_price_cache.json", encoding="utf-8") as f:
    price_cache = json.load(f)

long_candidates, short_candidates = [], []

for sym, r in rows.items():
    if sym in EXCLUDED_SECTORS:
        continue
    if sym.startswith("00"):  # ETF
        continue
    trust   = r.get("investment_trust_net_buy", 0) or 0
    foreign = r.get("foreign_net_buy", 0) or 0
    dealer  = r.get("dealer_net_buy", 0) or 0

    # 取技術數據（優先用 price_cache）
    sym_bars = price_cache.get(sym, {})
    if sym_bars:
        dates = sorted(sym_bars.keys())
        closes_hist = [sym_bars[d]["close"] for d in dates if sym_bars[d].get("close")]
    else:
        closes_hist = []

    current = closes_hist[-1] if closes_hist else None
    ma10 = calc_ma(closes_hist, 10) if closes_hist else None
    rsi = calc_rsi(closes_hist, 14) if closes_hist else None

    if trust >= TRUST_LONG_MIN and current and ma10:
        sc = score_long(trust, foreign, dealer, current, ma10, rsi)
        long_candidates.append((sym, trust, foreign, dealer, current, ma10, rsi, sc))

    if trust <= TRUST_SHORT_MIN and current and ma10:
        sc = score_short(trust, foreign, dealer, current, ma10, rsi)
        short_candidates.append((sym, trust, foreign, dealer, current, ma10, rsi, sc))

long_candidates.sort(key=lambda x: x[7], reverse=True)
short_candidates.sort(key=lambda x: x[7], reverse=True)

# ── 抓最新收盤（Yahoo，限 Top 10）────────────────────────
print(f"掃描完成。多單候選 {len(long_candidates)} 檔，空單候選 {len(short_candidates)} 檔")
print(f"籌碼日期：{flow_date}\n")

def enrich_with_yahoo(candidates: list, top_n: int = 10) -> list:
    enriched = []
    for row in candidates[:top_n]:
        sym = row[0]
        live = fetch_yahoo_close(sym)
        enriched.append((*row, live))
        time.sleep(0.25)
    return enriched

long_top = enrich_with_yahoo(long_candidates)
short_top = enrich_with_yahoo(short_candidates)

# ── 輸出 ─────────────────────────────────────────────────
tomorrow = "明日開盤"
print("=" * 60)
print(f"  {tomorrow} 交易信號 | 資金 {CAPITAL:,} 元")
print("=" * 60)

print(f"\n【多單 TOP10】（得分 = 籌碼60% + 技術40%）")
for sym, trust, foreign, dealer, cur, ma10, rsi, sc, live in long_top:
    price = live or cur
    if not price:
        continue
    budget = int(CAPITAL * MAX_POSITION_PCT)
    lots = budget // int(price * 1000)
    stop_est = round(price * 0.955, 2)
    target_est = round(price * 1.085, 2)
    above_ma = "MA10上方" if cur and ma10 and cur > ma10 else "MA10下方"
    rsi_str = f"RSI{rsi}" if rsi else "RSI-"
    print(f"  {sym}  得分{sc:.2f}  {price:.1f}元  投信{trust/1000:+,.0f}k  外資{foreign/1000:+,.0f}k"
          f"  {above_ma} {rsi_str}  建議{lots}張  停{stop_est}→目標{target_est}")

print(f"\n【空單 TOP10】（需融券）")
for sym, trust, foreign, dealer, cur, ma10, rsi, sc, live in short_top:
    price = live or cur
    if not price:
        continue
    rsi_str = f"RSI{rsi}" if rsi else "RSI-"
    below_ma = "MA10下方" if cur and ma10 and cur < ma10 else "MA10上方"
    stop_est = round(price * 1.04, 2)
    target_est = round(price * 0.92, 2)
    print(f"  {sym}  得分{sc:.2f}  {price:.1f}元  投信{trust/1000:+,.0f}k  外資{foreign/1000:+,.0f}k"
          f"  {below_ma} {rsi_str}  停{stop_est}→目標{target_est}")

print("\n---")
print("說明：得分由籌碼+技術純量化計算，非新聞驅動。")
print("MA10/RSI 使用 daily_price_cache；若 cache 無資料則只看籌碼。")
print("開盤後由 trading agent 依即時價確認是否執行。")

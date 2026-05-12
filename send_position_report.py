# -*- coding: utf-8 -*-
"""持倉盤後報告：讀取 paper_positions.json 和最新價格，推播 Telegram。"""
from __future__ import annotations
import json, os, sys, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

with open("data/paper_positions.json", encoding="utf-8") as f:
    pos_data = json.load(f)

with open("data/flow_cache.json", encoding="utf-8") as f:
    flow = json.load(f)

with open("data/daily_price_cache.json", encoding="utf-8") as f:
    price_cache = json.load(f)

positions = pos_data.get("positions", {})
date_raw = pos_data.get("trade_date", "")
date_label = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}" if len(date_raw) == 8 else date_raw
capital = pos_data.get("capital_total", 1_000_000)

# 最新籌碼日期
flow_date = sorted(flow.keys())[-1]

lines = [f"持倉日報 | {date_label} 盤後", ""]

long_pos = [(s, p) for s, p in positions.items() if p.get("side", "long") == "long"]
short_pos = [(s, p) for s, p in positions.items() if p.get("side") == "short"]

def get_current_price(sym: str, entry_price: float) -> tuple[float, float, float]:
    """回傳 (current, ma10, resist20)"""
    sym_bars = price_cache.get(sym, {})
    if sym_bars:
        recent = sorted(sym_bars.keys())[-20:]
        closes = [sym_bars[d]["close"] for d in recent if "close" in sym_bars[d]]
        current = closes[-1] if closes else entry_price
        ma10 = sum(closes[-10:]) / len(closes[-10:]) if len(closes) >= 10 else entry_price
        highs = [sym_bars[d].get("high", 0) for d in recent]
        resist = max(highs) if highs else entry_price
    else:
        current, ma10, resist = entry_price, entry_price, entry_price
    return current, ma10, resist

if long_pos:
    lines.append("【多單持倉】")
    for sym, pos in long_pos:
        entry = pos["entry_price"]
        shares = pos["shares"]
        lots = shares // 1000
        stop = pos.get("trail_stop_price", pos["stop_price"])
        target = pos["target_price"]
        name = pos.get("name", sym)
        current, ma10, resist = get_current_price(sym, entry)
        pnl = (current - entry) * shares
        pnl_pct = (current - entry) / entry * 100

        # 籌碼
        flow_row = flow.get(flow_date, {}).get(sym, {})
        trust = flow_row.get("investment_trust_net_buy", 0) or 0
        foreign = flow_row.get("foreign_net_buy", 0) or 0
        reason = pos.get("entry_reason", "")

        lines += [
            f"  {sym} {name}  多單",
            f"  買入價格 : {entry:.2f} 元　{lots} 張",
            f"  進場原因 : {reason}",
            f"  目前價格 : {current:.2f} 元　浮盈 {pnl:+,.0f} 元（{pnl_pct:+.2f}%）",
            f"  目標賣出 : {target:.2f} 元",
            f"  追蹤停損 : {stop:.2f} 元",
            f"  支撐     : {ma10:.1f} 元（MA10）",
            f"  壓力     : {resist:.1f} 元（近20日高點）",
            f"  最新籌碼 : 投信 {trust/1000:+,.0f}k　外資 {foreign/1000:+,.0f}k ({flow_date})",
            "",
        ]

if short_pos:
    lines.append("【空單持倉】")
    for sym, pos in short_pos:
        entry = pos["entry_price"]
        shares = pos["shares"]
        lots = shares // 1000
        stop = pos.get("trail_stop_price", pos["stop_price"])
        target = pos["target_price"]
        name = pos.get("name", sym)
        current, ma10, _ = get_current_price(sym, entry)
        pnl = (entry - current) * shares
        pnl_pct = (entry - current) / entry * 100

        flow_row = flow.get(flow_date, {}).get(sym, {})
        trust = flow_row.get("investment_trust_net_buy", 0) or 0
        foreign = flow_row.get("foreign_net_buy", 0) or 0
        reason = pos.get("entry_reason", "")

        lines += [
            f"  {sym} {name}  空單",
            f"  放空價格 : {entry:.2f} 元　{lots} 張",
            f"  進場原因 : {reason}",
            f"  目前價格 : {current:.2f} 元　浮盈 {pnl:+,.0f} 元（{pnl_pct:+.2f}%）",
            f"  目標回補 : {target:.2f} 元",
            f"  追蹤停損 : {stop:.2f} 元",
            f"  最新籌碼 : 投信 {trust/1000:+,.0f}k　外資 {foreign/1000:+,.0f}k ({flow_date})",
            "",
        ]

lines.append("---")
lines.append(f"起始資金 {capital:,} 元　已動用 {pos_data.get('capital_deployed',0):,} 元　現金 {pos_data.get('capital_cash',0):,} 元")

msg = "\n".join(lines)
print(msg)

payload = json.dumps({"chat_id": CHAT_ID, "text": msg}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    data=payload,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as resp:
    result = json.load(resp)
    print("Telegram OK" if result.get("ok") else f"ERROR: {result}")

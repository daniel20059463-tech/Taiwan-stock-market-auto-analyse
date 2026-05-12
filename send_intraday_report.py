# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os, sys, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

with open("data/paper_positions.json", encoding="utf-8") as f:
    pos_data = json.load(f)

positions = pos_data.get("positions", {})
capital = pos_data.get("capital_total", 1_000_000)
deployed = pos_data.get("capital_deployed", 0)
cash = pos_data.get("capital_cash", capital)
date_label = pos_data.get("trade_date", "")
date_str = f"{date_label[:4]}-{date_label[4:6]}-{date_label[6:]}"

lines = [
    f"模擬交易 盤中建倉報告 | {date_str}",
    f"起始資金：{capital:,} 元　已動用：{deployed:,} 元（{deployed/capital*100:.1f}%）　現金：{cash:,} 元",
    "",
]

long_positions = [(s, p) for s, p in positions.items() if p["side"] == "long"]
short_positions = [(s, p) for s, p in positions.items() if p["side"] == "short"]

if long_positions:
    lines.append("【多單持倉】")
    for sym, pos in long_positions:
        entry = pos["entry_price"]
        shares = pos["shares"]
        lots = shares // 1000
        stop = pos["stop_price"]
        target = pos["target_price"]
        name = pos.get("name", sym)
        reason = pos.get("entry_reason", "")
        risk = round((entry - stop) / entry * 100, 1)
        reward = round((target - entry) / entry * 100, 1)
        budget = entry * shares
        lines += [
            f"  {sym} {name}  多單",
            f"  買入價格 : {entry:.2f} 元　{lots} 張（{budget:,.0f} 元）",
            f"  進場原因 : {reason}",
            f"  目標賣出 : {target:.2f} 元（+{reward}%）",
            f"  停損     : {stop:.2f} 元（-{risk}%）",
            "",
        ]

if short_positions:
    lines.append("【空單持倉】")
    for sym, pos in short_positions:
        entry = pos["entry_price"]
        shares = pos["shares"]
        lots = shares // 1000
        stop = pos["stop_price"]
        target = pos["target_price"]
        name = pos.get("name", sym)
        reason = pos.get("entry_reason", "")
        risk = round((stop - entry) / entry * 100, 1)
        reward = round((entry - target) / entry * 100, 1)
        budget = entry * shares
        lines += [
            f"  {sym} {name}  空單",
            f"  放空價格 : {entry:.2f} 元　{lots} 張（{budget:,.0f} 元）",
            f"  進場原因 : {reason}",
            f"  目標回補 : {target:.2f} 元（-{reward}%）",
            f"  停損     : {stop:.2f} 元（+{risk}%）",
            "",
        ]

lines.append("---")
lines.append("策略：多強空弱，籌碼+新聞+技術三重確認")
lines.append("所有操作為模擬（Paper Trading），非真實下單")

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

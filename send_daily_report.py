# -*- coding: utf-8 -*-
"""盤後日報：讀取最新 flow_cache 日期，自動產生三大法人籌碼摘要並推播 Telegram。"""
from __future__ import annotations
import json, os, sys, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

with open("data/flow_cache.json", encoding="utf-8") as f:
    flow = json.load(f)

# 自動使用最新日期
date_label = sorted(flow.keys())[-1]
rows = flow.get(date_label, {})

combined = []
for sym, r in rows.items():
    trust = r.get("investment_trust_net_buy", 0) or 0
    foreign = r.get("foreign_net_buy", 0) or 0
    dealer = r.get("dealer_net_buy", 0) or 0
    combined.append((sym, trust, foreign, dealer))

top_trust = sorted(combined, key=lambda x: x[1], reverse=True)[:8]
top_foreign = sorted(combined, key=lambda x: x[2], reverse=True)[:8]
sell_trust = sorted(combined, key=lambda x: x[1])[:5]
both_buy = sorted(
    [(sym, t, f, d) for sym, t, f, d in combined if t > 500_000 and f > 500_000],
    key=lambda x: x[1] + x[2],
    reverse=True,
)[:6]

lines = [f"盤後日報 | {date_label}", ""]

lines.append("【投信買超 TOP8】")
for sym, t, f, d in top_trust:
    tag = "  外資同買" if f > 0 else ""
    lines.append(f"  {sym}  投信 {t/1000:+,.0f}k{tag}")

lines += ["", "【外資買超 TOP8】"]
for sym, t, f, d in top_foreign:
    tag = "  投信同買" if t > 0 else ""
    lines.append(f"  {sym}  外資 {f/1000:+,.0f}k{tag}")

lines += ["", "【投信大賣 TOP5】"]
for sym, t, f, d in sell_trust:
    lines.append(f"  {sym}  投信 {t/1000:+,.0f}k  外資 {f/1000:+,.0f}k")

if both_buy:
    lines += ["", "【投信+外資雙買超（策略關注）】"]
    for sym, t, f, d in both_buy:
        lines.append(f"  {sym}  投信 {t/1000:+,.0f}k  外資 {f/1000:+,.0f}k")

lines += ["", "---", "資料來源：flow_cache.json"]

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

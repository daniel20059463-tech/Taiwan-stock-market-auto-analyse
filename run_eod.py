# -*- coding: utf-8 -*-
"""
盤後收工：14:00 由工作排程器執行

功能：
1. 用當日收盤價更新所有持倉的浮盈
2. 推播持倉日報（含支撐/壓力）
3. 推播籌碼日報（三大法人摘要）
"""
from __future__ import annotations
import json, os, sys, urllib.request, datetime, time

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_PATH = os.path.join(_LOG_DIR, f"eod_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

class _Tee:
    def __init__(self, *streams):
        self._streams = streams
    def write(self, data):
        for s in self._streams:
            try: s.write(data); s.flush()
            except Exception: pass
    def flush(self):
        for s in self._streams:
            try: s.flush()
            except Exception: pass
    def reconfigure(self, **kwargs):
        pass

_log_file = open(_LOG_PATH, "w", encoding="utf-8", buffering=1)
sys.stdout = _Tee(sys.__stdout__, _log_file)
sys.stderr = _Tee(sys.__stderr__, _log_file)
sys.__stdout__.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
TODAY = datetime.datetime.now(tz=TZ_TW).strftime("%Y-%m-%d")


def fetch_close(sym: str) -> float | None:
    for suffix in (".TW", ".TWO"):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}{suffix}?interval=1d&range=5d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return next((v for v in reversed(closes) if v is not None), None)
        except Exception:
            continue
    return None


def send_telegram(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        return
    payload = json.dumps({"chat_id": CHAT_ID, "text": text},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        json.load(r)


def build_position_report(pos_data: dict, price_cache: dict, flow_all: dict) -> str:
    positions = pos_data.get("positions", {})
    capital   = pos_data.get("capital_total", 1_000_000)
    deployed  = pos_data.get("capital_deployed", 0)
    cash      = pos_data.get("capital_cash", capital)
    date_raw  = pos_data.get("trade_date", "")
    date_str  = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}" if len(date_raw) == 8 else date_raw
    flow_date = sorted(flow_all.keys())[-1]

    lines = [f"持倉日報 | {TODAY} 盤後", ""]

    if not positions:
        lines.append("目前無持倉，現金 100%")
        lines.append(f"資金：{capital:,} 元")
        return "\n".join(lines)

    for sym, pos in positions.items():
        entry  = pos["entry_price"]
        shares = pos["shares"]
        lots   = shares // 1000
        side   = pos.get("side", "long")
        stop   = pos.get("trail_stop_price", pos["stop_price"])
        target = pos["target_price"]
        name   = pos.get("name", sym)
        reason = pos.get("entry_reason", "")

        # 最新收盤：cache 有今日資料才用，否則一律抓 Yahoo 確保價格正確
        sym_bars = price_cache.get(sym, {})
        cache_latest = sorted(sym_bars.keys())[-1] if sym_bars else ""
        if sym_bars and cache_latest >= TODAY:
            recent = sorted(sym_bars.keys())[-20:]
            closes = [sym_bars[d]["close"] for d in recent if sym_bars[d].get("close")]
            current = closes[-1] if closes else entry
            ma10    = sum(closes[-10:]) / len(closes[-10:]) if len(closes) >= 10 else None
            highs   = [sym_bars[d].get("high", 0) for d in recent]
            resist  = max(highs) if highs else target
            support = ma10 or stop
        else:
            # cache 沒有今日資料，直接抓 Yahoo 即時收盤
            current = fetch_close(sym) or entry
            if sym_bars:
                recent = sorted(sym_bars.keys())[-20:]
                closes = [sym_bars[d]["close"] for d in recent if sym_bars[d].get("close")]
                closes.append(current)  # 補上今日
                ma10   = sum(closes[-10:]) / len(closes[-10:]) if len(closes) >= 10 else None
                highs  = [sym_bars[d].get("high", 0) for d in recent]
                resist = max(highs) if highs else target
                support = ma10 or stop
            else:
                ma10, resist, support = None, target, stop

        if side == "long":
            pnl     = (current - entry) * shares
            pnl_pct = (current - entry) / entry * 100
        else:
            pnl     = (entry - current) * shares
            pnl_pct = (entry - current) / entry * 100

        # 籌碼
        flow_row = flow_all.get(flow_date, {}).get(sym, {})
        trust   = flow_row.get("investment_trust_net_buy", 0) or 0
        foreign = flow_row.get("foreign_net_buy", 0) or 0

        dir_tag = "多" if side == "long" else "空"
        lines += [
            f"【{sym} {name}】{dir_tag}單",
            f"  買入價格 : {entry:.2f} 元　{lots} 張",
            f"  進場原因 : {reason}",
            f"  目前價格 : {current:.2f} 元  浮盈 {pnl:+,.0f} 元（{pnl_pct:+.2f}%）",
            f"  目標     : {target:.2f} 元",
            f"  追蹤停損 : {stop:.2f} 元",
            f"  支撐     : {support:.1f} 元（MA10）" if ma10 else f"  停損     : {stop:.2f} 元",
            f"  壓力     : {resist:.1f} 元（近20日高點）",
            f"  最新籌碼 : 投信 {trust/1000:+,.0f}k  外資 {foreign/1000:+,.0f}k ({flow_date})",
            "",
        ]

    lines += [
        "---",
        f"資金 {capital:,}　已動用 {deployed:,}　現金 {cash:,}",
    ]
    return "\n".join(lines)


def build_flow_report(flow_all: dict) -> str:
    date_label = sorted(flow_all.keys())[-1]
    rows = flow_all.get(date_label, {})
    combined = [
        (sym,
         r.get("investment_trust_net_buy", 0) or 0,
         r.get("foreign_net_buy", 0) or 0,
         r.get("dealer_net_buy", 0) or 0)
        for sym, r in rows.items()
    ]
    top_trust   = sorted(combined, key=lambda x: x[1], reverse=True)[:8]
    sell_trust  = sorted(combined, key=lambda x: x[1])[:5]
    both_buy    = sorted(
        [(s, t, f, d) for s, t, f, d in combined if t > 500_000 and f > 500_000],
        key=lambda x: x[1] + x[2], reverse=True
    )[:5]

    lines = [f"籌碼日報 | {date_label}", "", "【投信買超 TOP8】"]
    for sym, t, f, d in top_trust:
        tag = "  外資同買" if f > 0 else ""
        lines.append(f"  {sym}  投信 {t/1000:+,.0f}k{tag}")
    lines += ["", "【投信大賣 TOP5】"]
    for sym, t, f, d in sell_trust:
        lines.append(f"  {sym}  投信 {t/1000:+,.0f}k  外資 {f/1000:+,.0f}k")
    if both_buy:
        lines += ["", "【投信+外資雙買超】"]
        for sym, t, f, d in both_buy:
            lines.append(f"  {sym}  投信 {t/1000:+,.0f}k  外資 {f/1000:+,.0f}k")
    return "\n".join(lines)


def main() -> None:
    with open("data/paper_positions.json", encoding="utf-8") as f:
        pos_data = json.load(f)
    with open("data/daily_price_cache.json", encoding="utf-8") as f:
        price_cache = json.load(f)
    with open("data/flow_cache.json", encoding="utf-8") as f:
        flow_all = json.load(f)

    pos_report = build_position_report(pos_data, price_cache, flow_all)

    print(pos_report)
    send_telegram(pos_report)
    print("盤後報告推播完成。")


if __name__ == "__main__":
    main()

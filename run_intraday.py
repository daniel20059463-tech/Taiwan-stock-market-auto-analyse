# -*- coding: utf-8 -*-
"""
盤中監控：每 30 分鐘由工作排程器執行（09:30 / 10:00 / ... / 13:00）

功能：
- 抓每個持倉的最新 Yahoo Finance 延遲報價
- 更新追蹤停損（trail stop）
- 觸發停損 / 達到目標 → 平倉 + 推播 Telegram
- 無操作時安靜結束，只有異動時才推播
"""
from __future__ import annotations
import json, os, sys, urllib.request, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

POSITIONS_PATH = "data/paper_positions.json"
TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
NOW   = datetime.datetime.now(tz=TZ_TW)
NOW_STR = NOW.strftime("%H:%M")

TRAIL_PCT  = 0.035   # 追蹤停損距離 3.5%（以最高價計）
SHORT_TRAIL_PCT = 0.035


def fetch_price(sym: str) -> float | None:
    for suffix in (".TW", ".TWO"):
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}{suffix}"
               f"?interval=1m&range=1d")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            price = next((v for v in reversed(closes) if v is not None), None)
            if price:
                return round(price, 2)
        except Exception:
            continue
    return None


def send_telegram(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram 憑證未設定")
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


def main() -> None:
    with open(POSITIONS_PATH, encoding="utf-8") as f:
        pos_data = json.load(f)

    positions: dict = pos_data.get("positions", {})
    if not positions:
        print(f"[{NOW_STR}] 無持倉，結束。")
        return

    alerts: list[str] = []
    closed_syms: list[str] = []
    capital = pos_data.get("capital_total", 1_000_000)
    deployed = pos_data.get("capital_deployed", 0)
    cash = pos_data.get("capital_cash", capital)

    for sym, pos in list(positions.items()):
        price = fetch_price(sym)
        if price is None:
            print(f"  {sym}: 無法取得價格")
            continue

        side   = pos.get("side", "long")
        entry  = pos["entry_price"]
        shares = pos["shares"]
        stop   = pos["stop_price"]
        target = pos["target_price"]
        trail  = pos.get("trail_stop_price", stop)
        peak   = pos.get("peak_price", entry)
        name   = pos.get("name", sym)

        close_reason = ""

        if side == "long":
            # 更新追蹤停損
            if price > peak:
                pos["peak_price"] = price
                new_trail = round(price * (1 - TRAIL_PCT), 2)
                if new_trail > trail:
                    pos["trail_stop_price"] = new_trail
                    trail = new_trail

            pnl = (price - entry) * shares
            pnl_pct = (price - entry) / entry * 100

            if price <= trail:
                close_reason = f"追蹤停損觸發 {price:.2f} <= {trail:.2f}"
            elif price >= target:
                close_reason = f"達到目標價 {price:.2f} >= {target:.2f}"

        else:  # short
            if price < peak:
                pos["peak_price"] = price
                new_trail = round(price * (1 + SHORT_TRAIL_PCT), 2)
                if new_trail < trail:
                    pos["trail_stop_price"] = new_trail
                    trail = new_trail

            pnl = (entry - price) * shares
            pnl_pct = (entry - price) / entry * 100

            if price >= trail:
                close_reason = f"追蹤停損觸發 {price:.2f} >= {trail:.2f}"
            elif price <= target:
                close_reason = f"達到目標價 {price:.2f} <= {target:.2f}"

        if close_reason:
            # 平倉
            lot_val = price * shares
            if side == "long":
                deployed -= entry * shares
                cash += lot_val
            else:
                deployed -= entry * shares
                cash += (entry - price) * shares + entry * shares

            alerts.append(
                f"出場 {sym} {name} [{side}]\n"
                f"  {close_reason}\n"
                f"  損益 {pnl:+,.0f} 元（{pnl_pct:+.2f}%）"
            )
            closed_syms.append(sym)
        else:
            print(f"  {sym} {name}: {price:.2f}  浮盈 {pnl:+,.0f}({pnl_pct:+.2f}%)  "
                  f"Trail={trail:.2f}")

    # 移除平倉部位
    for sym in closed_syms:
        del positions[sym]

    pos_data["positions"]        = positions
    pos_data["capital_deployed"] = max(deployed, 0)
    pos_data["capital_cash"]     = cash

    with open(POSITIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(pos_data, f, ensure_ascii=False, indent=2)

    if alerts:
        msg = f"盤中出場通知 | {NOW_STR}\n\n" + "\n\n".join(alerts)
        msg += f"\n\n現金餘額：{cash:,.0f} 元"
        print(msg)
        send_telegram(msg)
    else:
        print(f"[{NOW_STR}] 持倉正常，無出場訊號。")


if __name__ == "__main__":
    main()

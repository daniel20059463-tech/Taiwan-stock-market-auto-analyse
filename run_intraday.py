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

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_PATH = os.path.join(_LOG_DIR, f"intraday_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

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

POSITIONS_PATH = "data/paper_positions.json"
TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
NOW   = datetime.datetime.now(tz=TZ_TW)
NOW_STR = NOW.strftime("%H:%M")

SHORT_TRAIL_PCT = 0.035  # 空單固定追蹤 3.5%


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

        side         = pos.get("side", "long")
        entry        = pos["entry_price"]
        shares       = pos["shares"]
        stop         = pos["stop_price"]
        target       = pos["target_price"]
        trail        = pos.get("trail_stop_price", stop)
        peak         = pos.get("peak_price", entry)
        name         = pos.get("name", sym)
        batch        = pos.get("partial_exit_batch", 0)
        init_stop    = pos.get("initial_stop_price", stop)
        SHARES_PER_LOT = 1000

        close_reason   = ""
        partial_reason = ""

        if side == "long":
            if price > peak:
                pos["peak_price"] = price
                peak = price

            pnl_pct = (price - entry) / entry * 100

            # 三段式追蹤停損
            new_trail = trail
            if pnl_pct >= 3.0:
                with open("data/daily_price_cache.json", encoding="utf-8") as _f:
                    _pc = json.load(_f)
                _bars = sorted(_pc.get(sym, {}).items())
                _lows = [v["low"] for _, v in _bars if v.get("low", 0) > 0]
                if pnl_pct < 8.0 and len(_lows) >= 3:
                    new_trail = max(trail, round(min(_lows[-3:]), 2))
                elif len(_lows) >= 5:
                    new_trail = max(trail, round(min(_lows[-5:]), 2))
            if new_trail > trail:
                pos["trail_stop_price"] = new_trail
                trail = new_trail

            # 三批分出場
            init_risk = entry - init_stop if init_stop > 0 else 0
            if init_risk > 0:
                if batch == 0 and shares >= 3 * SHARES_PER_LOT:
                    if price >= entry + init_risk:
                        sell = max(SHARES_PER_LOT,
                                   (shares // 2) // SHARES_PER_LOT * SHARES_PER_LOT)
                        pnl_sell = (price - entry) * sell
                        pos["shares"] -= sell
                        pos["stop_price"] = entry
                        pos["trail_stop_price"] = max(trail, entry)
                        pos["partial_exit_batch"] = 1
                        cash += price * sell
                        deployed -= entry * sell
                        partial_reason = (
                            f"分批停利第一批（50%） {sym} {name}\n"
                            f"  出場 {sell // SHARES_PER_LOT} 張 @ {price:.2f}\n"
                            f"  損益 {pnl_sell:+,.0f} 元  停損移至成本 {entry:.2f}\n"
                            f"  剩餘 {pos['shares'] // SHARES_PER_LOT} 張"
                        )

                elif batch == 1 and shares >= 2 * SHARES_PER_LOT:
                    at_2r = price >= entry + 2 * init_risk
                    at_res = False
                    if not at_2r:
                        try:
                            with open("data/daily_price_cache.json", encoding="utf-8") as _f:
                                _pc = json.load(_f)
                            _bars = sorted(_pc.get(sym, {}).items())
                            _highs = [v["high"] for _, v in _bars[-20:] if v.get("high", 0) > 0]
                            at_res = bool(_highs) and price >= max(_highs)
                        except Exception:
                            pass
                    if at_2r or at_res:
                        sell = max(SHARES_PER_LOT,
                                   (shares * 3 // 5) // SHARES_PER_LOT * SHARES_PER_LOT)
                        pnl_sell = (price - entry) * sell
                        new_stop = round(entry + init_risk, 2)
                        pos["shares"] -= sell
                        pos["stop_price"] = new_stop
                        pos["trail_stop_price"] = max(trail, new_stop)
                        pos["partial_exit_batch"] = 2
                        cash += price * sell
                        deployed -= entry * sell
                        reason_tag = "達+2R" if at_2r else "碰20日高點"
                        partial_reason = (
                            f"分批停利第二批（30%）{reason_tag} {sym} {name}\n"
                            f"  出場 {sell // SHARES_PER_LOT} 張 @ {price:.2f}\n"
                            f"  損益 {pnl_sell:+,.0f} 元  停損移至+1R {new_stop:.2f}\n"
                            f"  剩餘 {pos['shares'] // SHARES_PER_LOT} 張"
                        )

            pnl = (price - entry) * pos["shares"]
            shares = pos["shares"]  # 更新為分批後的數量

            if price <= max(pos["stop_price"], pos.get("trail_stop_price", trail)):
                effective_stop = max(pos["stop_price"], pos.get("trail_stop_price", trail))
                close_reason = f"追蹤停損觸發 {price:.2f} <= {effective_stop:.2f}"
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

        if partial_reason:
            alerts.append(partial_reason)

        if close_reason:
            # 平倉（使用分批後的剩餘 shares）
            if side == "long":
                pnl     = (price - entry) * shares
                pnl_pct = (price - entry) / entry * 100
                deployed -= entry * shares
                cash += price * shares
            else:
                pnl     = (entry - price) * shares
                pnl_pct = (entry - price) / entry * 100
                deployed -= entry * shares
                cash += (entry - price) * shares + entry * shares

            alerts.append(
                f"出場 {sym} {name} [{side}]\n"
                f"  {close_reason}\n"
                f"  損益 {pnl:+,.0f} 元（{pnl_pct:+.2f}%）"
            )
            closed_syms.append(sym)
        elif not partial_reason:
            print(f"  {sym} {name}: {price:.2f}  浮盈 {pnl:+,.0f}  "
                  f"Trail={pos.get('trail_stop_price', trail):.2f}")

    # 移除平倉部位
    for sym in closed_syms:
        del positions[sym]

    # 重算 deployed/cash 確保數字嚴格一致，不累積誤差
    capital = pos_data.get("capital_total", 1_000_000)
    recalc_deployed = sum(
        p["entry_price"] * p["shares"] for p in positions.values()
    )
    recalc_cash = capital - recalc_deployed

    pos_data["positions"]        = positions
    pos_data["capital_deployed"] = round(recalc_deployed, 2)
    pos_data["capital_cash"]     = round(recalc_cash, 2)

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

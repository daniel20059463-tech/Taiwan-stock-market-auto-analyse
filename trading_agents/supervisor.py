# -*- coding: utf-8 -*-
"""
Supervisor：主協調 Agent

責任：
- 並行呼叫 flow_agent（籌碼）、technical_agent（技術）
- 彙整兩者分數 → 最終候選清單
- 呼叫 news_agent 取得否決資訊（需外部 WebSearch 結果傳入）
- 呼叫 risk_agent 計算下單規格
- 更新 paper_positions.json
- 輸出決策報告（可推播 Telegram）

執行：
  python -m trading_agents.supervisor          # 純量化，跳過新聞
  python run_premarket.py                       # 完整流程（含新聞 agent）
"""
from __future__ import annotations
import json, os, sys, urllib.request
from dataclasses import dataclass, field
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POSITIONS_PATH = "data/paper_positions.json"

# 綜合分數權重
FLOW_WEIGHT = 0.60
TECH_WEIGHT = 0.40

# 進場門檻
LONG_SCORE_MIN  = 0.38
SHORT_SCORE_MIN = 0.32

# 最多同時持有部位數
MAX_LONG_POSITIONS  = 4
MAX_SHORT_POSITIONS = 2


@dataclass
class Decision:
    symbol: str
    side: str
    action: str              # "open" | "hold" | "close" | "skip"
    entry_price: float
    lots: int
    stop_price: float
    target_price: float
    final_score: float
    flow_score: float
    tech_score: float
    name: str = ""
    reason: str = ""


@dataclass
class SupervisorReport:
    flow_date: str
    decisions: list[Decision] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (sym, reason)
    capital_total: float = 1_000_000
    capital_deployed: float = 0

    def open_orders(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "open"]

    def to_telegram_text(self) -> str:
        lines = [
            f"盤前掃描報告 | {self.flow_date}",
            f"資金 {self.capital_total:,.0f}　已動用 {self.capital_deployed:,.0f}",
            "",
        ]
        opens = self.open_orders()
        if opens:
            lines.append("【今日建倉訊號】")
            for d in opens:
                dir_tag = "多" if d.side == "long" else "空"
                lines += [
                    f"  {d.symbol} {d.name} [{dir_tag}單]  綜合評分 {d.final_score:.3f}",
                    f"  進場 {d.entry_price:.2f}　{d.lots}張",
                    f"  停損 {d.stop_price:.2f}　目標 {d.target_price:.2f}",
                    f"  {d.reason}",
                    "",
                ]
        else:
            lines.append("今日無新建倉訊號（未達門檻或資金已滿）")
        lines.append("---")
        lines.append("評分 = 籌碼60% + 技術40%，新聞 agent 否決後不進場")
        return "\n".join(lines)


def _fetch_yahoo_close(sym: str) -> float | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.TW?interval=1d&range=5d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        return next((v for v in reversed(closes) if v is not None), None)
    except Exception:
        return None


def _load_positions(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"trade_date": "", "capital_total": 1_000_000,
                "capital_deployed": 0, "capital_cash": 1_000_000, "positions": {}}


def _save_positions(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run(
    news_verdicts: dict[str, bool] | None = None,
    dry_run: bool = False,
    top_n_flow: int = 30,
    send_telegram: bool = False,
) -> SupervisorReport:
    """
    Args:
        news_verdicts: {symbol: override_flag}，True = 否決。None = 跳過新聞檢查。
        dry_run: True = 不寫入 paper_positions.json
        top_n_flow: 從籌碼 agent 取前幾名進行技術分析
        send_telegram: 是否推播 Telegram
    """
    import time
    from trading_agents import flow_agent, technical_agent, risk_agent

    # ── Step 1：籌碼 agent（並行概念：先跑完整掃描）────────────
    print("[Supervisor] Step 1: 籌碼 Agent 執行中...")
    flow_rpt = flow_agent.run(top_n=top_n_flow)
    print(f"  多方候選 {len(flow_rpt.long_candidates)} 檔，空方候選 {len(flow_rpt.short_candidates)} 檔")

    # ── Step 2：技術 agent（多空分別跑）────────────────────────
    print("[Supervisor] Step 2: 技術 Agent 執行中...")
    long_syms  = [c.symbol for c in flow_rpt.long_candidates]
    short_syms = [c.symbol for c in flow_rpt.short_candidates]

    tech_long  = technical_agent.run(long_syms,  side="long")
    tech_short = technical_agent.run(short_syms, side="short")

    # ── Step 3：合併評分 ───────────────────────────────────────
    final_long: list[tuple[float, str, float, float]] = []
    for c in flow_rpt.long_candidates:
        sig = tech_long.get(c.symbol)
        if sig is None:
            continue
        combined = FLOW_WEIGHT * c.flow_score + TECH_WEIGHT * sig.tech_score
        final_long.append((combined, c.symbol, c.flow_score, sig.tech_score))
    final_long.sort(reverse=True)

    final_short: list[tuple[float, str, float, float]] = []
    for c in flow_rpt.short_candidates:
        sig = tech_short.get(c.symbol)
        if sig is None:
            continue
        combined = FLOW_WEIGHT * c.flow_score + TECH_WEIGHT * sig.tech_score
        final_short.append((combined, c.symbol, c.flow_score, sig.tech_score))
    final_short.sort(reverse=True)

    print(f"  合併後：多方 {len(final_long)} 檔，空方 {len(final_short)} 檔")

    # ── Step 4：新聞 agent 否決過濾 ───────────────────────────
    def is_blocked(sym: str) -> bool:
        if news_verdicts is None:
            return False
        return news_verdicts.get(sym, False)

    # ── Step 5：門檻過濾 + 現有持倉檢查 ──────────────────────
    pos_data = _load_positions(POSITIONS_PATH)
    existing = set(pos_data.get("positions", {}).keys())
    capital_total    = pos_data.get("capital_total", 1_000_000)
    capital_deployed = pos_data.get("capital_deployed", 0)

    candidates_to_open: list[tuple[str, str]] = []  # (symbol, side)

    long_count  = sum(1 for s, p in pos_data.get("positions", {}).items() if p.get("side") == "long")
    short_count = sum(1 for s, p in pos_data.get("positions", {}).items() if p.get("side") == "short")

    for score, sym, fs, ts in final_long:
        if score < LONG_SCORE_MIN:
            break
        if sym in existing:
            continue
        if is_blocked(sym):
            continue
        if long_count >= MAX_LONG_POSITIONS:
            break
        candidates_to_open.append((sym, "long"))
        long_count += 1

    for score, sym, fs, ts in final_short:
        if score < SHORT_SCORE_MIN:
            break
        if sym in existing:
            continue
        if is_blocked(sym):
            continue
        if short_count >= MAX_SHORT_POSITIONS:
            break
        candidates_to_open.append((sym, "short"))
        short_count += 1

    # ── Step 6：Yahoo Finance 取即時價 ───────────────────────
    print(f"[Supervisor] Step 3: 取得即時收盤價（{len(candidates_to_open)} 檔）...")
    prices: dict[str, float] = {}
    for sym, side in candidates_to_open:
        p = _fetch_yahoo_close(sym)
        if p:
            prices[sym] = p
            print(f"  {sym}: {p:.2f}")
        time.sleep(0.3)

    # ── Step 7：風控 agent ───────────────────────────────────
    print("[Supervisor] Step 4: 風控 Agent 計算下單規格...")
    risk_inputs = [(sym, side, prices[sym]) for sym, side in candidates_to_open if sym in prices]
    risk_rpt = risk_agent.run(risk_inputs)

    # ── Step 8：產生決策 ──────────────────────────────────────
    score_map_long  = {sym: (s, fs, ts) for s, sym, fs, ts in final_long}
    score_map_short = {sym: (s, fs, ts) for s, sym, fs, ts in final_short}

    decisions: list[Decision] = []
    new_positions: dict[str, Any] = {}
    running_deployed = capital_deployed

    for order in risk_rpt.orders:
        if not order.feasible:
            continue
        if order.symbol in score_map_long:
            sc, fs, ts = score_map_long[order.symbol]
        elif order.symbol in score_map_short:
            sc, fs, ts = score_map_short[order.symbol]
        else:
            continue

        flow_c = next((c for c in flow_rpt.long_candidates + flow_rpt.short_candidates
                       if c.symbol == order.symbol), None)
        reason = ""
        if flow_c:
            reason = (f"投信{flow_c.trust/1000:+,.0f}k 外資{flow_c.foreign/1000:+,.0f}k")

        d = Decision(
            symbol=order.symbol,
            side=order.side,
            action="open",
            entry_price=order.entry_price,
            lots=order.lots,
            stop_price=order.stop_price,
            target_price=order.target_price,
            final_score=sc,
            flow_score=fs,
            tech_score=ts,
            reason=reason,
        )
        decisions.append(d)
        running_deployed += order.budget

        import datetime
        new_positions[order.symbol] = {
            "symbol": order.symbol,
            "name": "",
            "side": order.side,
            "entry_price": order.entry_price,
            "shares": order.lots * 1000,
            "entry_ts": int(datetime.datetime.now().timestamp() * 1000),
            "stop_price": order.stop_price,
            "target_price": order.target_price,
            "peak_price": order.entry_price,
            "trail_stop_price": order.stop_price,
            "entry_atr": None,
            "entry_reason": reason,
            "flow_score": fs,
            "tech_score": ts,
            "final_score": sc,
        }

    # ── Step 9：寫入持倉（deployed/cash 從實際持倉反算，防止漂移）──
    if not dry_run and new_positions:
        import datetime
        pos_data["positions"].update(new_positions)
        all_positions = pos_data["positions"]
        recalc_deployed = sum(
            p["entry_price"] * p["shares"] for p in all_positions.values()
        )
        pos_data["capital_deployed"] = round(recalc_deployed, 2)
        pos_data["capital_cash"]     = round(capital_total - recalc_deployed, 2)
        pos_data["trade_date"] = datetime.datetime.now().strftime("%Y%m%d")
        _save_positions(POSITIONS_PATH, pos_data)
        print(f"[Supervisor] 已更新持倉 {len(new_positions)} 檔")

    report = SupervisorReport(
        flow_date=flow_rpt.flow_date,
        decisions=decisions,
        capital_total=capital_total,
        capital_deployed=running_deployed,
    )

    # ── Step 10：推播 Telegram ────────────────────────────────
    if send_telegram and decisions:
        _send_telegram(report.to_telegram_text())

    return report


def _send_telegram(text: str) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("[Supervisor] Telegram 憑證未設定，跳過推播")
        return
    payload = json.dumps({"chat_id": chat, "text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.load(r)
            print("Telegram OK" if result.get("ok") else f"Telegram 失敗: {result}")
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")


if __name__ == "__main__":
    rpt = run(dry_run=True, send_telegram=False)
    print("\n" + "=" * 60)
    print(rpt.to_telegram_text())
    opens = rpt.open_orders()
    print(f"\n共 {len(opens)} 個建倉訊號")

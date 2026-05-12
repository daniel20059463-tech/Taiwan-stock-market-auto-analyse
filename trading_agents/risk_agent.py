# -*- coding: utf-8 -*-
"""
Agent 4：風控 Agent

責任：
- 讀取目前持倉與可用資金
- 計算每筆建議張數、停損點、目標價
- 確認不違反：產業限制、單筆上限 20%、總曝險上限 80%
- 輸出：每檔股票的下單規格

不做選股判斷，只做「這筆單的數字」。
"""
from __future__ import annotations
import json
from dataclasses import dataclass

POSITIONS_PATH = "data/paper_positions.json"

MAX_POSITION_PCT  = 0.20   # 單筆最大 20% 資金
MAX_TOTAL_DEPLOYED = 0.80  # 總部位最大 80%

# 停損/目標預設（多/空）
LONG_STOP_PCT   = -0.05
LONG_TARGET_PCT = +0.08
SHORT_STOP_PCT  = +0.04
SHORT_TARGET_PCT = -0.08


@dataclass
class OrderSpec:
    symbol: str
    side: str
    entry_price: float
    lots: int
    budget: float           # 動用資金
    stop_price: float
    target_price: float
    feasible: bool          # 是否可執行（資金、產業都過）
    block_reason: str       # 若 feasible=False，說明原因


@dataclass
class RiskReport:
    capital_total: float
    capital_deployed: float
    capital_cash: float
    orders: list[OrderSpec]

    def available_budget(self) -> float:
        return self.capital_total * MAX_TOTAL_DEPLOYED - self.capital_deployed

    def summary(self) -> str:
        lines = [
            f"資金：{self.capital_total:,.0f}　已用：{self.capital_deployed:,.0f}"
            f"　可用：{self.available_budget():,.0f}",
        ]
        for o in self.orders:
            if o.feasible:
                lines.append(
                    f"  {o.symbol} [{o.side}] {o.lots}張 @{o.entry_price:.1f}"
                    f"  停{o.stop_price:.1f} 目標{o.target_price:.1f}"
                    f"  動用{o.budget:,.0f}"
                )
            else:
                lines.append(f"  {o.symbol} [BLOCKED] {o.block_reason}")
        return "\n".join(lines)


def calc_order(
    symbol: str,
    side: str,
    entry_price: float,
    capital_total: float,
    capital_deployed: float,
    stop_pct: float | None = None,
    target_pct: float | None = None,
) -> OrderSpec:
    from trading_agents.excluded_sectors import is_allowed

    if not is_allowed(symbol):
        return OrderSpec(symbol, side, entry_price, 0, 0, 0, 0,
                         False, "禁止產業")

    avail = capital_total * MAX_TOTAL_DEPLOYED - capital_deployed
    budget_cap = min(capital_total * MAX_POSITION_PCT, avail)

    if budget_cap < entry_price * 1000:
        return OrderSpec(symbol, side, entry_price, 0, 0, 0, 0,
                         False, f"可用資金不足（上限{budget_cap:,.0f}，單張{entry_price*1000:,.0f}）")

    lots = int(budget_cap // (entry_price * 1000))
    if lots < 1:
        return OrderSpec(symbol, side, entry_price, 0, 0, 0, 0,
                         False, "張數計算為 0")

    budget = lots * entry_price * 1000

    if side == "long":
        sp = stop_pct   if stop_pct   is not None else LONG_STOP_PCT
        tp = target_pct if target_pct is not None else LONG_TARGET_PCT
        stop   = round(entry_price * (1 + sp), 2)
        target = round(entry_price * (1 + tp), 2)
    else:
        sp = stop_pct   if stop_pct   is not None else SHORT_STOP_PCT
        tp = target_pct if target_pct is not None else SHORT_TARGET_PCT
        stop   = round(entry_price * (1 + sp), 2)
        target = round(entry_price * (1 + tp), 2)

    return OrderSpec(symbol, side, entry_price, lots, budget, stop, target, True, "")


def run(
    candidates: list[tuple[str, str, float]],   # [(symbol, side, price), ...]
    positions_path: str = POSITIONS_PATH,
) -> RiskReport:
    """
    Args:
        candidates: [(symbol, side, price), ...] 準備下單的清單
        positions_path: paper_positions.json 路徑
    """
    with open(positions_path, encoding="utf-8") as f:
        pos_data = json.load(f)

    capital_total    = pos_data.get("capital_total", 1_000_000)
    capital_deployed = pos_data.get("capital_deployed", 0)

    orders = []
    running_deployed = capital_deployed

    for sym, side, price in candidates:
        spec = calc_order(sym, side, price, capital_total, running_deployed)
        if spec.feasible:
            running_deployed += spec.budget
        orders.append(spec)

    return RiskReport(
        capital_total=capital_total,
        capital_deployed=capital_deployed,
        capital_cash=capital_total - capital_deployed,
        orders=orders,
    )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test = [("2344", "long", 121.5), ("2303", "long", 104.5), ("2891", "short", 53.5)]
    rpt = run(test)
    print("[Risk Agent]")
    print(rpt.summary())

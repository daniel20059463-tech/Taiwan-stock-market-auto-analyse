# -*- coding: utf-8 -*-
"""
Agent 1：籌碼分析 Agent

責任：
- 讀取最新 flow_cache.json
- 計算投信/外資/自營 買賣超強度評分
- 輸出多方/空方候選清單（純量化，不看新聞不看技術）

回傳：FlowReport dataclass
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any

FLOW_CACHE_PATH = "data/flow_cache.json"

TRUST_LONG_MIN   =  200_000   # 投信淨買 >= 20萬股
TRUST_SHORT_MIN  = -300_000   # 投信淨賣 <= -30萬股
TRUST_CONSEC_BONUS = 1.3      # 連買多日加成（由外部傳入，flow_cache 無歷史）


@dataclass
class FlowCandidate:
    symbol: str
    trust: float        # 投信淨買（股）
    foreign: float      # 外資淨買（股）
    dealer: float       # 自營淨買（股）
    flow_score: float   # 0~1，籌碼綜合評分
    side: str           # "long" | "short"

    def summary(self) -> str:
        return (f"{self.symbol} [{self.side}] "
                f"投信{self.trust/1000:+,.0f}k 外資{self.foreign/1000:+,.0f}k "
                f"得分{self.flow_score:.3f}")


@dataclass
class FlowReport:
    flow_date: str
    long_candidates: list[FlowCandidate] = field(default_factory=list)
    short_candidates: list[FlowCandidate] = field(default_factory=list)
    total_symbols: int = 0


def _flow_score_long(trust: float, foreign: float, dealer: float) -> float:
    """投信買超為主(45%)、外資(35%)、自營(20%)。"""
    trust_norm   = min(trust / 5_000_000, 1.0) * 0.45
    foreign_norm = min(max(foreign, 0) / 20_000_000, 1.0) * 0.35
    dealer_norm  = min(max(dealer, 0) / 2_000_000, 1.0) * 0.20
    return round(trust_norm + foreign_norm + dealer_norm, 4)


def _flow_score_short(trust: float, foreign: float, dealer: float) -> float:
    """賣超越大得分越高。"""
    trust_norm   = min(abs(min(trust, 0)) / 3_000_000, 1.0) * 0.45
    foreign_norm = min(abs(min(foreign, 0)) / 10_000_000, 1.0) * 0.35
    dealer_norm  = min(abs(min(dealer, 0)) / 1_000_000, 1.0) * 0.20
    return round(trust_norm + foreign_norm + dealer_norm, 4)


def run(
    flow_cache_path: str = FLOW_CACHE_PATH,
    allowed_fn: Any = None,
    top_n: int = 20,
) -> FlowReport:
    """
    執行籌碼分析。

    Args:
        flow_cache_path: flow_cache.json 路徑
        allowed_fn: callable(symbol) -> bool，產業過濾
        top_n: 每個方向最多回傳幾個候選
    """
    from trading_agents.excluded_sectors import is_allowed
    if allowed_fn is None:
        allowed_fn = is_allowed

    with open(flow_cache_path, encoding="utf-8") as f:
        flow_all = json.load(f)

    flow_date = sorted(flow_all.keys())[-1]
    rows = flow_all[flow_date]

    long_list: list[FlowCandidate] = []
    short_list: list[FlowCandidate] = []

    for sym, r in rows.items():
        if not allowed_fn(sym):
            continue
        trust   = r.get("investment_trust_net_buy", 0) or 0
        foreign = r.get("foreign_net_buy", 0) or 0
        dealer  = r.get("dealer_net_buy", 0) or 0

        if trust >= TRUST_LONG_MIN:
            score = _flow_score_long(trust, foreign, dealer)
            long_list.append(FlowCandidate(sym, trust, foreign, dealer, score, "long"))

        if trust <= TRUST_SHORT_MIN:
            score = _flow_score_short(trust, foreign, dealer)
            short_list.append(FlowCandidate(sym, trust, foreign, dealer, score, "short"))

    long_list.sort(key=lambda x: x.flow_score, reverse=True)
    short_list.sort(key=lambda x: x.flow_score, reverse=True)

    return FlowReport(
        flow_date=flow_date,
        long_candidates=long_list[:top_n],
        short_candidates=short_list[:top_n],
        total_symbols=len(rows),
    )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = run()
    print(f"[Flow Agent] 籌碼日期：{report.flow_date}，掃描 {report.total_symbols} 檔")
    print(f"\n多方 TOP10：")
    for c in report.long_candidates[:10]:
        print(" ", c.summary())
    print(f"\n空方 TOP10：")
    for c in report.short_candidates[:10]:
        print(" ", c.summary())

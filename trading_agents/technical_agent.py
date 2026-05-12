# -*- coding: utf-8 -*-
"""
Agent 2：技術分析 Agent

責任：
- 接收籌碼 agent 的候選清單
- 計算 MA10、RSI14、5日動能、量能變化
- 輸出技術面評分（0~1），並決定是否通過技術濾網

回傳：TechnicalReport dataclass
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field

PRICE_CACHE_PATH = "data/daily_price_cache.json"


@dataclass
class TechnicalSignal:
    symbol: str
    close: float
    ma10: float | None
    rsi14: float | None
    momentum_5d: float | None   # 5日報酬率 %
    above_ma10: bool
    tech_score: float           # 0~1
    pass_filter: bool           # 是否通過技術濾網

    def summary(self) -> str:
        ma_tag = "MA上" if self.above_ma10 else "MA下"
        rsi_str = f"RSI{self.rsi14:.0f}" if self.rsi14 else "RSI-"
        mom_str = f"動能{self.momentum_5d:+.1f}%" if self.momentum_5d is not None else ""
        return (f"{self.symbol} {self.close:.1f}元 {ma_tag} {rsi_str} {mom_str} "
                f"技術{self.tech_score:.3f} {'OK' if self.pass_filter else 'SKIP'}")


@dataclass
class TechnicalReport:
    signals: dict[str, TechnicalSignal] = field(default_factory=dict)

    def get(self, symbol: str) -> TechnicalSignal | None:
        return self.signals.get(symbol)


def _calc_ma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        (gains if diff >= 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def _tech_score_long(close: float, ma10: float | None, rsi: float | None,
                     mom: float | None) -> tuple[float, bool]:
    """回傳 (得分, 是否通過)。"""
    score = 0.0
    above = ma10 is not None and close > ma10

    # MA10（30%）
    if above:
        score += 0.30
    elif ma10 is not None:
        gap_pct = (close - ma10) / ma10 * 100
        if gap_pct > -3:       # 貼近 MA10，算半分
            score += 0.15

    # RSI（40%）：50-70 最理想，超買或超賣都扣
    if rsi is not None:
        if 50 <= rsi <= 68:
            score += 0.40
        elif 40 <= rsi < 50:
            score += 0.20
        elif 68 < rsi <= 80:
            score += 0.15    # 偏熱但可追
        # rsi > 80 或 < 40：不加分

    # 動能（30%）：5日上漲且 < 15%（避免追高）
    if mom is not None:
        if 0 < mom <= 8:
            score += 0.30
        elif 8 < mom <= 15:
            score += 0.15
        elif mom > 15:
            score += 0.05    # 漲太多，可能過熱

    pass_filter = above and (rsi is None or rsi < 80) and score >= 0.30
    return round(score, 4), pass_filter


def _tech_score_short(close: float, ma10: float | None, rsi: float | None,
                      mom: float | None) -> tuple[float, bool]:
    score = 0.0
    below = ma10 is not None and close < ma10

    if below:
        score += 0.30
    elif ma10 is not None:
        gap_pct = (close - ma10) / ma10 * 100
        if gap_pct < 3:
            score += 0.15

    if rsi is not None:
        if 30 <= rsi <= 50:
            score += 0.40
        elif 50 < rsi <= 60:
            score += 0.20
        elif rsi > 70:
            score += 0.30    # 超買更適合放空

    if mom is not None:
        if -8 <= mom < 0:
            score += 0.30
        elif -15 <= mom < -8:
            score += 0.15

    pass_filter = (rsi is None or rsi > 30) and score >= 0.25
    return round(score, 4), pass_filter


def run(
    symbols: list[str],
    side: str = "long",
    price_cache_path: str = PRICE_CACHE_PATH,
) -> TechnicalReport:
    """
    Args:
        symbols: 要分析的股票代號清單（來自 flow_agent）
        side: "long" 或 "short"
        price_cache_path: daily_price_cache.json 路徑
    """
    with open(price_cache_path, encoding="utf-8") as f:
        cache = json.load(f)

    report = TechnicalReport()

    for sym in symbols:
        bars = cache.get(sym, {})
        if not bars:
            continue
        dates = sorted(bars.keys())
        closes = [bars[d]["close"] for d in dates if bars[d].get("close")]
        if len(closes) < 5:
            continue

        close   = closes[-1]
        ma10    = _calc_ma(closes, 10)
        rsi14   = _calc_rsi(closes, 14)
        mom_5d  = round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None

        if side == "long":
            score, passed = _tech_score_long(close, ma10, rsi14, mom_5d)
        else:
            score, passed = _tech_score_short(close, ma10, rsi14, mom_5d)

        report.signals[sym] = TechnicalSignal(
            symbol=sym,
            close=close,
            ma10=ma10,
            rsi14=rsi14,
            momentum_5d=mom_5d,
            above_ma10=(ma10 is not None and close > ma10),
            tech_score=score,
            pass_filter=passed,
        )

    return report


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # 測試：直接掃描幾檔
    test_syms = ["2344", "2303", "2337", "2330", "3711"]
    rpt = run(test_syms, side="long")
    print("[Technical Agent] 結果：")
    for sig in rpt.signals.values():
        print(" ", sig.summary())

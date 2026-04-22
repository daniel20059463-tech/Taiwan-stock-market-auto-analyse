"""
Rule-based swing exit judge for retail_flow_swing strategy.

Uses deterministic rules instead of an LLM so that decisions are
reproducible, testable, and compatible with backtesting.

Exit priority:
  1. stop_loss_hit          — immediate, confidence 100
  2. MA10 break + drawdown  — price below MA10 with loss buffer exceeded
  3. flow_weakened          — institutional flow turned negative for ≥ 3 days
  4. time_exit              — position held beyond MAX_HOLDING_DAYS
  5. hold                   — all conditions satisfied
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_HOLDING_DAYS = 15
FLOW_EXIT_MIN_DAYS = 3      # require flow to be weak for at least N days before exiting
MA10_BUFFER_PCT = 0.5       # allow price to be below MA10 by this % before triggering


@dataclass
class SwingJudgment:
    action: str                      # "hold" or "exit"
    reason: str
    confidence: int                  # 0–100
    exit_reason_code: str | None = None  # "ma10_break" | "flow_weakened" | "time_exit" | "stop_loss" | None


class SwingExitJudge:
    """Rule-based judge: deterministic, zero latency, fully backtestable."""

    async def judge(
        self,
        *,
        symbol: str,
        holding_days: int,
        entry_price: float,
        current_price: float,
        unrealized_pnl_pct: float,
        above_ma10: bool,
        flow_score: float,
        sentiment_score: float | None,
        market_change_pct: float,
        stop_loss_hit: bool,
    ) -> SwingJudgment:
        if stop_loss_hit:
            logger.info("SwingExitJudge %s → exit (stop_loss)", symbol)
            return SwingJudgment(
                action="exit",
                reason="止損價格觸及，強制出場",
                confidence=100,
                exit_reason_code="stop_loss",
            )

        # MA10 跌破：允許 MA10_BUFFER_PCT 緩衝，避免因小波動誤出場
        if not above_ma10 and unrealized_pnl_pct < -MA10_BUFFER_PCT:
            logger.info(
                "SwingExitJudge %s → exit (ma10_break) unrealized=%.2f%% above_ma10=%s",
                symbol, unrealized_pnl_pct, above_ma10,
            )
            return SwingJudgment(
                action="exit",
                reason="跌破 MA10 支撐且出現虧損，趨勢轉弱",
                confidence=85,
                exit_reason_code="ma10_break",
            )

        # 籌碼轉弱：flow_score ≤ 0 且持有已超過最短觀察期
        if flow_score <= 0.0 and holding_days >= FLOW_EXIT_MIN_DAYS:
            logger.info(
                "SwingExitJudge %s → exit (flow_weakened) flow_score=%.2f holding_days=%d",
                symbol, flow_score, holding_days,
            )
            return SwingJudgment(
                action="exit",
                reason="法人籌碼轉為賣超，波段支撐消失",
                confidence=75,
                exit_reason_code="flow_weakened",
            )

        # 時間出場：超過最大持有天數
        if holding_days >= MAX_HOLDING_DAYS:
            logger.info(
                "SwingExitJudge %s → exit (time_exit) holding_days=%d",
                symbol, holding_days,
            )
            return SwingJudgment(
                action="exit",
                reason=f"持有已達 {MAX_HOLDING_DAYS} 日上限，依計畫出場",
                confidence=80,
                exit_reason_code="time_exit",
            )

        logger.debug(
            "SwingExitJudge %s → hold (days=%d flow=%.2f above_ma10=%s pnl=%.2f%%)",
            symbol, holding_days, flow_score, above_ma10, unrealized_pnl_pct,
        )
        return SwingJudgment(
            action="hold",
            reason="持倉條件均滿足，繼續持有",
            confidence=70,
        )


def swing_exit_judge_from_env() -> SwingExitJudge:
    return SwingExitJudge()

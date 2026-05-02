"""
Rule-based swing exit judge for retail_flow_swing strategy.

Uses deterministic rules instead of an LLM so that decisions are
reproducible, testable, and compatible with backtesting.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_HOLDING_DAYS = 15
STRONG_MAX_HOLDING_DAYS = 20
FLOW_EXIT_MIN_DAYS = 3
FLOW_WEAK_STREAK_DAYS = 2
MA10_BUFFER_PCT = 0.5
MA10_ATR_BUFFER_MULT = 0.3


@dataclass
class SwingJudgment:
    action: str
    reason: str
    confidence: int
    exit_reason_code: str | None = None


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
        flow_weak_streak: int,
        sentiment_score: float | None,
        market_change_pct: float,
        stop_loss_hit: bool,
        ma10_gap_pct: float | None = None,
        atr_pct: float | None = None,
        sector_state: str | None = None,
    ) -> SwingJudgment:
        if stop_loss_hit:
            logger.info("SwingExitJudge %s exit (stop_loss)", symbol)
            return SwingJudgment(
                action="exit",
                reason="跌破有效停損，立即出場",
                confidence=100,
                exit_reason_code="stop_loss",
            )

        ma10_buffer_pct = MA10_BUFFER_PCT
        if atr_pct is not None and atr_pct > 0:
            ma10_buffer_pct = max(MA10_BUFFER_PCT, atr_pct * MA10_ATR_BUFFER_MULT)

        if (
            not above_ma10
            and unrealized_pnl_pct < -MA10_BUFFER_PCT
            and ma10_gap_pct is not None
            and ma10_gap_pct <= -ma10_buffer_pct
        ):
            logger.info(
                "SwingExitJudge %s exit (ma10_break) unrealized=%.2f%% gap=%.2f%% buffer=%.2f%%",
                symbol,
                unrealized_pnl_pct,
                ma10_gap_pct,
                ma10_buffer_pct,
            )
            return SwingJudgment(
                action="exit",
                reason="跌破 MA10 且超出 ATR 緩衝，視為結構轉弱",
                confidence=85,
                exit_reason_code="ma10_break",
            )

        if flow_score <= 0.0 and flow_weak_streak >= FLOW_WEAK_STREAK_DAYS and holding_days >= FLOW_EXIT_MIN_DAYS:
            logger.info(
                "SwingExitJudge %s exit (flow_weakened) flow_score=%.2f streak=%d holding_days=%d",
                symbol,
                flow_score,
                flow_weak_streak,
                holding_days,
            )
            return SwingJudgment(
                action="exit",
                reason="籌碼連續兩個有效日轉弱，波段結構失真",
                confidence=75,
                exit_reason_code="flow_weakened",
            )

        if sector_state == "exit" and holding_days >= FLOW_EXIT_MIN_DAYS:
            logger.info(
                "SwingExitJudge %s exit (sector_exit) sector_state=%s holding_days=%d",
                symbol,
                sector_state,
                holding_days,
            )
            return SwingJudgment(
                action="exit",
                reason="類股狀態轉為 exit，持股優先退出。",
                confidence=88,
                exit_reason_code="sector_exit",
            )

        strong_position = above_ma10 and flow_score > 0.0
        if sector_state == "weakening":
            strong_position = False
        max_holding_days = STRONG_MAX_HOLDING_DAYS if strong_position else MAX_HOLDING_DAYS
        if holding_days >= max_holding_days:
            logger.info(
                "SwingExitJudge %s exit (time_exit) holding_days=%d limit=%d",
                symbol,
                holding_days,
                max_holding_days,
            )
            return SwingJudgment(
                action="exit",
                reason=f"持有天數超過 {max_holding_days} 天，時間出場",
                confidence=80,
                exit_reason_code="time_exit",
            )

        logger.debug(
            "SwingExitJudge %s hold (days=%d flow=%.2f streak=%d above_ma10=%s pnl=%.2f%%)",
            symbol,
            holding_days,
            flow_score,
            flow_weak_streak,
            above_ma10,
            unrealized_pnl_pct,
        )
        return SwingJudgment(
            action="hold",
            reason="持股結構仍成立，繼續持有",
            confidence=70,
        )


def swing_exit_judge_from_env() -> SwingExitJudge:
    return SwingExitJudge()

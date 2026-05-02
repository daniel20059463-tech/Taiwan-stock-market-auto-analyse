from __future__ import annotations

import asyncio

from swing_exit_judge import SwingExitJudge


def test_swing_exit_judge_holds_when_ma10_break_is_within_atr_buffer() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=5,
            entry_price=100.0,
            current_price=98.8,
            unrealized_pnl_pct=-1.2,
            above_ma10=False,
            flow_score=0.5,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=-0.25,
            atr_pct=1.0,
        )
    )

    assert result.action == "hold"


def test_swing_exit_judge_exits_when_ma10_break_exceeds_atr_buffer() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=5,
            entry_price=100.0,
            current_price=98.0,
            unrealized_pnl_pct=-2.0,
            above_ma10=False,
            flow_score=0.5,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=-0.8,
            atr_pct=1.0,
        )
    )

    assert result.action == "exit"
    assert result.exit_reason_code == "ma10_break"


def test_swing_exit_judge_requires_two_day_weak_flow_streak() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=4,
            entry_price=100.0,
            current_price=101.0,
            unrealized_pnl_pct=1.0,
            above_ma10=True,
            flow_score=-0.2,
            flow_weak_streak=1,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=0.5,
            atr_pct=1.0,
        )
    )

    assert result.action == "hold"


def test_swing_exit_judge_exits_on_two_day_weak_flow_streak() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=4,
            entry_price=100.0,
            current_price=101.0,
            unrealized_pnl_pct=1.0,
            above_ma10=True,
            flow_score=-0.2,
            flow_weak_streak=2,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=0.5,
            atr_pct=1.0,
        )
    )

    assert result.action == "exit"
    assert result.exit_reason_code == "flow_weakened"


def test_swing_exit_judge_extends_time_exit_for_strong_positions() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=16,
            entry_price=100.0,
            current_price=108.0,
            unrealized_pnl_pct=8.0,
            above_ma10=True,
            flow_score=0.8,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=2.0,
            atr_pct=1.0,
        )
    )

    assert result.action == "hold"


def test_swing_exit_judge_exits_strong_position_after_extended_limit() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=20,
            entry_price=100.0,
            current_price=108.0,
            unrealized_pnl_pct=8.0,
            above_ma10=True,
            flow_score=0.8,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=2.0,
            atr_pct=1.0,
        )
    )

    assert result.action == "exit"
    assert result.exit_reason_code == "time_exit"


def test_swing_exit_judge_weakening_sector_disables_extended_time_exit() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=16,
            entry_price=100.0,
            current_price=108.0,
            unrealized_pnl_pct=8.0,
            above_ma10=True,
            flow_score=0.8,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=2.0,
            atr_pct=1.0,
            sector_state="weakening",
        )
    )

    assert result.action == "exit"
    assert result.exit_reason_code == "time_exit"


def test_swing_exit_judge_exit_sector_forces_exit_after_min_hold() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=4,
            entry_price=100.0,
            current_price=108.0,
            unrealized_pnl_pct=8.0,
            above_ma10=True,
            flow_score=0.8,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=2.0,
            atr_pct=1.0,
            sector_state="exit",
        )
    )

    assert result.action == "exit"
    assert result.exit_reason_code == "sector_exit"


def test_swing_exit_judge_exits_immediately_on_stop_loss() -> None:
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=1,
            entry_price=100.0,
            current_price=94.0,
            unrealized_pnl_pct=-6.0,
            above_ma10=False,
            flow_score=0.8,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=True,
            ma10_gap_pct=-2.0,
            atr_pct=1.0,
        )
    )

    assert result.action == "exit"
    assert result.exit_reason_code == "stop_loss"


def test_swing_exit_judge_holds_when_flow_weak_but_holding_days_below_min() -> None:
    # flow_weak_streak >= 2 but holding_days < FLOW_EXIT_MIN_DAYS (3) → hold
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=2,
            entry_price=100.0,
            current_price=101.0,
            unrealized_pnl_pct=1.0,
            above_ma10=True,
            flow_score=-0.2,
            flow_weak_streak=2,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=0.5,
            atr_pct=1.0,
        )
    )

    assert result.action == "hold"


def test_swing_exit_judge_holds_when_sector_exit_but_below_min_hold_days() -> None:
    # sector_state="exit" but holding_days < FLOW_EXIT_MIN_DAYS (3) → hold
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=2,
            entry_price=100.0,
            current_price=108.0,
            unrealized_pnl_pct=8.0,
            above_ma10=True,
            flow_score=0.8,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=2.0,
            atr_pct=1.0,
            sector_state="exit",
        )
    )

    assert result.action == "hold"


def test_swing_exit_judge_holds_when_ma10_gap_pct_is_none() -> None:
    # ma10_gap_pct=None → ma10_break condition cannot be evaluated → hold
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=5,
            entry_price=100.0,
            current_price=98.0,
            unrealized_pnl_pct=-2.0,
            above_ma10=False,
            flow_score=0.5,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=None,
            atr_pct=1.0,
        )
    )

    assert result.action == "hold"


def test_swing_exit_judge_normal_time_exit_at_day_15() -> None:
    # Non-strong position (below MA10) → limit is 15 days
    judge = SwingExitJudge()

    result = asyncio.run(
        judge.judge(
            symbol="2330",
            holding_days=15,
            entry_price=100.0,
            current_price=99.0,
            unrealized_pnl_pct=-1.0,
            above_ma10=False,
            flow_score=0.3,
            flow_weak_streak=0,
            sentiment_score=None,
            market_change_pct=0.0,
            stop_loss_hit=False,
            ma10_gap_pct=0.0,
            atr_pct=1.0,
        )
    )

    assert result.action == "exit"
    assert result.exit_reason_code == "time_exit"

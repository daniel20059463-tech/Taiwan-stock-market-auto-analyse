from institutional_flow_provider import InstitutionalFlowRow
from retail_flow_strategy import (
    classify_watch_state,
    compute_flow_score,
    should_enter_position,
    should_exit_position,
)
from trading.swing_runtime import SwingRuntimeCoordinator


def test_compute_flow_score_weights_foreign_trust_and_major() -> None:
    row = InstitutionalFlowRow(
        symbol="2330",
        name="台積電",
        foreign_net_buy=1000,
        investment_trust_net_buy=500,
        major_net_buy=800,
    )

    score = compute_flow_score(row)

    assert score == 1.0


def test_classify_watch_state_marks_watch_when_flow_is_positive_but_price_not_confirmed() -> None:
    state = classify_watch_state(
        flow_score=0.7,
        above_ma10=False,
        volume_confirmed=False,
        recent_runup_pct=2.0,
    )

    assert state == "watch"


def test_classify_watch_state_marks_ready_to_buy_when_all_confirmations_pass() -> None:
    state = classify_watch_state(
        flow_score=0.8,
        above_ma10=True,
        volume_confirmed=True,
        recent_runup_pct=3.0,
        consecutive_trust_days=2,
    )

    assert state == "ready_to_buy"


def test_classify_watch_state_stays_watch_when_trust_streak_is_one() -> None:
    state = classify_watch_state(
        flow_score=0.8,
        above_ma10=True,
        volume_confirmed=True,
        recent_runup_pct=3.0,
        consecutive_trust_days=1,
    )

    assert state == "watch"


def test_classify_watch_state_marks_skip_when_recent_runup_is_too_high() -> None:
    state = classify_watch_state(
        flow_score=0.8,
        above_ma10=True,
        volume_confirmed=True,
        recent_runup_pct=11.0,
    )

    assert state == "skip"


def test_should_enter_position_requires_ready_to_buy_state() -> None:
    assert should_enter_position(watch_state="ready_to_buy") is True
    assert should_enter_position(watch_state="watch") is False


def test_should_exit_position_when_price_breaks_below_ma10() -> None:
    assert should_exit_position(
        stop_loss_hit=False,
        close_below_ma10=True,
        flow_weakened=False,
        holding_days=4,
    ) == "ma10_break"


def test_should_exit_position_when_flow_weakened() -> None:
    assert should_exit_position(
        stop_loss_hit=False,
        close_below_ma10=False,
        flow_weakened=True,
        holding_days=4,
    ) == "flow_weakened"


def test_should_exit_position_when_holding_days_exceed_limit() -> None:
    assert should_exit_position(
        stop_loss_hit=False,
        close_below_ma10=False,
        flow_weakened=False,
        holding_days=11,
    ) == "time_exit"


def test_swing_runtime_coordinator_tracks_state_transitions() -> None:
    runtime = SwingRuntimeCoordinator()

    state = runtime.classify_entry_state(
        symbol="2330",
        flow_score=0.8,
        above_ma10=False,
        volume_confirmed=False,
        recent_runup_pct=2.0,
        consecutive_trust_days=2,
        classifier=classify_watch_state,
    )

    assert state == "watch"
    assert runtime.watch_states["2330"] == "watch"

    state = runtime.classify_entry_state(
        symbol="2330",
        flow_score=0.8,
        above_ma10=True,
        volume_confirmed=True,
        recent_runup_pct=2.0,
        consecutive_trust_days=2,
        classifier=classify_watch_state,
    )

    assert state == "ready_to_buy"
    assert runtime.watch_states["2330"] == "ready_to_buy"


def test_swing_runtime_coordinator_only_triggers_on_transition_into_ready() -> None:
    runtime = SwingRuntimeCoordinator()
    runtime.watch_states["2330"] = "watch"

    assert runtime.should_trigger_entry("2330", "ready_to_buy") is True
    runtime.mark_entered("2330")
    assert runtime.watch_states["2330"] == "entered"
    assert runtime.should_trigger_entry("2330", "ready_to_buy") is False


def test_swing_runtime_coordinator_resets_for_new_day() -> None:
    runtime = SwingRuntimeCoordinator()
    runtime.watch_states["2330"] = "entered"

    runtime.reset_for_new_day()

    assert runtime.watch_states == {}

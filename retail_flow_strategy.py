from __future__ import annotations

from institutional_flow_provider import InstitutionalFlowRow

TRUST_FLOW_INTENSITY_FULL_SCALE = 0.01
FOREIGN_FLOW_INTENSITY_FULL_SCALE = 0.01
MAJOR_FLOW_INTENSITY_FULL_SCALE = 0.008
MIN_ENTRY_FLOW_SCORE = 0.55


def _positive_score(value: int) -> float:
    return 1.0 if value > 0 else 0.0


def _scaled_positive_intensity(
    value: int,
    avg_daily_volume_20d: float | None,
    *,
    full_scale_ratio: float,
) -> float:
    if value <= 0:
        return 0.0
    if avg_daily_volume_20d is None or avg_daily_volume_20d <= 0:
        return _positive_score(value)
    intensity = value / avg_daily_volume_20d
    return max(0.0, min(intensity / full_scale_ratio, 1.0))


def _margin_signal(margin_net_change: int) -> float:
    """Contrarian retail signal.

    Margin decrease (retail exiting) → institutions holding → mild positive.
    Margin surge (retail chasing) → crowded trade → mild negative.
    """
    if margin_net_change < 0:
        return 0.05
    if margin_net_change > 0:
        return -0.05
    return 0.0


def compute_flow_score(row: InstitutionalFlowRow) -> float:
    trust = _scaled_positive_intensity(
        row.investment_trust_net_buy,
        row.avg_daily_volume_20d,
        full_scale_ratio=TRUST_FLOW_INTENSITY_FULL_SCALE,
    ) * 0.45
    foreign = _scaled_positive_intensity(
        row.foreign_net_buy,
        row.avg_daily_volume_20d,
        full_scale_ratio=FOREIGN_FLOW_INTENSITY_FULL_SCALE,
    ) * 0.35
    major = _scaled_positive_intensity(
        row.major_net_buy,
        row.avg_daily_volume_20d,
        full_scale_ratio=MAJOR_FLOW_INTENSITY_FULL_SCALE,
    ) * 0.20
    margin = _margin_signal(row.margin_net_change)
    return round(trust + foreign + major + margin, 2)


def classify_watch_state(
    *,
    flow_score: float,
    above_ma10: bool,
    volume_confirmed: bool,
    recent_runup_pct: float,
    consecutive_trust_days: int = 0,
) -> str:
    if flow_score <= 0:
        return "skip"
    if recent_runup_pct >= 15.0:
        return "skip"
    if flow_score < MIN_ENTRY_FLOW_SCORE:
        return "watch"
    if consecutive_trust_days < 2:
        return "watch"
    if above_ma10 and volume_confirmed:
        return "ready_to_buy"
    return "watch"


def should_enter_position(*, watch_state: str) -> bool:
    return watch_state == "ready_to_buy"


MAX_SWING_HOLDING_DAYS = 15  # 波段最長持有天數


def should_exit_position(
    *,
    stop_loss_hit: bool,
    close_below_ma10: bool,
    flow_weakened: bool,
    holding_days: int,
) -> str | None:
    """Return an exit reason code, or None if the position should be held."""
    if stop_loss_hit:
        return "stop_loss"
    if close_below_ma10:
        return "ma10_break"
    if flow_weakened:
        return "flow_weakened"
    if holding_days > MAX_SWING_HOLDING_DAYS:
        return "time_exit"
    return None


class RetailFlowSwingStrategy:
    def compute_flow_score(self, row: InstitutionalFlowRow) -> float:
        return compute_flow_score(row)

    def classify_watch_state(
        self,
        *,
        flow_score: float,
        above_ma10: bool,
        volume_confirmed: bool,
        recent_runup_pct: float,
        consecutive_trust_days: int = 0,
    ) -> str:
        return classify_watch_state(
            flow_score=flow_score,
            above_ma10=above_ma10,
            volume_confirmed=volume_confirmed,
            recent_runup_pct=recent_runup_pct,
            consecutive_trust_days=consecutive_trust_days,
        )

    def should_enter_position(self, *, watch_state: str) -> bool:
        return should_enter_position(watch_state=watch_state)

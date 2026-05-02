from __future__ import annotations

from sector_rotation_signal_builder import SectorFeatureSnapshot

SECTOR_STATE_WATCH = "watch"
SECTOR_STATE_EMERGING = "emerging"
SECTOR_STATE_ACTIVE = "active"
SECTOR_STATE_WEAKENING = "weakening"
SECTOR_STATE_EXIT = "exit"

ALLOWED_TRANSITIONS = {
    SECTOR_STATE_WATCH: {SECTOR_STATE_WATCH, SECTOR_STATE_EMERGING},
    SECTOR_STATE_EMERGING: {SECTOR_STATE_WATCH, SECTOR_STATE_EMERGING, SECTOR_STATE_ACTIVE},
    SECTOR_STATE_ACTIVE: {SECTOR_STATE_ACTIVE, SECTOR_STATE_WEAKENING},
    SECTOR_STATE_WEAKENING: {SECTOR_STATE_ACTIVE, SECTOR_STATE_WEAKENING, SECTOR_STATE_EXIT},
    SECTOR_STATE_EXIT: {SECTOR_STATE_EXIT, SECTOR_STATE_EMERGING},
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _relative_strength_score(feature: SectorFeatureSnapshot) -> float:
    score_20 = _clamp((feature.relative_strength_20 + 10.0) / 20.0)
    score_60 = _clamp((feature.relative_strength_60 + 15.0) / 30.0)
    return (score_20 * 0.6) + (score_60 * 0.4)


def _breadth_score(feature: SectorFeatureSnapshot) -> float:
    return (
        feature.breadth_positive_return_pct * 0.45
        + feature.breadth_positive_flow_pct * 0.45
        + feature.breadth_above_ma10_pct * 0.10
    )


def score_sector_feature(feature: SectorFeatureSnapshot) -> float:
    return round(
        feature.chip_score * 0.4
        + _relative_strength_score(feature) * 0.35
        + _breadth_score(feature) * 0.25,
        6,
    )


def classify_sector_state(
    *,
    previous_state: str,
    feature: SectorFeatureSnapshot,
    rank_pct: float,
) -> str:
    if (
        feature.chip_score < 0.12
        and feature.relative_strength_20 < -3.0
        and feature.breadth_positive_return_pct < 0.2
    ):
        return SECTOR_STATE_EXIT

    if previous_state in {SECTOR_STATE_ACTIVE, SECTOR_STATE_EMERGING} and (
        rank_pct < 0.5
        or feature.chip_score < 0.18
        or feature.relative_strength_20 < -2.0
    ):
        return SECTOR_STATE_WEAKENING

    if (
        rank_pct >= 0.8
        and feature.chip_score >= 0.28
        and feature.relative_strength_20 >= -0.5
        and feature.breadth_positive_flow_pct >= 0.6
        and feature.breadth_positive_return_pct >= 0.35
    ):
        return SECTOR_STATE_ACTIVE

    if (
        rank_pct >= 0.35
        and feature.chip_score >= 0.16
        and feature.relative_strength_20 >= -2.5
        and feature.breadth_positive_flow_pct >= 0.4
        and (
            feature.breadth_positive_return_pct >= 0.2
            or feature.relative_strength_20 >= -1.5
        )
    ):
        return SECTOR_STATE_EMERGING

    return SECTOR_STATE_WATCH


def transition_sector_state(
    *,
    previous_state: str,
    feature: SectorFeatureSnapshot,
    rank_pct: float,
) -> str:
    candidate = classify_sector_state(
        previous_state=previous_state,
        feature=feature,
        rank_pct=rank_pct,
    )
    allowed = ALLOWED_TRANSITIONS.get(previous_state, {candidate})
    if candidate in allowed:
        return candidate
    if previous_state == SECTOR_STATE_WATCH and candidate == SECTOR_STATE_ACTIVE:
        return SECTOR_STATE_EMERGING
    if previous_state == SECTOR_STATE_ACTIVE and candidate == SECTOR_STATE_EXIT:
        return SECTOR_STATE_WEAKENING
    if previous_state == SECTOR_STATE_EXIT and candidate == SECTOR_STATE_ACTIVE:
        return SECTOR_STATE_EMERGING
    return previous_state


def _rank_percentiles(features: dict[str, SectorFeatureSnapshot]) -> dict[str, float]:
    ranked = sorted(
        ((sector, score_sector_feature(feature)) for sector, feature in features.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    total = len(ranked)
    if total == 0:
        return {}
    if total == 1:
        return {ranked[0][0]: 1.0}
    return {
        sector: 1.0 - (index / (total - 1))
        for index, (sector, _score) in enumerate(ranked)
    }


def build_sector_states(
    *,
    previous_state_map: dict[str, str] | None,
    features: dict[str, SectorFeatureSnapshot],
) -> dict[str, str]:
    previous_state_map = previous_state_map or {}
    rank_pcts = _rank_percentiles(features)
    return {
        sector: transition_sector_state(
            previous_state=previous_state_map.get(sector, SECTOR_STATE_WATCH),
            feature=feature,
            rank_pct=rank_pcts.get(sector, 0.0),
        )
        for sector, feature in features.items()
    }

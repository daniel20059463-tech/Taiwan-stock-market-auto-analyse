from sector_rotation_signal_builder import SectorFeatureSnapshot
from sector_rotation_state_machine import build_sector_states, transition_sector_state


def _feature(
    *,
    sector: str,
    chip_score: float,
    rs20: float,
    rs60: float,
    breadth_return: float,
    breadth_ma10: float,
    breadth_flow: float,
) -> SectorFeatureSnapshot:
    return SectorFeatureSnapshot(
        sector=sector,
        symbol_count=6,
        chip_score=chip_score,
        relative_strength_20=rs20,
        relative_strength_60=rs60,
        breadth_positive_return_pct=breadth_return,
        breadth_above_ma10_pct=breadth_ma10,
        breadth_positive_flow_pct=breadth_flow,
        top_symbols=["2330", "2454", "2303"],
    )


def test_transition_watch_to_emerging_for_high_rank_sector() -> None:
    feature = _feature(
        sector="semi",
        chip_score=0.34,
        rs20=-0.4,
        rs60=-0.2,
        breadth_return=0.48,
        breadth_ma10=0.0,
        breadth_flow=0.72,
    )

    assert transition_sector_state(previous_state="watch", feature=feature, rank_pct=0.9) == "emerging"


def test_transition_watch_to_emerging_for_mid_rank_sector_when_chip_and_flow_are_good() -> None:
    feature = _feature(
        sector="agri",
        chip_score=0.18,
        rs20=-2.0,
        rs60=-0.8,
        breadth_return=0.24,
        breadth_ma10=0.0,
        breadth_flow=0.54,
    )

    assert transition_sector_state(previous_state="watch", feature=feature, rank_pct=0.42) == "emerging"


def test_transition_emerging_to_active_when_top_rank_and_breadth_hold() -> None:
    feature = _feature(
        sector="semi",
        chip_score=0.31,
        rs20=0.1,
        rs60=-0.1,
        breadth_return=0.42,
        breadth_ma10=0.0,
        breadth_flow=0.68,
    )

    assert transition_sector_state(previous_state="emerging", feature=feature, rank_pct=0.95) == "active"


def test_transition_active_to_weakening_when_rank_and_rs_break() -> None:
    feature = _feature(
        sector="semi",
        chip_score=0.19,
        rs20=-2.2,
        rs60=-1.0,
        breadth_return=0.24,
        breadth_ma10=0.0,
        breadth_flow=0.41,
    )

    assert transition_sector_state(previous_state="active", feature=feature, rank_pct=0.2) == "weakening"


def test_transition_weakening_to_exit_when_sector_fully_breaks() -> None:
    feature = _feature(
        sector="semi",
        chip_score=0.08,
        rs20=-3.4,
        rs60=-2.0,
        breadth_return=0.12,
        breadth_ma10=0.0,
        breadth_flow=0.18,
    )

    assert transition_sector_state(previous_state="weakening", feature=feature, rank_pct=0.1) == "exit"


def test_transition_exit_to_emerging_does_not_jump_directly_to_active() -> None:
    feature = _feature(
        sector="semi",
        chip_score=0.34,
        rs20=0.3,
        rs60=0.1,
        breadth_return=0.5,
        breadth_ma10=0.1,
        breadth_flow=0.74,
    )

    assert transition_sector_state(previous_state="exit", feature=feature, rank_pct=0.95) == "emerging"


def test_build_sector_states_uses_relative_rank_to_create_mixed_states() -> None:
    features = {
        "semi": _feature(
            sector="semi",
            chip_score=0.33,
            rs20=-0.3,
            rs60=-0.2,
            breadth_return=0.46,
            breadth_ma10=0.0,
            breadth_flow=0.7,
        ),
        "pc": _feature(
            sector="pc",
            chip_score=0.27,
            rs20=-1.0,
            rs60=-0.8,
            breadth_return=0.36,
            breadth_ma10=0.0,
            breadth_flow=0.58,
        ),
        "shipping": _feature(
            sector="shipping",
            chip_score=0.1,
            rs20=-3.6,
            rs60=-2.5,
            breadth_return=0.08,
            breadth_ma10=0.0,
            breadth_flow=0.2,
        ),
    }

    states = build_sector_states(
        previous_state_map={
            "semi": "emerging",
            "pc": "watch",
            "shipping": "weakening",
        },
        features=features,
    )

    assert states["semi"] == "active"
    assert states["pc"] == "emerging"
    assert states["shipping"] == "exit"

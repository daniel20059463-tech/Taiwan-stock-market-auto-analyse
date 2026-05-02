from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_price_cache import DailyPriceCache
from institutional_flow_cache import InstitutionalFlowCache
from sector_rotation_signal_builder import build_sector_features
from sector_rotation_signal_cache import SectorSignalCache, SectorSignalRecord
from sector_rotation_state_machine import build_sector_states

DEFAULT_FLOW_CACHE = ROOT / "data" / "flow_cache.json"
DEFAULT_DAILY_CACHE = ROOT / "data" / "daily_price_cache.json"
DEFAULT_SECTOR_MAP = (
    ROOT / "data" / "full_sector_map.json"
    if (ROOT / "data" / "full_sector_map.json").exists()
    else ROOT / "data" / "sector_map.json"
)
DEFAULT_OUTPUT = ROOT / "data" / "sector_rotation_signals.json"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _normalize_chip_score(chip_score: float) -> float:
    return _clamp(chip_score)


def _normalize_relative_strength(relative_strength_20: float, relative_strength_60: float) -> float:
    score_20 = _clamp((relative_strength_20 + 10.0) / 20.0)
    score_60 = _clamp((relative_strength_60 + 15.0) / 30.0)
    return (score_20 * 0.6) + (score_60 * 0.4)


def _normalize_breadth(feature) -> float:
    return (
        feature.breadth_positive_return_pct
        + feature.breadth_above_ma10_pct
        + feature.breadth_positive_flow_pct
    ) / 3.0


def _build_signal_record(feature, state: str) -> SectorSignalRecord:
    chip_component = _normalize_chip_score(feature.chip_score)
    rs_component = _normalize_relative_strength(
        feature.relative_strength_20,
        feature.relative_strength_60,
    )
    breadth_component = _normalize_breadth(feature)
    sector_flow_score = round(
        (chip_component * 0.4) + (rs_component * 0.35) + (breadth_component * 0.25),
        4,
    )
    return SectorSignalRecord(
        sector=feature.sector,
        state=state,
        sector_flow_score=sector_flow_score,
        chip_score=feature.chip_score,
        relative_strength_20=feature.relative_strength_20,
        relative_strength_60=feature.relative_strength_60,
        breadth_positive_return_pct=feature.breadth_positive_return_pct,
        breadth_above_ma10_pct=feature.breadth_above_ma10_pct,
        breadth_positive_flow_pct=feature.breadth_positive_flow_pct,
        top_symbols=list(feature.top_symbols),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build daily sector rotation signals.")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--flow-cache", default=str(DEFAULT_FLOW_CACHE))
    parser.add_argument("--daily-cache", default=str(DEFAULT_DAILY_CACHE))
    parser.add_argument("--sector-map", default=str(DEFAULT_SECTOR_MAP))
    parser.add_argument("--market-symbol", default="TAIEX")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    flow_cache = InstitutionalFlowCache()
    flow_cache.load(args.flow_cache)

    daily_cache = DailyPriceCache()
    daily_cache.load(args.daily_cache)

    sector_map = json.loads(Path(args.sector_map).read_text(encoding="utf-8"))

    signal_cache = SectorSignalCache()
    signal_cache.load(args.output)

    previous_state_map: dict[str, str] = {}
    for previous_date in reversed(signal_cache.available_dates()):
        if previous_date < args.trade_date:
            previous_state_map = {
                sector: record.state
                for sector, record in signal_cache.sectors_for_date(previous_date).items()
            }
            break

    features = build_sector_features(
        trade_date=args.trade_date,
        flow_cache=flow_cache,
        daily_cache=daily_cache,
        sector_map=sector_map,
        market_symbol=args.market_symbol,
    )
    if not features:
        latest_trade_date = flow_cache.available_dates()[-1] if flow_cache.available_dates() else "N/A"
        raise SystemExit(
            f"no sector features for trade_date={args.trade_date}; "
            f"latest flow cache date={latest_trade_date}"
        )
    states = build_sector_states(
        previous_state_map=previous_state_map,
        features=features,
    )
    records = {
        sector: _build_signal_record(feature, states[sector])
        for sector, feature in features.items()
    }
    signal_cache.store(trade_date=args.trade_date, sectors=records)
    signal_cache.save(args.output)
    print(f"wrote {len(records)} sector signals to {args.output}")


if __name__ == "__main__":
    main()

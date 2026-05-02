from __future__ import annotations

from dataclasses import dataclass

from daily_price_cache import DailyPriceCache
from institutional_flow_cache import InstitutionalFlowCache
from retail_flow_strategy import compute_flow_score


@dataclass(frozen=True)
class SectorFeatureSnapshot:
    sector: str
    symbol_count: int
    chip_score: float
    relative_strength_20: float
    relative_strength_60: float
    breadth_positive_return_pct: float
    breadth_above_ma10_pct: float
    breadth_positive_flow_pct: float
    top_symbols: list[str]


def _pct_return(closes: list[float]) -> float:
    if len(closes) < 2 or closes[0] <= 0:
        return 0.0
    return ((closes[-1] / closes[0]) - 1.0) * 100.0


def _symbol_return(
    daily_cache: DailyPriceCache,
    symbol: str,
    *,
    as_of_date: str,
    lookback_bars: int,
) -> float:
    closes = daily_cache.get_closes(symbol, as_of_date=as_of_date, n=lookback_bars + 1)
    return _pct_return(closes)


def build_sector_features(
    *,
    trade_date: str,
    flow_cache: InstitutionalFlowCache,
    daily_cache: DailyPriceCache,
    sector_map: dict[str, str],
    market_symbol: str = "TAIEX",
) -> dict[str, SectorFeatureSnapshot]:
    market_return_20 = _symbol_return(
        daily_cache,
        market_symbol,
        as_of_date=trade_date,
        lookback_bars=20,
    )
    market_return_60 = _symbol_return(
        daily_cache,
        market_symbol,
        as_of_date=trade_date,
        lookback_bars=60,
    )

    buckets: dict[str, list] = {}
    for row in flow_cache.rows_for_date(trade_date):
        sector = sector_map.get(row.symbol, "").strip()
        if not sector:
            continue
        buckets.setdefault(sector, []).append(row)

    snapshots: dict[str, SectorFeatureSnapshot] = {}
    for sector, rows in buckets.items():
        chip_total = 0.0
        rs20_values: list[float] = []
        rs60_values: list[float] = []
        positive_return_count = 0
        above_ma10_count = 0
        positive_flow_count = 0
        contributions: list[tuple[str, float]] = []

        for row in rows:
            flow_score = compute_flow_score(row)
            chip_total += flow_score
            contributions.append((row.symbol, flow_score))
            if flow_score > 0:
                positive_flow_count += 1

            symbol_return_20 = _symbol_return(
                daily_cache,
                row.symbol,
                as_of_date=trade_date,
                lookback_bars=20,
            )
            symbol_return_60 = _symbol_return(
                daily_cache,
                row.symbol,
                as_of_date=trade_date,
                lookback_bars=60,
            )
            rs20 = symbol_return_20 - market_return_20
            rs60 = symbol_return_60 - market_return_60
            rs20_values.append(rs20)
            rs60_values.append(rs60)
            if symbol_return_20 > 0:
                positive_return_count += 1

            bars = daily_cache.get_bars(row.symbol, as_of_date=trade_date, n=10)
            if len(bars) >= 10:
                ma10 = sum(bar.close for bar in bars[-10:]) / 10.0
                if bars[-1].close >= ma10:
                    above_ma10_count += 1

        symbol_count = len(rows)
        contributions.sort(key=lambda item: item[1], reverse=True)
        snapshots[sector] = SectorFeatureSnapshot(
            sector=sector,
            symbol_count=symbol_count,
            chip_score=round(chip_total / symbol_count, 4) if symbol_count else 0.0,
            relative_strength_20=round(sum(rs20_values) / symbol_count, 4) if symbol_count else 0.0,
            relative_strength_60=round(sum(rs60_values) / symbol_count, 4) if symbol_count else 0.0,
            breadth_positive_return_pct=round(positive_return_count / symbol_count, 4) if symbol_count else 0.0,
            breadth_above_ma10_pct=round(above_ma10_count / symbol_count, 4) if symbol_count else 0.0,
            breadth_positive_flow_pct=round(positive_flow_count / symbol_count, 4) if symbol_count else 0.0,
            top_symbols=[symbol for symbol, _score in contributions[:3]],
        )
    return snapshots

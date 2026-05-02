from daily_price_cache import DailyBar, DailyPriceCache
from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow
from sector_rotation_signal_builder import build_sector_features


def _seed_symbol_bars(
    cache: DailyPriceCache,
    symbol: str,
    *,
    start: float,
    step: float,
    count: int = 60,
) -> None:
    for index in range(count):
        close = start + (step * index)
        cache.add_bar(
            symbol,
            DailyBar(
                date=f"2026-02-{index + 1:02d}",
                open=close - 0.2,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1_000 + (index * 10),
            ),
        )


def test_build_sector_features_aggregates_chip_strength_rs_and_breadth() -> None:
    flow_cache = InstitutionalFlowCache()
    flow_cache.store(
        trade_date="2026-04-27",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=1_000,
                investment_trust_net_buy=800,
                major_net_buy=600,
                avg_daily_volume_20d=10_000,
            ),
            InstitutionalFlowRow(
                symbol="2303",
                name="UMC",
                foreign_net_buy=500,
                investment_trust_net_buy=300,
                major_net_buy=200,
                avg_daily_volume_20d=8_000,
            ),
        ],
    )
    daily_cache = DailyPriceCache()
    _seed_symbol_bars(daily_cache, "TAIEX", start=100.0, step=0.2)
    _seed_symbol_bars(daily_cache, "2330", start=100.0, step=0.5)
    _seed_symbol_bars(daily_cache, "2303", start=100.0, step=0.4)
    sector_map = {"2330": "24 半導體業", "2303": "24 半導體業"}

    signals = build_sector_features(
        trade_date="2026-04-27",
        flow_cache=flow_cache,
        daily_cache=daily_cache,
        sector_map=sector_map,
        market_symbol="TAIEX",
    )

    semi = signals["24 半導體業"]
    assert semi.symbol_count == 2
    assert semi.chip_score > 0
    assert semi.relative_strength_20 > 0
    assert semi.breadth_above_ma10_pct == 1.0

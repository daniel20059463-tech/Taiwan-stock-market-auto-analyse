import subprocess
import sys

from daily_price_cache import DailyBar, DailyPriceCache
from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow
from sector_rotation_signal_cache import SectorSignalCache, SectorSignalRecord


def test_sector_signal_cache_round_trips_json(tmp_path) -> None:
    cache = SectorSignalCache()
    cache.store(
        trade_date="2026-04-27",
        sectors={
            "24 半導體業": SectorSignalRecord(
                sector="24 半導體業",
                state="active",
                sector_flow_score=0.8,
                chip_score=0.7,
                relative_strength_20=2.0,
                relative_strength_60=1.0,
                breadth_positive_return_pct=0.6,
                breadth_above_ma10_pct=0.7,
                breadth_positive_flow_pct=0.5,
                top_symbols=["2330", "2454"],
            )
        },
    )
    path = tmp_path / "sector_signals.json"
    cache.save(str(path))

    restored = SectorSignalCache()
    restored.load(str(path))

    assert restored.get("2026-04-27", "24 半導體業").state == "active"


def test_build_sector_rotation_signals_cli_writes_output(tmp_path) -> None:
    flow_cache = InstitutionalFlowCache()
    flow_cache.store(
        trade_date="2026-04-27",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="TSMC",
                foreign_net_buy=800,
                investment_trust_net_buy=700,
                major_net_buy=500,
                avg_daily_volume_20d=10_000,
            ),
        ],
    )
    flow_path = tmp_path / "flow_cache.json"
    flow_cache.save(str(flow_path))

    daily_cache = DailyPriceCache()
    for index in range(60):
        date = f"2026-02-{index + 1:02d}"
        daily_cache.add_bar(
            "TAIEX",
            DailyBar(date=date, open=100 + index, high=101 + index, low=99 + index, close=100 + index, volume=10_000),
        )
        daily_cache.add_bar(
            "2330",
            DailyBar(date=date, open=100 + index, high=102 + index, low=99 + index, close=101 + index, volume=20_000),
        )
    daily_path = tmp_path / "daily_price_cache.json"
    daily_cache.save(str(daily_path))

    sector_map_path = tmp_path / "sector_map.json"
    sector_map_path.write_text('{"2330":"24 半導體業"}', encoding="utf-8")
    output_path = tmp_path / "sector_signals.json"

    result = subprocess.run(
        [
            sys.executable,
            r".\scripts\build_sector_rotation_signals.py",
            "--trade-date",
            "2026-04-27",
            "--output",
            str(output_path),
            "--flow-cache",
            str(flow_path),
            "--daily-cache",
            str(daily_path),
            "--sector-map",
            str(sector_map_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=r"E:\claude code test",
    )
    assert result.returncode == 0, result.stderr
    restored = SectorSignalCache()
    restored.load(str(output_path))
    assert restored.get("2026-04-27", "24 半導體業") is not None

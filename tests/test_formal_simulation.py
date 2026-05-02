from __future__ import annotations

import datetime
import json
from pathlib import Path

from formal_simulation import expected_previous_open_trade_date
from formal_simulation import run_formal_simulation_preflight
from sector_rotation_signal_cache import SectorSignalCache
from sector_rotation_signal_cache import SectorSignalRecord


def _write_cache(path: Path, trade_date: str) -> None:
    cache = SectorSignalCache()
    cache.store(
        trade_date=trade_date,
        sectors={
            "半導體": SectorSignalRecord(
                sector="半導體",
                state="emerging",
                sector_flow_score=0.6,
                chip_score=0.4,
                relative_strength_20=1.0,
                relative_strength_60=0.5,
                breadth_positive_return_pct=0.5,
                breadth_above_ma10_pct=0.3,
                breadth_positive_flow_pct=0.7,
                top_symbols=["2330"],
            )
        },
    )
    cache.save(str(path))


def test_expected_previous_open_trade_date_uses_previous_day_when_today_is_open() -> None:
    now = datetime.datetime(2026, 4, 30, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    dates = {"2026-04-28", "2026-04-29", "2026-04-30"}
    assert expected_previous_open_trade_date(now=now, known_open_dates=dates) == "2026-04-29"


def test_formal_simulation_preflight_passes_for_live_1m_with_fresh_sector_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "sector_rotation_signals.json"
    _write_cache(cache_path, "2026-04-29")
    env = {
        "SINOPAC_MOCK": "false",
        "ACCOUNT_CAPITAL": "1000000",
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_CHAT_ID": "123",
    }

    result = run_formal_simulation_preflight(
        env=env,
        now=datetime.datetime(2026, 4, 30, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
        sector_signal_path=str(cache_path),
        known_open_dates={"2026-04-28", "2026-04-29", "2026-04-30"},
        telegram_validator=lambda **_: (True, []),
    )

    assert result.ok is True
    assert result.errors == []
    assert result.account_capital == 1_000_000.0


def test_formal_simulation_preflight_rejects_mock_mode(tmp_path: Path) -> None:
    cache_path = tmp_path / "sector_rotation_signals.json"
    _write_cache(cache_path, "2026-04-29")
    env = {
        "SINOPAC_MOCK": "true",
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_CHAT_ID": "123",
    }

    result = run_formal_simulation_preflight(
        env=env,
        now=datetime.datetime(2026, 4, 30, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
        sector_signal_path=str(cache_path),
        known_open_dates={"2026-04-28", "2026-04-29", "2026-04-30"},
        telegram_validator=lambda **_: (True, []),
    )

    assert result.ok is False
    assert "sinopac_mock_enabled" in result.errors


def test_formal_simulation_preflight_rejects_stale_sector_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "sector_rotation_signals.json"
    _write_cache(cache_path, "2026-04-28")
    env = {
        "SINOPAC_MOCK": "false",
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_CHAT_ID": "123",
    }

    result = run_formal_simulation_preflight(
        env=env,
        now=datetime.datetime(2026, 4, 30, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
        sector_signal_path=str(cache_path),
        known_open_dates={"2026-04-28", "2026-04-29", "2026-04-30"},
        telegram_validator=lambda **_: (True, []),
    )

    assert result.ok is False
    assert any(error.startswith("sector_signal_cache_stale:") for error in result.errors)


def test_formal_simulation_preflight_rejects_telegram_failure(tmp_path: Path) -> None:
    cache_path = tmp_path / "sector_rotation_signals.json"
    _write_cache(cache_path, "2026-04-29")
    env = {
        "SINOPAC_MOCK": "false",
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_CHAT_ID": "123",
    }

    result = run_formal_simulation_preflight(
        env=env,
        now=datetime.datetime(2026, 4, 30, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
        sector_signal_path=str(cache_path),
        known_open_dates={"2026-04-28", "2026-04-29", "2026-04-30"},
        telegram_validator=lambda **_: (False, ["telegram_getChat_failed:forbidden"]),
    )

    assert result.ok is False
    assert "telegram_getChat_failed:forbidden" in result.errors

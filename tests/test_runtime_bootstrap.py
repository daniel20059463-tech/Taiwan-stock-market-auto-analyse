from __future__ import annotations

import types
import datetime

import runtime_bootstrap


class _FakeCache:
    def load(self, path: str) -> None:
        return None

    def has_enough_data(self, symbol: str, min_bars: int) -> bool:
        return False

    def prune(self) -> None:
        return None

    def save(self, path: str) -> None:
        return None

    def symbols(self) -> list[str]:
        return []


def test_prime_daily_price_cache_skips_startup_backfill_by_default(monkeypatch):
    imported_names: list[str] = []

    fake_cache_module = types.SimpleNamespace(
        DailyPriceCache=_FakeCache,
        DailyBar=lambda **kwargs: kwargs,
    )

    def fake_import_module(name: str):
        imported_names.append(name)
        if name == "daily_price_cache":
            return fake_cache_module
        if name == "historical_data":
            raise AssertionError("historical_data should not be imported when startup backfill is disabled")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.delenv("DAILY_PRICE_BACKFILL_ON_STARTUP", raising=False)
    monkeypatch.setattr(runtime_bootstrap.importlib, "import_module", fake_import_module)

    cache = runtime_bootstrap._prime_daily_price_cache(["2330", "2317"])

    assert cache is not None
    assert imported_names == ["daily_price_cache"]


def test_load_sector_rotation_signals_injects_cache_into_trader(tmp_path):
    injected = {}

    class _FakeSectorSignalCache:
        def __init__(self) -> None:
            self.loaded_path: str | None = None

        def load(self, path: str) -> None:
            self.loaded_path = path

        def latest_trade_date(self) -> str | None:
            return None

    class _FakeTrader:
        def set_sector_signal_cache(self, cache) -> None:
            injected["cache"] = cache

    signal_path = tmp_path / "sector_rotation_signals.json"
    signal_path.write_text("{}", encoding="utf-8")

    runtime_bootstrap._load_sector_rotation_signals(
        _FakeTrader(),
        path=str(signal_path),
        cache_cls=_FakeSectorSignalCache,
    )

    assert "cache" in injected
    assert injected["cache"].loaded_path == str(signal_path)


def test_expected_sector_signal_trade_date_uses_previous_open_day_during_open_session() -> None:
    now = datetime.datetime(2026, 4, 28, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    open_dates = {"2026-04-24", "2026-04-27", "2026-04-28"}

    expected = runtime_bootstrap._expected_sector_signal_trade_date(
        now=now,
        known_open_dates=open_dates,
    )

    assert expected == "2026-04-27"

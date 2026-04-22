from __future__ import annotations

import types

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

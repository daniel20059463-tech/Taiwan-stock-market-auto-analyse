from __future__ import annotations

from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow
import strategy_runtime


class _FakeProvider:
    def fetch_rank_rows(self) -> list[InstitutionalFlowRow]:
        return [
            InstitutionalFlowRow(
                symbol="2330",
                name="台積電",
                foreign_net_buy=1000,
                investment_trust_net_buy=500,
                major_net_buy=200,
            )
        ]


def test_prime_flow_cache_uses_previous_open_day_for_retail_flow_swing(tmp_path):
    cache = InstitutionalFlowCache()
    dependencies = {
        "institutional_flow_provider": _FakeProvider(),
        "institutional_flow_cache": cache,
        "strategy_mode": "retail_flow_swing",
    }

    strategy_runtime.prime_institutional_flow_cache(
        dependencies,
        cache_path=str(tmp_path / "flow_cache.json"),
        today_trade_date_fn=lambda: "2026-04-22",
    )

    assert cache.get("2026-04-21", "2330") is not None
    assert cache.get("2026-04-22", "2330") is None


def test_prime_flow_cache_keeps_today_for_non_swing_mode(tmp_path):
    cache = InstitutionalFlowCache()
    dependencies = {
        "institutional_flow_provider": _FakeProvider(),
        "institutional_flow_cache": cache,
        "strategy_mode": "intraday",
    }

    strategy_runtime.prime_institutional_flow_cache(
        dependencies,
        cache_path=str(tmp_path / "flow_cache.json"),
        today_trade_date_fn=lambda: "2026-04-22",
    )

    assert cache.get("2026-04-22", "2330") is not None


from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow


def test_cache_stores_rows_by_trade_date_and_symbol() -> None:
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-17",
        rows=[
            InstitutionalFlowRow(
                symbol="2330",
                name="台積電",
                foreign_net_buy=1000,
                investment_trust_net_buy=500,
                major_net_buy=800,
            )
        ],
    )

    row = cache.get("2026-04-17", "2330")

    assert row is not None
    assert row.foreign_net_buy == 1000


def test_cache_returns_none_for_missing_symbol() -> None:
    cache = InstitutionalFlowCache()

    assert cache.get("2026-04-17", "1101") is None

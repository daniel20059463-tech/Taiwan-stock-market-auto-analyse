from __future__ import annotations

import asyncio

from sinopac_bridge import SinopacCollector, _bind_index_tick_handler, _merge_seed_meta, _sanitize_quote_payload


def test_merge_seed_meta_prefers_sinopac_primary_values() -> None:
    primary = {
        "name": "台積電",
        "lastPrice": 950.0,
        "previousClose": 945.0,
        "open": 948.0,
        "high": 952.0,
        "low": 944.0,
        "totalVolume": 120_000,
    }
    fallback = {
        "name": "2330",
        "lastPrice": 930.0,
        "previousClose": 900.0,
        "open": 910.0,
        "high": 940.0,
        "low": 905.0,
        "totalVolume": 80_000,
    }

    merged = _merge_seed_meta(primary, fallback)

    assert merged["name"] == "台積電"
    assert merged["lastPrice"] == 950.0
    assert merged["previousClose"] == 945.0
    assert merged["totalVolume"] == 120_000


def test_sanitize_quote_payload_rejects_abnormal_price_deviation() -> None:
    payload = {
        "symbol": "2330",
        "name": "台積電",
        "sector": "24",
        "price": 1300.0,
        "previousClose": 950.0,
        "open": 960.0,
        "high": 1310.0,
        "low": 955.0,
        "volume": 1000,
        "totalVolume": 1000,
        "ts": 1_700_000_000_000,
    }

    assert _sanitize_quote_payload(payload) is None


def test_sanitize_quote_payload_normalizes_ohlc_and_volume() -> None:
    payload = {
        "symbol": "2317",
        "name": "鴻海",
        "sector": "24",
        "price": 155.0,
        "previousClose": 150.0,
        "open": 151.0,
        "high": 149.0,
        "low": 160.0,
        "volume": 200,
        "totalVolume": 100,
        "ts": 1_700_000_000_000,
    }

    sanitized = _sanitize_quote_payload(payload)

    assert sanitized is not None
    assert sanitized["high"] == 155.0
    assert sanitized["low"] == 151.0
    assert sanitized["totalVolume"] == 200
    assert sanitized["changePct"] == round((155.0 - 150.0) / 150.0 * 100, 2)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[object] = []
        self.remote_address = ("127.0.0.1", 12345)

    async def send(self, payload: object) -> None:
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_sinopac_collector_sends_initial_portfolio_snapshot_on_connect() -> None:
    class _FakeAutoTrader:
        def get_portfolio_snapshot(self) -> dict[str, object]:
            return {
                "type": "PAPER_PORTFOLIO",
                "positions": [],
                "recentTrades": [
                    {
                        "symbol": "2317",
                        "action": "SELL",
                        "price": 120.0,
                        "shares": 1000,
                        "reason": "STOP_LOSS",
                        "netPnl": -5000.0,
                        "grossPnl": -4800.0,
                        "ts": 1_700_000_000_000,
                    }
                ],
                "realizedPnl": -5000.0,
                "unrealizedPnl": 0.0,
                "totalPnl": -5000.0,
                "tradeCount": 1,
                "winRate": 0.0,
                "marketChangePct": 0.0,
                "riskStatus": {},
                "sessionId": "test-session",
            }

    collector = SinopacCollector(
        ["2317"],
        api_key="demo",
        secret_key="demo",
        auto_trader=_FakeAutoTrader(),
    )
    websocket = _FakeWebSocket()

    asyncio.run(collector._ws_handler(websocket))

    assert websocket.sent, "expected an initial websocket payload"
    assert '"type":"PAPER_PORTFOLIO"' in str(websocket.sent[0])


def test_bind_index_tick_handler_skips_when_shioaji_api_lacks_index_hook() -> None:
    class _FakeApi:
        pass

    called: list[object] = []

    def _callback(exchange, tick) -> None:
        called.append((exchange, tick))

    assert _bind_index_tick_handler(_FakeApi(), _callback) is False
    assert called == []

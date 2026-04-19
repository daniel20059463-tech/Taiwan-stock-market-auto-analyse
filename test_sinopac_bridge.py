from __future__ import annotations

import asyncio
import datetime
import json
import sys
import types

from sinopac_bridge import (
    SinopacCollector,
    _bind_index_tick_handler,
    _merge_seed_meta,
    _sanitize_quote_payload,
    _to_epoch_milliseconds,
    load_shioaji_stock_universe,
)


class _FakeQuote:
    def __init__(
        self,
        *,
        subscribe_failures: dict[str, int] | None = None,
        allow_unsubscribe: bool = True,
        unsubscribe_fail_symbols: set[str] | None = None,
    ) -> None:
        self.subscriptions: list[tuple[str, object, object]] = []
        self.unsubscriptions: list[tuple[str, object, object]] = []
        self.subscribe_attempts: list[tuple[str, object, object]] = []
        self.unsubscribe_attempts: list[tuple[str, object, object]] = []
        self.tick_callback = None
        self.bidask_callback = None
        self._subscribe_failures = dict(subscribe_failures or {})
        self._allow_unsubscribe = allow_unsubscribe
        self._unsubscribe_fail_symbols = set(unsubscribe_fail_symbols or set())

    def subscribe(self, contract, quote_type, version) -> None:
        entry = (contract.code, quote_type, version)
        self.subscribe_attempts.append(entry)
        remaining_failures = self._subscribe_failures.get(contract.code, 0)
        if remaining_failures > 0:
            self._subscribe_failures[contract.code] = remaining_failures - 1
            raise RuntimeError(f"subscribe failed for {contract.code}")
        self.subscriptions.append(entry)

    def unsubscribe(self, contract, quote_type, version) -> None:
        if not self._allow_unsubscribe:
            raise AttributeError("unsubscribe unavailable")
        entry = (contract.code, quote_type, version)
        self.unsubscribe_attempts.append(entry)
        if contract.code in self._unsubscribe_fail_symbols:
            raise RuntimeError(f"unsubscribe failed for {contract.code}")
        self.unsubscriptions.append(entry)

    def set_on_tick_stk_v1_callback(self, callback) -> None:
        self.tick_callback = callback

    def set_on_bidask_stk_v1_callback(self, callback) -> None:
        self.bidask_callback = callback


class _FakeApi:
    def __init__(self, contracts: dict[str, object]) -> None:
        self.quote = _FakeQuote()
        self.Contracts = types.SimpleNamespace(
            Stocks=types.SimpleNamespace(
                TSE=contracts,
                OTC={},
                OES={},
            ),
            Indices=types.SimpleNamespace(
                TSE={"TSE001": types.SimpleNamespace(code="TSE001")}
            ),
        )


def build_test_collector() -> tuple[SinopacCollector, _FakeApi]:
    symbols = ["2330", "2317", "2603"]
    contracts = {
        symbol: types.SimpleNamespace(code=symbol, name=symbol, category="Common")
        for symbol in symbols
    }
    collector = SinopacCollector(
        symbols,
        api_key="demo",
        secret_key="demo",
    )
    fake_api = _FakeApi(contracts)
    collector._api = fake_api
    collector._symbol_contracts = contracts
    collector._subscribed_visible_symbols = set()
    return collector, fake_api


def test_set_visible_symbols_updates_high_frequency_subscription_set(monkeypatch) -> None:
    collector, fake_api = build_test_collector()
    collector._loop = asyncio.new_event_loop()
    fake_shioaji = types.ModuleType("shioaji")
    fake_constant = types.ModuleType("shioaji.constant")
    fake_constant.QuoteType = types.SimpleNamespace(Tick="Tick", BidAsk="BidAsk")
    fake_constant.QuoteVersion = types.SimpleNamespace(v1="v1")
    monkeypatch.setitem(sys.modules, "shioaji", fake_shioaji)
    monkeypatch.setitem(sys.modules, "shioaji.constant", fake_constant)

    websocket = _FakeWebSocket()

    try:
        asyncio.run(
            collector._handle_ws_message(
                websocket,
                '{"type":"set_visible_symbols","symbols":["2330","2317"]}',
            )
        )
    finally:
        collector._loop.close()

    assert collector.visible_symbols == {"2330", "2317"}
    assert len(fake_api.quote.subscriptions) == 4
    assert set(fake_api.quote.subscriptions) == {
        ("2330", "Tick", "v1"),
        ("2330", "BidAsk", "v1"),
        ("2317", "Tick", "v1"),
        ("2317", "BidAsk", "v1"),
    }


def test_setting_same_visible_symbols_twice_does_not_reapply_subscription(monkeypatch) -> None:
    collector, fake_api = build_test_collector()
    fake_shioaji = types.ModuleType("shioaji")
    fake_constant = types.ModuleType("shioaji.constant")
    fake_constant.QuoteType = types.SimpleNamespace(Tick="Tick", BidAsk="BidAsk")
    fake_constant.QuoteVersion = types.SimpleNamespace(v1="v1")
    monkeypatch.setitem(sys.modules, "shioaji", fake_shioaji)
    monkeypatch.setitem(sys.modules, "shioaji.constant", fake_constant)

    collector.set_visible_symbols(["2330"])
    subscription_count = len(fake_api.quote.subscriptions)
    unsubscription_count = len(fake_api.quote.unsubscriptions)

    collector.set_visible_symbols(["2330"])

    assert collector.visible_symbols == {"2330"}
    assert len(fake_api.quote.subscriptions) == subscription_count
    assert len(fake_api.quote.unsubscriptions) == unsubscription_count


def test_set_visible_symbols_retries_after_partial_subscribe_failure() -> None:
    collector, fake_api = build_test_collector()
    fake_api.quote = _FakeQuote(subscribe_failures={"2317": 1})
    collector._api = fake_api

    collector.set_visible_symbols(["2330", "2317"])
    first_attempts = list(fake_api.quote.subscribe_attempts)
    first_subscribed = set(collector._subscribed_visible_symbols)

    collector.set_visible_symbols(["2330", "2317"])

    assert collector.visible_symbols == {"2330", "2317"}
    assert first_subscribed == {"2330"}
    assert sum(1 for symbol, _, _ in fake_api.quote.subscribe_attempts if symbol == "2317") == 3
    assert sum(1 for symbol, _, _ in fake_api.quote.subscribe_attempts if symbol == "2330") == 2
    assert len(fake_api.quote.subscriptions) == 4
    assert collector._subscribed_visible_symbols == {"2330", "2317"}


def test_unsubscribe_failure_keeps_symbol_marked_subscribed() -> None:
    collector, fake_api = build_test_collector()
    fake_api.quote = _FakeQuote(unsubscribe_fail_symbols={"2330"})
    collector._api = fake_api

    collector.set_visible_symbols(["2330"])
    collector.set_visible_symbols([])

    assert collector.visible_symbols == set()
    assert collector._subscribed_visible_symbols == {"2330"}
    assert sum(1 for symbol, _, _ in fake_api.quote.unsubscribe_attempts if symbol == "2330") == 2


def test_missing_unsubscribe_keeps_symbol_marked_subscribed() -> None:
    collector, fake_api = build_test_collector()
    class _FakeQuoteWithoutUnsubscribe:
        def __init__(self) -> None:
            self.subscriptions: list[tuple[str, object, object]] = []
            self.subscribe_attempts: list[tuple[str, object, object]] = []
            self.unsubscriptions: list[tuple[str, object, object]] = []

        def subscribe(self, contract, quote_type, version) -> None:
            entry = (contract.code, quote_type, version)
            self.subscribe_attempts.append(entry)
            self.subscriptions.append(entry)

        def set_on_tick_stk_v1_callback(self, callback) -> None:
            return None

        def set_on_bidask_stk_v1_callback(self, callback) -> None:
            return None

    fake_api.quote = _FakeQuoteWithoutUnsubscribe()
    collector._api = fake_api

    collector.set_visible_symbols(["2330"])
    collector.set_visible_symbols([])

    assert collector.visible_symbols == set()
    assert collector._subscribed_visible_symbols == {"2330"}
    assert fake_api.quote.unsubscriptions == []


def test_load_shioaji_stock_universe_filters_to_twse_otc_ordinary_stocks() -> None:
    fake_api = types.SimpleNamespace(
        Contracts=types.SimpleNamespace(
            Stocks=types.SimpleNamespace(
                TSE={
                    "2330": types.SimpleNamespace(code="2330", name="台積電", category="半導體"),
                    "0050": types.SimpleNamespace(code="0050", name="元大台灣50", category="00"),
                    "12345": types.SimpleNamespace(code="12345", name="五位數普通股", category="半導體"),
                },
                OTC={
                    "3680": types.SimpleNamespace(code="3680", name="家登", category="半導體"),
                    "6488": types.SimpleNamespace(code="6488", name="環球晶", category="Warrant"),
                },
                OES={
                    "6543": types.SimpleNamespace(code="6543", name="普通股", category="半導體"),
                },
            )
        )
    )

    universe = load_shioaji_stock_universe(fake_api)

    assert set(universe) == {"2330", "3680"}
    assert universe["2330"]["market"] == "TSE"
    assert universe["3680"]["market"] == "OTC"
    assert "0050" not in universe
    assert "12345" not in universe
    assert "6488" not in universe
    assert "6543" not in universe


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


def test_sanitize_quote_payload_uses_taiwan_regular_trading_hours() -> None:
    in_session = _sanitize_quote_payload(
        {
            "symbol": "2330",
            "price": 950.0,
            "previousClose": 945.0,
            "open": 948.0,
            "high": 952.0,
            "low": 944.0,
            "volume": 100,
            "totalVolume": 500,
            "ts": int(datetime.datetime(2026, 4, 14, 9, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp() * 1000),
        }
    )
    after_close = _sanitize_quote_payload(
        {
            "symbol": "2330",
            "price": 950.0,
            "previousClose": 945.0,
            "open": 948.0,
            "high": 952.0,
            "low": 944.0,
            "volume": 100,
            "totalVolume": 500,
            "ts": int(datetime.datetime(2026, 4, 14, 13, 31, tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp() * 1000),
        }
    )

    assert in_session is not None
    assert after_close is not None
    assert in_session["inTradingHours"] is True
    assert after_close["inTradingHours"] is False


def test_load_symbol_meta_sync_does_not_use_last_close_as_previous_close_fallback() -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )
    collector._api = types.SimpleNamespace(
        snapshots=lambda contracts: [
            types.SimpleNamespace(
                close=25.25,
                open=25.50,
                high=25.55,
                low=25.00,
                total_volume=25000,
            )
        ]
    )

    meta = collector._load_symbol_meta_sync(
        types.SimpleNamespace(code="1101", name="台泥", category="普通股")
    )

    assert meta["lastPrice"] == 25.25
    assert meta["previousClose"] is None


def test_history_bars_sync_reconnects_and_retries_once_after_kbars_failure() -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )

    contract = types.SimpleNamespace(code="2330", name="台積電", category="24")
    first_api = types.SimpleNamespace(
        Contracts=types.SimpleNamespace(Stocks=types.SimpleNamespace(TSE={"2330": contract}, OTC={}, OES={})),
        kbars=lambda contract, start, end: (_ for _ in ()).throw(RuntimeError("Token is expired")),
    )
    second_api = types.SimpleNamespace(
        Contracts=types.SimpleNamespace(Stocks=types.SimpleNamespace(TSE={"2330": contract}, OTC={}, OES={})),
        kbars=lambda contract, start, end: types.SimpleNamespace(
            ts=[1_760_000_000, 1_760_086_400],
            Open=[100.0, 101.0],
            High=[102.0, 103.0],
            Low=[99.0, 100.0],
            Close=[101.0, 102.0],
            Volume=[1000, 1200],
        ),
    )
    collector._api = first_api

    reconnect_calls = {"count": 0}

    def reconnect() -> None:
        reconnect_calls["count"] += 1
        collector._api = second_api

    collector._reconnect_sync = reconnect  # type: ignore[method-assign]

    candles = collector._history_bars_sync("2330", months=1)

    assert reconnect_calls["count"] == 1
    assert len(candles) == 2
    assert candles[0]["open"] == 100.0
    assert candles[1]["close"] == 102.0


def test_session_bars_sync_reconnects_and_retries_once_after_kbars_failure() -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )

    contract = types.SimpleNamespace(code="2330", name="台積電", category="24")
    first_api = types.SimpleNamespace(
        Contracts=types.SimpleNamespace(Stocks=types.SimpleNamespace(TSE={"2330": contract}, OTC={}, OES={})),
        kbars=lambda contract, start, end: (_ for _ in ()).throw(RuntimeError("Topic: api/v1/data/kbars")),
    )
    second_api = types.SimpleNamespace(
        Contracts=types.SimpleNamespace(Stocks=types.SimpleNamespace(TSE={"2330": contract}, OTC={}, OES={})),
        kbars=lambda contract, start, end: types.SimpleNamespace(
            ts=[1_760_000_000],
            Open=[100.0],
            High=[101.0],
            Low=[99.0],
            Close=[100.5],
            Volume=[800],
        ),
    )
    collector._api = first_api

    reconnect_calls = {"count": 0}

    def reconnect() -> None:
        reconnect_calls["count"] += 1
        collector._api = second_api

    collector._reconnect_sync = reconnect  # type: ignore[method-assign]

    candles = collector._session_bars_sync("2330", limit=10)

    assert reconnect_calls["count"] == 1
    assert len(candles) == 1
    assert candles[0]["close"] == 100.5


def test_history_bars_sync_waits_and_reconnects_again_after_503_relogin_cooldown(monkeypatch) -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )

    contract = types.SimpleNamespace(code="2330", name="台積電", category="24")
    calls = {"count": 0}

    def kbars(contract, start, end):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Token is expired")
        if calls["count"] == 2:
            raise RuntimeError("StatusCode: 503, Detail: 操作異常，請1分鐘後再重新登入")
        return types.SimpleNamespace(
            ts=[1_760_000_000],
            Open=[100.0],
            High=[102.0],
            Low=[99.0],
            Close=[101.0],
            Volume=[1000],
        )

    collector._api = types.SimpleNamespace(
        Contracts=types.SimpleNamespace(Stocks=types.SimpleNamespace(TSE={"2330": contract}, OTC={}, OES={})),
        kbars=kbars,
    )

    reconnect_calls = {"count": 0}
    sleep_calls: list[float] = []

    def reconnect() -> None:
        reconnect_calls["count"] += 1

    monkeypatch.setattr("sinopac_bridge.time.sleep", lambda seconds: sleep_calls.append(seconds))
    collector._reconnect_sync = reconnect  # type: ignore[method-assign]

    candles = collector._history_bars_sync("2330", months=1)

    assert reconnect_calls["count"] == 2
    assert sleep_calls == [65.0]
    assert len(candles) == 1
    assert candles[0]["close"] == 101.0


class _FakeWebSocket:
    def __init__(self, incoming: list[object] | None = None) -> None:
        self.sent: list[object] = []
        self.remote_address = ("127.0.0.1", 12345)
        self._incoming = list(incoming or [])

    async def send(self, payload: object) -> None:
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


def _json_messages(payloads: list[object]) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for payload in payloads:
        if isinstance(payload, str):
            loaded = json.loads(payload)
            if isinstance(loaded, list):
                messages.extend(item for item in loaded if isinstance(item, dict))
            elif isinstance(loaded, dict):
                messages.append(loaded)
    return messages


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


def test_sinopac_collector_executes_manual_paper_trade_over_websocket() -> None:
    class _FakeAutoTrader:
        async def execute_manual_trade(
            self,
            *,
            symbol: str,
            action: str,
            shares: int,
            ts_ms: int | None = None,
        ) -> dict[str, object]:
            assert symbol == "2317"
            assert action == "SELL"
            assert shares == 1000
            return {
                "type": "PAPER_PORTFOLIO",
                "positions": [],
                "recentTrades": [
                    {
                        "symbol": "2317",
                        "action": "SELL",
                        "price": 120.0,
                        "shares": 1000,
                        "reason": "MANUAL",
                        "netPnl": 0.0,
                        "grossPnl": 0.0,
                        "ts": 1_700_000_000_000,
                    }
                ],
                "realizedPnl": 0.0,
                "unrealizedPnl": 0.0,
                "totalPnl": 0.0,
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
    collector._loop = asyncio.new_event_loop()
    websocket = _FakeWebSocket(
        incoming=['{"type":"paper_trade","symbol":"2317","action":"SELL","shares":1000}']
    )

    try:
        asyncio.run(collector._ws_handler(websocket))
    finally:
        collector._loop.close()

    assert any('"type":"PAPER_TRADE_RESULT"' in str(payload) for payload in websocket.sent)
    assert any('"type":"PAPER_PORTFOLIO"' in str(payload) for payload in websocket.sent[1:])


def test_sinopac_collector_subscribe_quote_detail_sends_native_order_book_snapshot() -> None:
    collector = SinopacCollector(
        ["2317"],
        api_key="demo",
        secret_key="demo",
    )
    collector._loop = asyncio.new_event_loop()
    collector._order_book_buffers["2317"] = {
        "timestamp": 1_700_000_000_123,
        "asks": [{"level": 1, "price": 123.5, "volume": 11}],
        "bids": [{"level": 1, "price": 123.0, "volume": 22}],
    }
    collector._current_ticks["2317"] = {
        "symbol": "2317",
        "price": 120.0,
        "volume": 1000,
        "totalVolume": 5000,
        "ts": 1_700_000_000_000,
    }
    websocket = _FakeWebSocket(
        incoming=['{"type":"subscribe_quote_detail","symbol":"2317"}']
    )

    try:
        asyncio.run(collector._ws_handler(websocket))
    finally:
        collector._loop.close()

    messages = _json_messages(websocket.sent)
    order_book = next(message for message in messages if message.get("type") == "ORDER_BOOK_SNAPSHOT")

    assert order_book["timestamp"] == 1_700_000_000_123
    assert order_book["asks"] == [{"level": 1, "price": 123.5, "volume": 11}]
    assert order_book["bids"] == [{"level": 1, "price": 123.0, "volume": 22}]


def test_sinopac_collector_subscribe_quote_detail_without_native_bidask_has_empty_order_book() -> None:
    collector = SinopacCollector(
        ["2317"],
        api_key="demo",
        secret_key="demo",
    )
    collector._loop = asyncio.new_event_loop()
    collector._current_ticks["2317"] = {
        "symbol": "2317",
        "price": 120.0,
        "volume": 1000,
        "totalVolume": 5000,
        "ts": 1_700_000_000_000,
    }
    websocket = _FakeWebSocket(
        incoming=['{"type":"subscribe_quote_detail","symbol":"2317"}']
    )

    try:
        asyncio.run(collector._ws_handler(websocket))
    finally:
        collector._loop.close()

    messages = _json_messages(websocket.sent)
    order_book = next(message for message in messages if message.get("type") == "ORDER_BOOK_SNAPSHOT")

    assert order_book["asks"] == []
    assert order_book["bids"] == []


def test_sinopac_collector_apply_native_bidask_pushes_quote_detail_snapshot_to_subscribers() -> None:
    class _FakeLoop:
        def is_closed(self) -> bool:
            return False

        def create_task(self, coroutine):
            return asyncio.run(coroutine)

    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )
    collector._loop = _FakeLoop()
    websocket = _FakeWebSocket()
    collector._clients.add(websocket)
    collector._quote_detail_subscriptions[websocket] = "2330"

    collector._apply_native_bidask(
        type(
            "NativeBidAsk",
            (),
            {
                "code": "2330",
                "datetime": datetime.datetime(2026, 4, 12, 9, 30, 15),
                "bid_price": [123.0],
                "bid_volume": [10],
                "ask_price": [123.5],
                "ask_volume": [11],
            },
        )(),
    )

    messages = _json_messages(websocket.sent)
    order_book = next(message for message in messages if message.get("type") == "ORDER_BOOK_SNAPSHOT")

    assert order_book["timestamp"] == int(datetime.datetime(2026, 4, 12, 9, 30, 15).timestamp() * 1000)
    assert order_book["asks"] == [{"level": 1, "price": 123.5, "volume": 11}]
    assert order_book["bids"] == [{"level": 1, "price": 123.0, "volume": 10}]


def test_sinopac_collector_build_order_book_snapshot_uses_native_buffers() -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )
    collector._order_book_buffers["2330"] = {
        "timestamp": 1_700_000_000_123,
        "asks": [
            {"level": 1, "price": 123.5, "volume": 11},
            {"level": 2, "price": 124.0, "volume": 22},
        ],
        "bids": [
            {"level": 1, "price": 122.5, "volume": 33},
            {"level": 2, "price": 122.0, "volume": 44},
        ],
    }

    snapshot = collector._build_order_book_snapshot("2330")

    assert snapshot["timestamp"] == 1_700_000_000_123
    assert snapshot["asks"] == collector._order_book_buffers["2330"]["asks"]
    assert snapshot["bids"] == collector._order_book_buffers["2330"]["bids"]


def test_sinopac_collector_build_order_book_snapshot_without_native_buffer_is_empty() -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )
    collector._current_ticks["2330"] = {
        "symbol": "2330",
        "price": 123.0,
        "ts": 1_700_000_000_000,
    }

    snapshot = collector._build_order_book_snapshot("2330")

    assert snapshot["asks"] == []
    assert snapshot["bids"] == []


def test_sinopac_collector_record_trade_tape_marks_side_by_direction() -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )

    collector._record_trade_tape("2330", price=100.0, volume=1000, ts_ms=1_700_000_000_000)
    collector._record_trade_tape("2330", price=101.0, volume=1000, ts_ms=1_700_000_001_000)
    collector._record_trade_tape("2330", price=100.5, volume=1000, ts_ms=1_700_000_002_000)

    rows = collector._build_trade_tape_snapshot("2330")["rows"]

    assert [row["side"] for row in rows] == ["neutral", "outer", "inner"]


def test_sinopac_collector_offer_tick_does_not_record_trade_tape() -> None:
    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )

    collector._offer_tick(
        {
            "symbol": "2330",
            "price": 100.0,
            "volume": 1000,
            "totalVolume": 1000,
            "ts": 1_700_000_000_000,
        }
    )

    assert collector._build_trade_tape_snapshot("2330")["rows"] == []


def test_sinopac_collector_record_native_tick_tape_normalizes_seconds_timestamp() -> None:
    assert _to_epoch_milliseconds(1_700_000_000) == 1_700_000_000_000
    assert _to_epoch_milliseconds(1_700_000_000_000) == 1_700_000_000_000
    assert _to_epoch_milliseconds(1_700_000_000_000_000) == 1_700_000_000_000

    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )

    collector._record_native_tick_tape(
        type(
            "NativeTick",
            (),
            {
                "code": "2330",
                "close": 100.0,
                "volume": 1000,
                "ts": 1_700_000_000,
            },
        )(),
    )

    rows = collector._build_trade_tape_snapshot("2330")["rows"]

    assert rows[0]["time"] == "06:13:20"
    assert rows[0]["price"] == 100.0


def test_sinopac_collector_apply_native_bidask_updates_order_book_buffer() -> None:
    from datetime import datetime
    from decimal import Decimal

    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
    )

    collector._apply_native_bidask(
        type(
            "NativeBidAsk",
            (),
            {
                "code": "2330",
                "datetime": datetime(2026, 4, 12, 9, 30, 15),
                "bid_price": [Decimal("123.0"), Decimal("122.5")],
                "bid_volume": [10, 20],
                "ask_price": [Decimal("123.5"), Decimal("124.0")],
                "ask_volume": [11, 22],
            },
        )(),
    )

    assert collector._order_book_buffers["2330"] == {
        "timestamp": int(datetime(2026, 4, 12, 9, 30, 15).timestamp() * 1000),
        "asks": [
            {"level": 1, "price": 123.5, "volume": 11},
            {"level": 2, "price": 124.0, "volume": 22},
        ],
        "bids": [
            {"level": 1, "price": 123.0, "volume": 10},
            {"level": 2, "price": 122.5, "volume": 20},
        ],
    }


def test_sinopac_collector_login_and_subscribe_sync_records_native_tick_tape_before_normalization(monkeypatch) -> None:
    import sinopac_bridge as bridge

    class _FakeLoop:
        def is_closed(self) -> bool:
            return False

        def call_soon_threadsafe(self, callback, *args) -> None:
            callback(*args)

    class _FakeQuote:
        def __init__(self) -> None:
            self.tick_callback = None
            self.bidask_callback = None

        def subscribe(self, contract, quote_type, version) -> None:
            return None

        def set_on_tick_stk_v1_callback(self, callback) -> None:
            self.tick_callback = callback

        def set_on_bidask_stk_v1_callback(self, callback) -> None:
            self.bidask_callback = callback

    class _FakeApi:
        def __init__(self) -> None:
            self.quote = _FakeQuote()
            self.Contracts = types.SimpleNamespace(
                Stocks=types.SimpleNamespace(
                    TSE={"2330": types.SimpleNamespace(code="2330")},
                    OTC={},
                    OES={},
                ),
                Indices=types.SimpleNamespace(
                    TSE={"TSE001": types.SimpleNamespace(code="TSE001")}
                ),
            )

        def login(self, *, api_key, secret_key) -> None:
            return None

        def logout(self) -> None:
            return None

        def snapshots(self, contracts) -> list[object]:
            return []

    fake_api = _FakeApi()
    fake_sj = types.SimpleNamespace(Shioaji=lambda simulation=False: fake_api)
    fake_constant = types.SimpleNamespace(
        QuoteType=types.SimpleNamespace(Tick="Tick", BidAsk="BidAsk"),
        QuoteVersion=types.SimpleNamespace(v1="v1"),
    )

    monkeypatch.setitem(sys.modules, "shioaji", fake_sj)
    monkeypatch.setitem(sys.modules, "shioaji.constant", fake_constant)
    monkeypatch.setattr(bridge, "_load_twse_seed_quotes", lambda symbols: {})

    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
        bootstrap_bar_limit=0,
    )
    collector._loop = _FakeLoop()

    collector._login_and_subscribe_sync()

    tick = types.SimpleNamespace(
        code="2330",
        price=123.0,
        volume=1000,
        ts=1_700_000_000_000,
    )
    assert fake_api.quote.tick_callback is not None

    fake_api.quote.tick_callback(None, tick)

    rows = collector._build_trade_tape_snapshot("2330")["rows"]
    assert rows and rows[0]["price"] == 123.0


def test_sinopac_collector_login_and_subscribe_sync_subscribes_tick_and_bidask(monkeypatch) -> None:
    import sinopac_bridge as bridge

    class _FakeLoop:
        def is_closed(self) -> bool:
            return False

        def call_soon_threadsafe(self, callback, *args) -> None:
            callback(*args)

    class _FakeQuote:
        def __init__(self) -> None:
            self.subscriptions: list[tuple[str, object, object]] = []
            self.tick_callback = None
            self.bidask_callback = None

        def subscribe(self, contract, quote_type, version) -> None:
            self.subscriptions.append((contract.code, quote_type, version))

        def set_on_tick_stk_v1_callback(self, callback) -> None:
            self.tick_callback = callback

        def set_on_bidask_stk_v1_callback(self, callback) -> None:
            self.bidask_callback = callback

    class _FakeApi:
        def __init__(self) -> None:
            self.quote = _FakeQuote()
            self.Contracts = types.SimpleNamespace(
                Stocks=types.SimpleNamespace(
                    TSE={
                        "2330": types.SimpleNamespace(code="2330"),
                        "2317": types.SimpleNamespace(code="2317"),
                    },
                    OTC={},
                    OES={},
                ),
                Indices=types.SimpleNamespace(
                    TSE={"TSE001": types.SimpleNamespace(code="TSE001")}
                ),
            )
            self.logged_in = None
            self.tick_callback = None

        def login(self, *, api_key, secret_key) -> None:
            self.logged_in = (api_key, secret_key)

        def logout(self) -> None:
            return None

        def snapshots(self, contracts) -> list[object]:
            return []

        def on_tick_stk_v1(self):
            def _decorator(callback):
                self.tick_callback = callback
                return callback

            return _decorator

    fake_api = _FakeApi()
    fake_sj = types.SimpleNamespace(Shioaji=lambda simulation=False: fake_api)
    fake_constant = types.SimpleNamespace(
        QuoteType=types.SimpleNamespace(Tick="Tick", BidAsk="BidAsk"),
        QuoteVersion=types.SimpleNamespace(v1="v1"),
    )

    monkeypatch.setitem(sys.modules, "shioaji", fake_sj)
    monkeypatch.setitem(sys.modules, "shioaji.constant", fake_constant)
    monkeypatch.setattr(bridge, "_load_twse_seed_quotes", lambda symbols: {})

    collector = SinopacCollector(
        ["2330", "2317"],
        api_key="demo",
        secret_key="demo",
        bootstrap_bar_limit=0,
    )
    collector._loop = _FakeLoop()

    applied_bidasks: list[object] = []
    collector._apply_native_bidask = lambda bidask: applied_bidasks.append(bidask)

    collector._login_and_subscribe_sync()

    assert fake_api.logged_in == ("demo", "demo")
    assert fake_api.quote.tick_callback is not None
    assert fake_api.quote.bidask_callback is not None
    assert fake_api.quote.subscriptions[:4] == [
        ("2330", "Tick", "v1"),
        ("2330", "BidAsk", "v1"),
        ("2317", "Tick", "v1"),
        ("2317", "BidAsk", "v1"),
    ]
    assert ("TSE001", "Tick", "v1") in fake_api.quote.subscriptions

    bidask = types.SimpleNamespace(code="2330")
    fake_api.quote.bidask_callback(None, bidask)

    assert applied_bidasks == [bidask]


def test_sinopac_collector_login_and_subscribe_sync_skips_taiex_when_indices_contracts_are_unavailable(
    monkeypatch,
    caplog,
) -> None:
    import logging
    import sinopac_bridge as bridge

    class _FakeLoop:
        def is_closed(self) -> bool:
            return False

        def call_soon_threadsafe(self, callback, *args) -> None:
            callback(*args)

    class _FakeQuote:
        def __init__(self) -> None:
            self.subscriptions: list[tuple[str, object, object]] = []
            self.tick_callback = None
            self.bidask_callback = None

        def subscribe(self, contract, quote_type, version) -> None:
            self.subscriptions.append((contract.code, quote_type, version))

        def set_on_tick_stk_v1_callback(self, callback) -> None:
            self.tick_callback = callback

        def set_on_bidask_stk_v1_callback(self, callback) -> None:
            self.bidask_callback = callback

    class _FakeApi:
        def __init__(self) -> None:
            self.quote = _FakeQuote()
            self.Contracts = types.SimpleNamespace(
                Stocks=types.SimpleNamespace(
                    TSE={"2330": types.SimpleNamespace(code="2330")},
                    OTC={},
                    OES={},
                ),
            )
            self.logged_in = None

        def login(self, *, api_key, secret_key) -> None:
            self.logged_in = (api_key, secret_key)

        def logout(self) -> None:
            return None

        def snapshots(self, contracts) -> list[object]:
            return []

    fake_api = _FakeApi()
    fake_sj = types.SimpleNamespace(Shioaji=lambda simulation=False: fake_api)
    fake_constant = types.SimpleNamespace(
        QuoteType=types.SimpleNamespace(Tick="Tick", BidAsk="BidAsk"),
        QuoteVersion=types.SimpleNamespace(v1="v1"),
    )

    monkeypatch.setitem(sys.modules, "shioaji", fake_sj)
    monkeypatch.setitem(sys.modules, "shioaji.constant", fake_constant)
    monkeypatch.setattr(bridge, "_load_twse_seed_quotes", lambda symbols: {})

    collector = SinopacCollector(
        ["2330"],
        api_key="demo",
        secret_key="demo",
        bootstrap_bar_limit=0,
    )
    collector._loop = _FakeLoop()

    with caplog.at_level(logging.WARNING):
        collector._login_and_subscribe_sync()

    assert fake_api.logged_in == ("demo", "demo")
    assert fake_api.quote.subscriptions == [
        ("2330", "Tick", "v1"),
        ("2330", "BidAsk", "v1"),
    ]
    assert "TAIEX index subscription failed" not in caplog.text
    assert "hook unavailable" not in caplog.text


def test_sinopac_collector_unsubscribes_quote_detail() -> None:
    collector = SinopacCollector(
        ["2317"],
        api_key="demo",
        secret_key="demo",
    )
    collector._loop = asyncio.new_event_loop()
    websocket = _FakeWebSocket(
        incoming=[
            '{"type":"subscribe_quote_detail","symbol":"2317"}',
            '{"type":"unsubscribe_quote_detail","symbol":"2317"}',
        ]
    )

    try:
        asyncio.run(collector._ws_handler(websocket))
    finally:
        collector._loop.close()

    assert getattr(collector, "_quote_detail_subscriptions", {}).get(websocket) is None


def test_bind_index_tick_handler_skips_when_shioaji_api_lacks_index_hook() -> None:
    class _FakeApi:
        pass

    called: list[object] = []

    def _callback(exchange, tick) -> None:
        called.append((exchange, tick))

    assert _bind_index_tick_handler(_FakeApi(), _callback) is False
    assert called == []

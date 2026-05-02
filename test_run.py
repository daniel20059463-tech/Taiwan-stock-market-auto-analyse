from __future__ import annotations

import asyncio
import importlib
import types
from dataclasses import is_dataclass
from pathlib import Path

import pytest

from institutional_flow_provider import InstitutionalFlowRow
from market_universe import DEFAULT_TW_SYMBOLS

REPO_ROOT = Path(__file__).resolve().parent


class _FakeCollector:
    async def start(self) -> None:  # pragma: no cover - helper only
        return None

    async def stop_accepting(self) -> None:  # pragma: no cover - helper only
        return None

    async def stop(self) -> None:  # pragma: no cover - helper only
        return None


class _FakeWebSocket:
    def __init__(self, incoming: list[object] | None = None) -> None:
        self.sent: list[object] = []
        self._incoming = list(incoming or [])

    async def send(self, payload: object) -> None:
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


def test_build_runtime_components_continues_without_auto_trader(monkeypatch) -> None:
    run = importlib.import_module("run")
    captured: dict[str, object] = {}

    class _FakeAnalyzerService:
        def __init__(self, **kwargs: object) -> None:
            self._workers: list[object] = []

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    fake_analyzer = types.SimpleNamespace(AnalyzerService=_FakeAnalyzerService)

    def fake_collector_from_env(symbols: list[str], auto_trader=None):
        captured["symbols"] = symbols
        captured["auto_trader"] = auto_trader
        return _FakeCollector()

    fake_bridge = types.SimpleNamespace(collector_from_env=fake_collector_from_env)

    def fake_import_module(name: str):
        if name == "auto_trader":
            raise ModuleNotFoundError("auto_trader is intentionally unavailable")
        if name == "analyzer":
            return fake_analyzer
        if name == "sinopac_bridge":
            return fake_bridge
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(run.importlib, "import_module", fake_import_module)
    monkeypatch.setenv("ENABLE_AUTO_TRADER", "true")
    monkeypatch.setenv("SINOPAC_AUTO_SCAN", "false")
    monkeypatch.setattr(
        run,
        "resolve_runtime_symbols",
        lambda *, raw_symbols="", use_mock, auto_universe_loader=None: ["2330", "2317"],
    )

    runtime = run.build_runtime_components(
        raw_symbols="2330,2317",
        ws_host="127.0.0.1",
        ws_port=8765,
        use_mock=False,
    )

    assert is_dataclass(runtime)
    assert isinstance(runtime.collector, _FakeCollector)
    assert runtime.auto_trader is None
    assert runtime.symbols == ["2330", "2317"]
    assert runtime.state_store is not None
    assert runtime.notifier is not None
    assert runtime.analyzer is not None
    assert captured["symbols"] == ["2330", "2317"]
    assert captured["auto_trader"] is None


def test_build_runtime_components_honors_explicit_raw_symbols_in_live_mode(monkeypatch) -> None:
    run = importlib.import_module("run")
    captured: dict[str, object] = {}

    class _FakeAnalyzerService:
        def __init__(self, **kwargs: object) -> None:
            self._workers: list[object] = []

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    fake_analyzer = types.SimpleNamespace(AnalyzerService=_FakeAnalyzerService)

    def fake_collector_from_env(symbols: list[str], auto_trader=None):
        captured["symbols"] = symbols
        return _FakeCollector()

    fake_bridge = types.SimpleNamespace(collector_from_env=fake_collector_from_env)

    def fake_import_module(name: str):
        if name == "auto_trader":
            raise ModuleNotFoundError("auto_trader is intentionally unavailable")
        if name == "analyzer":
            return fake_analyzer
        if name == "sinopac_bridge":
            return fake_bridge
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(run.importlib, "import_module", fake_import_module)
    monkeypatch.setenv("ENABLE_AUTO_TRADER", "true")
    monkeypatch.setenv("SINOPAC_AUTO_SCAN", "false")
    monkeypatch.setattr(
        run,
        "_load_dynamic_shioaji_universe_from_env",
        lambda: (_ for _ in ()).throw(AssertionError("dynamic loader should not be used for explicit raw symbols")),
    )

    runtime = run.build_runtime_components(
        raw_symbols="2330,2317",
        ws_host="127.0.0.1",
        ws_port=8765,
        use_mock=False,
    )

    assert is_dataclass(runtime)
    assert runtime.symbols == ["2330", "2317"]
    assert captured["symbols"] == ["2330", "2317"]


def test_load_auto_trader_defaults_to_retail_flow_swing(monkeypatch) -> None:
    run = importlib.import_module("run")
    captured: dict[str, object] = {}

    def fake_load_auto_trader(enabled: bool, *, strategy_mode: str, build_strategy_dependencies_fn, prime_institutional_flow_cache_fn):
        captured["enabled"] = enabled
        captured["strategy_mode"] = strategy_mode
        captured["build_strategy_dependencies_fn"] = build_strategy_dependencies_fn
        captured["prime_institutional_flow_cache_fn"] = prime_institutional_flow_cache_fn
        return None

    monkeypatch.setattr(run, "_runtime_bootstrap", types.SimpleNamespace(load_auto_trader=fake_load_auto_trader))

    assert run._load_auto_trader(True) is None
    assert captured["enabled"] is True
    assert captured["strategy_mode"] == "retail_flow_swing"


def test_resolve_runtime_symbols_falls_back_to_default_symbols_when_dynamic_load_fails() -> None:
    run = importlib.import_module("run")

    symbols = run.resolve_runtime_symbols(
        use_mock=False,
        auto_universe_loader=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert symbols == DEFAULT_TW_SYMBOLS


def test_resolve_runtime_symbols_falls_back_to_default_symbols_when_dynamic_universe_is_empty() -> None:
    run = importlib.import_module("run")

    symbols = run.resolve_runtime_symbols(
        use_mock=False,
        auto_universe_loader=lambda: {},
    )

    assert symbols == DEFAULT_TW_SYMBOLS


def test_mock_collector_sends_initial_portfolio_snapshot_on_connect() -> None:
    run = importlib.import_module("run")
    class _FakeAutoTrader:
        def get_portfolio_snapshot(self) -> dict[str, object]:
            return {
                "type": "PAPER_PORTFOLIO",
                "positions": [],
                "recentTrades": [
                    {
                        "symbol": "2330",
                        "action": "BUY",
                        "price": 950.0,
                        "shares": 1000,
                        "reason": "SIGNAL",
                        "netPnl": 0.0,
                        "grossPnl": 0.0,
                        "ts": 1_700_000_000_000,
                    }
                ],
                "realizedPnl": 0.0,
                "unrealizedPnl": 0.0,
                "totalPnl": 0.0,
                "tradeCount": 0,
                "winRate": 0.0,
                "marketChangePct": 0.0,
                "riskStatus": {},
                "sessionId": "test-session",
            }

    collector = run.MockCollector(["2330"], auto_trader=_FakeAutoTrader())
    websocket = _FakeWebSocket()

    asyncio.run(collector._ws_handler(websocket))

    assert websocket.sent, "expected an initial websocket payload"
    assert '"type":"PAPER_PORTFOLIO"' in str(websocket.sent[0])


def test_mock_collector_executes_manual_paper_trade_over_websocket() -> None:
    run = importlib.import_module("run")

    class _FakeAutoTrader:
        def get_portfolio_snapshot(self) -> dict[str, object]:
            return {
                "type": "PAPER_PORTFOLIO",
                "positions": [],
                "recentTrades": [],
                "realizedPnl": 0.0,
                "unrealizedPnl": 0.0,
                "totalPnl": 0.0,
                "tradeCount": 0,
                "winRate": 0.0,
                "marketChangePct": 0.0,
                "riskStatus": {},
                "sessionId": "init-session",
            }

        async def execute_manual_trade(
            self,
            *,
            symbol: str,
            action: str,
            shares: int,
            ts_ms: int | None = None,
        ) -> dict[str, object]:
            assert symbol == "2330"
            assert action == "BUY"
            assert shares == 1000
            return {
                "type": "PAPER_PORTFOLIO",
                "positions": [{"symbol": "2330", "side": "long"}],
                "recentTrades": [],
                "realizedPnl": 0.0,
                "unrealizedPnl": 0.0,
                "totalPnl": 0.0,
                "tradeCount": 0,
                "winRate": 0.0,
                "marketChangePct": 0.0,
                "riskStatus": {},
                "sessionId": "test-session",
            }

    collector = run.MockCollector(["2330"], auto_trader=_FakeAutoTrader())
    websocket = _FakeWebSocket(
        incoming=['{"type":"paper_trade","symbol":"2330","action":"BUY","shares":1000}']
    )

    asyncio.run(collector._ws_handler(websocket))

    assert any('"type":"PAPER_TRADE_RESULT"' in str(payload) for payload in websocket.sent)
    assert any('"type":"PAPER_PORTFOLIO"' in str(payload) for payload in websocket.sent[1:])


def test_mock_collector_subscribes_quote_detail_and_sends_snapshots() -> None:
    run = importlib.import_module("run")

    collector = run.MockCollector(["2330"])
    websocket = _FakeWebSocket(
        incoming=['{"type":"subscribe_quote_detail","symbol":"2330"}']
    )

    asyncio.run(collector._ws_handler(websocket))

    assert any('"type":"ORDER_BOOK_SNAPSHOT"' in str(payload) for payload in websocket.sent)
    assert any('"type":"TRADE_TAPE_SNAPSHOT"' in str(payload) for payload in websocket.sent)


def test_mock_collector_unsubscribes_quote_detail() -> None:
    run = importlib.import_module("run")

    collector = run.MockCollector(["2330"])
    websocket = _FakeWebSocket(
        incoming=[
            '{"type":"subscribe_quote_detail","symbol":"2330"}',
            '{"type":"unsubscribe_quote_detail","symbol":"2330"}',
        ]
    )

    asyncio.run(collector._ws_handler(websocket))

    assert getattr(collector, "_quote_detail_subscriptions", {}).get(websocket) is None


def test_runtime_builds_retail_flow_swing_dependencies_when_enabled(monkeypatch) -> None:
    run = importlib.import_module("run")
    captured: dict[str, object] = {}

    class _FakeAnalyzerService:
        def __init__(self, **kwargs: object) -> None:
            self._workers: list[object] = []

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeProvider:
        pass

    class _FakeCache:
        def load(self, path: str) -> None:
            pass

        def prune(self, keep_days: int = 30) -> None:
            pass

        def save(self, path: str) -> None:
            pass

    class _FakeStrategy:
        pass

    fake_analyzer = types.SimpleNamespace(AnalyzerService=_FakeAnalyzerService)

    def fake_trader_from_env(**kwargs):
        captured.update(kwargs)
        return "AUTO_TRADER"

    def fake_collector_from_env(symbols: list[str], auto_trader=None):
        captured["symbols"] = symbols
        captured["auto_trader"] = auto_trader
        return _FakeCollector()

    fake_auto_trader = types.SimpleNamespace(trader_from_env=fake_trader_from_env)
    fake_bridge = types.SimpleNamespace(collector_from_env=fake_collector_from_env)
    fake_provider_module = types.SimpleNamespace(InstitutionalFlowProvider=_FakeProvider)
    fake_cache_module = types.SimpleNamespace(InstitutionalFlowCache=_FakeCache)
    fake_strategy_module = types.SimpleNamespace(RetailFlowSwingStrategy=_FakeStrategy)

    def fake_import_module(name: str):
        if name == "auto_trader":
            return fake_auto_trader
        if name == "analyzer":
            return fake_analyzer
        if name == "sinopac_bridge":
            return fake_bridge
        if name == "institutional_flow_provider":
            return fake_provider_module
        if name == "institutional_flow_cache":
            return fake_cache_module
        if name == "retail_flow_strategy":
            return fake_strategy_module
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(run.importlib, "import_module", fake_import_module)
    monkeypatch.setenv("ENABLE_AUTO_TRADER", "true")
    monkeypatch.setenv("SINOPAC_AUTO_SCAN", "false")
    monkeypatch.setenv("STRATEGY_MODE", "retail_flow_swing")
    monkeypatch.setattr(
        run,
        "resolve_runtime_symbols",
        lambda *, raw_symbols="", use_mock, auto_universe_loader=None: ["2330", "2317"],
    )

    runtime = run.build_runtime_components(
        raw_symbols="2330,2317",
        ws_host="127.0.0.1",
        ws_port=8765,
        use_mock=False,
    )

    assert runtime.auto_trader == "AUTO_TRADER"
    assert isinstance(captured["institutional_flow_provider"], _FakeProvider)
    assert isinstance(captured["institutional_flow_cache"], _FakeCache)
    assert isinstance(captured["retail_flow_strategy"], _FakeStrategy)
    assert captured["strategy_mode"] == "retail_flow_swing"


def test_runtime_primes_institutional_flow_cache_when_swing_mode_enabled(monkeypatch) -> None:
    run = importlib.import_module("run")
    captured: dict[str, object] = {}

    class _FakeAnalyzerService:
        def __init__(self, **kwargs: object) -> None:
            self._workers: list[object] = []

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeProvider:
        def fetch_rank_rows(self):
            return [
                InstitutionalFlowRow(
                    symbol="2330",
                    name="台積電",
                    foreign_net_buy=1000,
                    investment_trust_net_buy=500,
                    major_net_buy=800,
                )
            ]

    class _FakeCache:
        def __init__(self) -> None:
            self.stored: list[tuple[str, list[InstitutionalFlowRow]]] = []

        def store(self, *, trade_date: str, rows: list[InstitutionalFlowRow]) -> None:
            self.stored.append((trade_date, rows))

        def load(self, path: str) -> None:
            pass

        def prune(self, keep_days: int = 30) -> None:
            pass

        def save(self, path: str) -> None:
            pass

    class _FakeStrategy:
        pass

    fake_analyzer = types.SimpleNamespace(AnalyzerService=_FakeAnalyzerService)

    def fake_trader_from_env(**kwargs):
        captured.update(kwargs)
        return "AUTO_TRADER"

    def fake_collector_from_env(symbols: list[str], auto_trader=None):
        return _FakeCollector()

    fake_auto_trader = types.SimpleNamespace(trader_from_env=fake_trader_from_env)
    fake_bridge = types.SimpleNamespace(collector_from_env=fake_collector_from_env)
    fake_provider_module = types.SimpleNamespace(InstitutionalFlowProvider=_FakeProvider)
    fake_cache_module = types.SimpleNamespace(InstitutionalFlowCache=_FakeCache)
    fake_strategy_module = types.SimpleNamespace(RetailFlowSwingStrategy=_FakeStrategy)

    def fake_import_module(name: str):
        if name == "auto_trader":
            return fake_auto_trader
        if name == "analyzer":
            return fake_analyzer
        if name == "sinopac_bridge":
            return fake_bridge
        if name == "institutional_flow_provider":
            return fake_provider_module
        if name == "institutional_flow_cache":
            return fake_cache_module
        if name == "retail_flow_strategy":
            return fake_strategy_module
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(run.importlib, "import_module", fake_import_module)
    monkeypatch.setenv("ENABLE_AUTO_TRADER", "true")
    monkeypatch.setenv("SINOPAC_AUTO_SCAN", "false")
    monkeypatch.setenv("STRATEGY_MODE", "retail_flow_swing")
    monkeypatch.setattr(
        run,
        "resolve_runtime_symbols",
        lambda *, raw_symbols="", use_mock, auto_universe_loader=None: ["2330"],
    )
    monkeypatch.setattr(run, "_today_trade_date", lambda: "2026-04-17")

    run.build_runtime_components(
        raw_symbols="2330",
        ws_host="127.0.0.1",
        ws_port=8765,
        use_mock=False,
    )

    cache = captured["institutional_flow_cache"]
    assert cache.stored
    # retail_flow_swing uses T+1 data: cache is primed with the previous trading day
    assert cache.stored[0][0] == "2026-04-16"
    assert cache.stored[0][1][0].symbol == "2330"


def test_main_skips_live_engine_on_non_trading_day(monkeypatch) -> None:
    run = importlib.import_module("run")
    called: dict[str, bool] = {"build": False}

    def fake_build_runtime_components(**kwargs):
        called["build"] = True
        raise AssertionError("build_runtime_components should not run on non-trading days")

    monkeypatch.setattr(run, "build_runtime_components", fake_build_runtime_components)
    monkeypatch.setenv("SINOPAC_MOCK", "false")
    monkeypatch.setattr(
        run,
        "is_known_open_trading_datetime",
        lambda value=None: False,
    )

    asyncio.run(run.main())

    assert called["build"] is False


def test_strategy_runtime_builds_retail_flow_swing_dependencies(monkeypatch) -> None:
    strategy_runtime = importlib.import_module("strategy_runtime")

    class _FakeProvider:
        pass

    class _FakeCache:
        pass

    class _FakeStrategy:
        pass

    fake_provider_module = types.SimpleNamespace(InstitutionalFlowProvider=_FakeProvider)
    fake_cache_module = types.SimpleNamespace(InstitutionalFlowCache=_FakeCache)
    fake_strategy_module = types.SimpleNamespace(RetailFlowSwingStrategy=_FakeStrategy)

    def fake_import_module(name: str):
        if name == "institutional_flow_provider":
            return fake_provider_module
        if name == "institutional_flow_cache":
            return fake_cache_module
        if name == "retail_flow_strategy":
            return fake_strategy_module
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(strategy_runtime.importlib, "import_module", fake_import_module)

    dependencies = strategy_runtime.build_strategy_dependencies("retail_flow_swing")

    assert isinstance(dependencies["institutional_flow_provider"], _FakeProvider)
    assert isinstance(dependencies["institutional_flow_cache"], _FakeCache)
    assert isinstance(dependencies["retail_flow_strategy"], _FakeStrategy)
    assert dependencies["strategy_mode"] == "retail_flow_swing"


def test_strategy_runtime_rejects_unsupported_strategy_mode() -> None:
    strategy_runtime = importlib.import_module("strategy_runtime")

    with pytest.raises(ValueError, match="Unsupported STRATEGY_MODE"):
        strategy_runtime.build_strategy_dependencies("intraday")


def test_strategy_runtime_primes_institutional_flow_cache(monkeypatch, tmp_path) -> None:
    strategy_runtime = importlib.import_module("strategy_runtime")

    captured: dict[str, object] = {}

    class _FakeProvider:
        def fetch_rank_rows(self):
            return [
                InstitutionalFlowRow(
                    symbol="2330",
                    name="台積電",
                    foreign_net_buy=1000,
                    investment_trust_net_buy=500,
                    major_net_buy=800,
                )
            ]

    class _FakeCache:
        def __init__(self) -> None:
            self.loaded: list[str] = []
            self.saved: list[str] = []
            self.stored: list[tuple[str, list[InstitutionalFlowRow]]] = []
            self.pruned = 0

        def load(self, path: str) -> None:
            self.loaded.append(path)

        def store(self, *, trade_date: str, rows: list[InstitutionalFlowRow]) -> None:
            self.stored.append((trade_date, rows))

        def prune(self, keep_days: int = 30) -> None:
            self.pruned += 1

        def save(self, path: str) -> None:
            self.saved.append(path)

    cache_path = tmp_path / "flow_cache.json"
    monkeypatch.setattr(strategy_runtime, "FLOW_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(strategy_runtime, "_today_trade_date", lambda: "2026-04-19")

    cache = _FakeCache()
    dependencies = {
        "institutional_flow_provider": _FakeProvider(),
        "institutional_flow_cache": cache,
        "strategy_mode": "retail_flow_swing",
    }

    strategy_runtime.prime_institutional_flow_cache(dependencies)

    assert cache.loaded == [str(cache_path)]
    assert cache.saved == [str(cache_path)]
    assert cache.pruned == 1
    assert cache.stored
    # retail_flow_swing uses T+1 data: cache is primed with the previous open trading day
    assert cache.stored[0][0] == "2026-04-17"
    assert cache.stored[0][1][0].symbol == "2330"


def test_runtime_bootstrap_build_runtime_components_continues_without_auto_trader(monkeypatch) -> None:
    runtime_bootstrap = importlib.import_module("runtime_bootstrap")
    captured: dict[str, object] = {}

    class _FakeAnalyzerService:
        def __init__(self, **kwargs: object) -> None:
            self._workers: list[object] = []

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

    fake_analyzer = types.SimpleNamespace(AnalyzerService=_FakeAnalyzerService)

    def fake_collector_from_env(symbols: list[str], auto_trader=None):
        captured["symbols"] = symbols
        captured["auto_trader"] = auto_trader
        return _FakeCollector()

    fake_bridge = types.SimpleNamespace(collector_from_env=fake_collector_from_env)

    def fake_import_module(name: str):
        if name == "analyzer":
            return fake_analyzer
        if name == "sinopac_bridge":
            return fake_bridge
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(runtime_bootstrap.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(
        runtime_bootstrap,
        "resolve_runtime_symbols",
        lambda *, raw_symbols="", use_mock, auto_universe_loader=None: ["2330", "2317"],
    )
    monkeypatch.setattr(runtime_bootstrap, "load_auto_trader", lambda enabled, strategy_mode="intraday": None)
    monkeypatch.setattr(runtime_bootstrap, "inject_daily_price_cache", lambda auto_trader, symbols: None)
    monkeypatch.setenv("SINOPAC_AUTO_SCAN", "false")

    runtime = runtime_bootstrap.build_runtime_components(
        raw_symbols="2330,2317",
        ws_host="127.0.0.1",
        ws_port=8765,
        use_mock=False,
    )

    assert is_dataclass(runtime)
    assert isinstance(runtime.collector, _FakeCollector)
    assert runtime.auto_trader is None
    assert runtime.symbols == ["2330", "2317"]
    assert captured["symbols"] == ["2330", "2317"]
    assert captured["auto_trader"] is None

from __future__ import annotations

import asyncio
import importlib
import types
from dataclasses import is_dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


class _FakeCollector:
    async def start(self) -> None:  # pragma: no cover - helper only
        return None

    async def stop_accepting(self) -> None:  # pragma: no cover - helper only
        return None

    async def stop(self) -> None:  # pragma: no cover - helper only
        return None


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, payload: object) -> None:
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


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


def test_frontend_history_contract_is_backend_only() -> None:
    worker_source = (REPO_ROOT / "src" / "workers" / "data.worker.ts").read_text(encoding="utf-8")
    type_source = (REPO_ROOT / "src" / "types" / "market.ts").read_text(encoding="utf-8")

    assert "twse.com.tw" not in worker_source
    assert "fetchTwseMonth" not in worker_source
    assert 'source: "sinopac" | "fallback";' in type_source


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


def test_desktop_backend_enters_project_root_loads_root_env_and_delegates(monkeypatch, tmp_path) -> None:
    desktop_backend = importlib.import_module("desktop_backend")
    calls: list[tuple[str, object]] = []

    fake_run_module = types.SimpleNamespace()

    async def fake_run_main() -> None:
        calls.append(("run.main", None))

    fake_run_module.main = fake_run_main

    monkeypatch.setattr(desktop_backend, "__file__", str(tmp_path / "desktop_backend.py"))
    monkeypatch.setattr(desktop_backend.os, "chdir", lambda path: calls.append(("chdir", path)))
    monkeypatch.setattr(
        desktop_backend,
        "load_dotenv",
        lambda path=None, *args, **kwargs: calls.append(("load_dotenv", path)),
    )
    monkeypatch.setattr(
        desktop_backend.importlib,
        "import_module",
        lambda name: fake_run_module if name == "run" else importlib.import_module(name),
    )

    result = desktop_backend.main()

    assert result == 0
    assert calls[0] == ("chdir", tmp_path)
    assert calls[1] == ("load_dotenv", tmp_path / ".env")
    assert calls[2] == ("run.main", None)


def test_desktop_backend_uses_project_root_env_when_frozen(monkeypatch, tmp_path) -> None:
    desktop_backend = importlib.import_module("desktop_backend")
    calls: list[tuple[str, object]] = []

    fake_run_module = types.SimpleNamespace()

    async def fake_run_main() -> None:
        calls.append(("run.main", None))

    fake_run_module.main = fake_run_main

    project_root = tmp_path / "repo"
    backend_dir = project_root / "src-tauri" / "backend"
    backend_dir.mkdir(parents=True)
    (project_root / "run.py").write_text("async def main():\n    return None\n", encoding="utf-8")
    (project_root / ".env").write_text("FOO=bar\n", encoding="utf-8")

    monkeypatch.setattr(desktop_backend.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        desktop_backend.sys,
        "executable",
        str(backend_dir / "desktop_backend.exe"),
    )
    monkeypatch.setattr(desktop_backend.os, "chdir", lambda path: calls.append(("chdir", path)))
    monkeypatch.setattr(
        desktop_backend,
        "load_dotenv",
        lambda path=None, *args, **kwargs: calls.append(("load_dotenv", path)),
    )
    monkeypatch.setattr(
        desktop_backend.importlib,
        "import_module",
        lambda name: fake_run_module if name == "run" else importlib.import_module(name),
    )

    result = desktop_backend.main()

    assert result == 0
    assert calls[0] == ("chdir", project_root)
    assert calls[1] == ("load_dotenv", project_root / ".env")
    assert calls[2] == ("run.main", None)

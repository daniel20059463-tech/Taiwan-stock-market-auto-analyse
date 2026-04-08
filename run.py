from __future__ import annotations

import asyncio
import datetime
import importlib
import inspect
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from main import SharedMemoryIPC, create_supervisor_from_runtime
from market_universe import DEFAULT_TW_SYMBOLS

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")

_MOCK_BASE: dict[str, float] = {
    "2330": 920.0,
    "2317": 105.0,
    "2454": 1280.0,
    "2382": 245.0,
    "2412": 128.0,
}


@dataclass(slots=True)
class RuntimeComponents:
    state_store: Any
    analyzer: Any
    collector: Any
    notifier: Any
    ipc_manager: Any | None = None
    symbols: list[str] = field(default_factory=list)
    auto_trader: Any | None = None


class ReadyStateStore:
    def __init__(self) -> None:
        self._ready = False

    async def start(self) -> None:
        self._ready = True

    async def wait_ready(self, timeout: float | None = None) -> bool:
        return self._ready

    async def stop(self) -> None:
        self._ready = False


class ReadyNotifier:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class AnalyzerServiceAdapter:
    def __init__(self, service: Any) -> None:
        self._service = service
        self._stopped = False

    def start(self, ipc: Any) -> None:
        self._service.start()

    def is_alive(self) -> bool:
        workers = getattr(self._service, "_workers", [])
        return any(worker.is_alive() for worker in workers)

    @property
    def exitcode(self) -> int | None:
        workers = getattr(self._service, "_workers", [])
        exitcodes = [worker.exitcode for worker in workers if worker.exitcode is not None]
        if not exitcodes:
            return None if self.is_alive() else 0
        for exitcode in exitcodes:
            if exitcode not in (None, 0):
                return exitcode
        return 0

    def send_stop(self) -> None:
        self._service.stop()
        self._stopped = True

    def join(self, timeout: float) -> None:
        if self._stopped:
            return
        workers = getattr(self._service, "_workers", [])
        for worker in workers:
            worker.join(timeout)

    def terminate(self) -> None:
        workers = getattr(self._service, "_workers", [])
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=1)
        if not self._stopped:
            self._service.stop()
            self._stopped = True


class CollectorRuntimeAdapter:
    def __init__(self, collector: Any, auto_trader: Any | None) -> None:
        self._collector = collector
        self._auto_trader = auto_trader

    async def start(self) -> None:
        await self._collector.start()

    async def stop_accepting(self) -> None:
        await self._collector.stop_accepting()

    async def stop(self) -> None:
        await self._collector.stop()
        if self._auto_trader is None:
            return

        close = getattr(self._auto_trader, "close", None)
        if close is None:
            return

        result = close()
        if inspect.isawaitable(result):
            await result

    def pending_count(self) -> int:
        return int(self._collector.pending_count())


class MockCollector:
    def __init__(
        self,
        symbols: list[str],
        ws_host: str = "127.0.0.1",
        ws_port: int = 8765,
        auto_trader=None,
    ) -> None:
        self._symbols = symbols
        self._ws_host = ws_host
        self._ws_port = ws_port
        self._auto_trader = auto_trader
        self._clients: set = set()
        self._accepting = True
        self._server = None
        self._tasks: list[asyncio.Task] = []
        self._prices = {symbol: _MOCK_BASE.get(symbol, 100.0) for symbol in symbols}
        self._previous_close = dict(self._prices)
        self._session_high = dict(self._prices)
        self._session_low = dict(self._prices)
        self._total_volume = {symbol: 0 for symbol in symbols}
        # ── 模擬加權指數 ──────────────────────────────────────────────────────
        self._market_price: float = 20000.0      # 模擬大盤起始點位
        self._market_prev_close: float = 20000.0 # 模擬大盤前收

    async def start(self) -> None:
        import websockets

        self._server = await websockets.serve(self._ws_handler, self._ws_host, self._ws_port)
        for symbol in self._symbols:
            self._tasks.append(asyncio.create_task(self._tick_loop(symbol), name=f"mock-tick-{symbol}"))
        self._tasks.append(asyncio.create_task(self._market_index_loop(), name="mock-market-index"))
        logger.info("MockCollector ready on ws://%s:%d symbols=%d", self._ws_host, self._ws_port, len(self._symbols))

    async def stop_accepting(self) -> None:
        self._accepting = False

    async def stop(self) -> None:
        self._accepting = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def pending_count(self) -> int:
        return 0

    async def _ws_handler(self, websocket, path: str = "/") -> None:
        self._clients.add(websocket)
        logger.info("Dashboard connected (%d total)", len(self._clients))
        try:
            if self._auto_trader is not None:
                try:
                    snapshot = self._auto_trader.get_portfolio_snapshot()
                    await websocket.send(json.dumps(snapshot, separators=(",", ":")))
                except Exception as exc:
                    logger.warning("Initial portfolio snapshot failed: %s", exc)
            async for raw in websocket:
                if not isinstance(raw, str):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if message.get("type") != "session_bars":
                    if message.get("type") != "history_bars":
                        continue
                symbol = str(message.get("symbol", "")).strip()
                if not symbol:
                    continue
                if message.get("type") == "session_bars":
                    payload = {
                        "type": "SESSION_BARS",
                        "symbol": symbol,
                        "candles": self._build_session_candles(symbol, int(message.get("limit", 240))),
                        "source": "fallback",
                    }
                else:
                    payload = {
                        "type": "HISTORY_BARS",
                        "symbol": symbol,
                        "candles": self._build_history_candles(symbol, int(message.get("months", 6))),
                        "source": "fallback",
                    }
                await websocket.send(json.dumps(payload, separators=(",", ":")))
        finally:
            self._clients.discard(websocket)
            logger.info("Dashboard disconnected (%d total)", len(self._clients))

    def _build_session_candles(self, symbol: str, limit: int) -> list[dict[str, float | int]]:
        close = self._prices.get(symbol, 100.0)
        previous_close = self._previous_close.get(symbol, close)
        high = self._session_high.get(symbol, max(close, previous_close))
        low = self._session_low.get(symbol, min(close, previous_close))
        total_volume = self._total_volume.get(symbol, 0)
        count = max(24, min(limit, 180))
        start = int(time.time() // 60) * 60_000 - (count - 1) * 60_000
        candles: list[dict[str, float | int]] = []
        for index in range(count):
            progress = index / max(1, count - 1)
            anchor = previous_close + (close - previous_close) * progress
            wave = (high - low) * 0.15 * ((index % 7) - 3) / 3
            price = round(max(low, min(high, anchor + wave)), 2)
            open_ = round(previous_close + (price - previous_close) * 0.85, 2)
            candle_high = round(max(open_, price, high if index == count - 1 else price), 2)
            candle_low = round(min(open_, price, low if index == 0 else price), 2)
            volume = max(1, total_volume // count if total_volume else 0)
            candles.append(
                {
                    "time": start + index * 60_000,
                    "open": open_,
                    "high": candle_high,
                    "low": candle_low,
                    "close": price,
                    "volume": volume,
                }
            )
        return candles

    def _build_history_candles(self, symbol: str, months: int) -> list[dict[str, float | int]]:
        close = self._prices.get(symbol, 100.0)
        previous_close = self._previous_close.get(symbol, close)
        high = self._session_high.get(symbol, max(close, previous_close))
        low = self._session_low.get(symbol, min(close, previous_close))
        total = max(20, min(months * 22, 180))
        start = int(time.time() // 86400) * 86_400_000 - (total - 1) * 86_400_000
        candles: list[dict[str, float | int]] = []
        for index in range(total):
            progress = index / max(1, total - 1)
            drift = previous_close + (close - previous_close) * progress
            wave = (high - low + 1) * 0.25 * ((index % 9) - 4) / 4
            day_close = round(max(low, min(high, drift + wave)), 2)
            day_open = round(day_close * (1 + (((index % 5) - 2) * 0.003)), 2)
            day_high = round(max(day_open, day_close) * 1.01, 2)
            day_low = round(min(day_open, day_close) * 0.99, 2)
            candles.append(
                {
                    "time": start + index * 86_400_000,
                    "open": day_open,
                    "high": day_high,
                    "low": day_low,
                    "close": day_close,
                    "volume": max(1, self._total_volume.get(symbol, 0) // max(1, total)),
                }
            )
        return candles

    async def _market_index_loop(self) -> None:
        """
        模擬加權指數漲跌幅，每 10~20 秒更新一次。
        波動率比個股小（sigma=0.0004），但會逐漸隨機遊走。
        當大盤跌幅超過 1.5% 時，auto_trader 將暫停所有個股買入，
        可藉此驗證大盤過濾功能是否正常運作。
        """
        try:
            while self._accepting:
                await asyncio.sleep(random.uniform(10.0, 20.0))

                now_tw = datetime.datetime.now(tz=_TZ_TW)
                t = now_tw.hour * 60 + now_tw.minute
                if not (8 * 60 <= t <= 17 * 60):
                    continue

                self._market_price = max(
                    1.0,
                    self._market_price * (1 + random.gauss(0, 0.0004)),
                )
                self._market_price = round(self._market_price, 2)
                change_pct = (
                    (self._market_price - self._market_prev_close)
                    / self._market_prev_close * 100
                    if self._market_prev_close else 0.0
                )

                if self._auto_trader is not None:
                    self._auto_trader.update_market_index(change_pct)

                logger.debug(
                    "MockMarket: %.2f (%+.2f%%)", self._market_price, change_pct
                )
        except asyncio.CancelledError:
            return

    async def _tick_loop(self, symbol: str) -> None:
        price = self._prices[symbol]
        # mock ts 從現在開始，模擬交易時段內的 tick
        ts_ms = int(time.time() * 1000)
        try:
            while self._accepting:
                await asyncio.sleep(random.uniform(0.2, 1.0))

                # 在交易時段內才更新價格（mock 使用真實時鐘）
                now_tw = datetime.datetime.now(tz=_TZ_TW)
                t = now_tw.hour * 60 + now_tw.minute
                in_trading = 8 * 60 <= t <= 17 * 60

                if in_trading:
                    price = max(1.0, price * (1 + random.gauss(0, 0.0012)))
                    price = round(price, 2)
                    volume = random.randint(1, 200) * 1000
                else:
                    volume = 0

                ts_ms = int(time.time() * 1000)
                self._prices[symbol] = price
                self._session_high[symbol] = max(self._session_high[symbol], price)
                self._session_low[symbol] = min(self._session_low[symbol], price)
                self._total_volume[symbol] += volume

                prev_close = self._previous_close[symbol]
                change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0
                near_limit_up = change_pct >= 9.5
                near_limit_down = change_pct <= -9.5

                tick_data = {
                    "symbol": symbol,
                    "price": price,
                    "volume": volume,
                    "totalVolume": self._total_volume[symbol],
                    "previousClose": prev_close,
                    "open": prev_close,
                    "high": self._session_high[symbol],
                    "low": self._session_low[symbol],
                    "ts": ts_ms,
                    "changePct": round(change_pct, 2),
                    "inTradingHours": in_trading,
                    "nearLimitUp": near_limit_up,
                    "nearLimitDown": near_limit_down,
                }

                # 傳給 auto_trader
                if self._auto_trader is not None and in_trading:
                    try:
                        await self._auto_trader.on_tick(tick_data)
                    except Exception as exc:
                        logger.warning("MockCollector auto_trader.on_tick error: %s", exc)

                    # 廣播持倉快照
                    if self._clients:
                        try:
                            snapshot = self._auto_trader.get_portfolio_snapshot()
                            await self._broadcast(json.dumps(snapshot, separators=(",", ":")))
                        except Exception:
                            pass

                await self._broadcast(json.dumps(tick_data, separators=(",", ":")))
        except asyncio.CancelledError:
            return

    async def _broadcast(self, message: str) -> None:
        dead = []
        for client in list(self._clients):
            try:
                await client.send(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)


def _scan_symbols_sync() -> list[str]:
    try:
        import shioaji as sj
        from symbol_scanner import scan_strong_symbols

        top_n = int(os.getenv("SINOPAC_SCAN_TOP", "100"))
        api = sj.Shioaji(simulation=os.getenv("SINOPAC_SIMULATION", "false").lower() == "true")
        api.login(
            api_key=os.environ["SINOPAC_API_KEY"],
            secret_key=os.environ["SINOPAC_SECRET_KEY"],
        )
        result = scan_strong_symbols(api, top_n=top_n)
        api.logout()
        # scan_strong_symbols 回傳 ScanResult，取 top_symbols
        if hasattr(result, "top_symbols"):
            if result.top_sector:
                logger.info(
                    "Auto scan: 強勢族群=%s，入選 %d 檔",
                    result.top_sector,
                    len(result.top_symbols),
                )
            return result.top_symbols
        return list(result)   # 向下相容（萬一仍是 list）
    except Exception as exc:
        logger.error("Auto scan failed: %s", exc)
        return []


def _stable_unique(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
    return ordered


def _env_flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off"}


def _load_auto_trader(enabled: bool) -> Any | None:
    if not enabled:
        logger.info("Auto trader disabled by ENABLE_AUTO_TRADER")
        return None

    try:
        trader_module = importlib.import_module("auto_trader")
        trader_factory = getattr(trader_module, "trader_from_env")
        return trader_factory()
    except Exception as exc:
        logger.warning("Auto trader unavailable, continuing with collector only: %s", exc)
        return None


def _build_analyzer_service() -> Any:
    analyzer_module = importlib.import_module("analyzer")
    analyzer_service = analyzer_module.AnalyzerService(
        num_workers=int(os.getenv("ANALYZER_WORKERS", "1")),
        queue_size=int(os.getenv("ANALYZER_QUEUE_SIZE", "1024")),
    )
    return AnalyzerServiceAdapter(analyzer_service)


def resolve_symbols(raw_symbols: str) -> list[str]:
    default_symbols = ",".join(DEFAULT_TW_SYMBOLS)
    configured = raw_symbols.strip() or default_symbols
    return [symbol.strip() for symbol in configured.split(",") if symbol.strip()]


def build_runtime_components(
    *,
    raw_symbols: str,
    ws_host: str,
    ws_port: int,
    use_mock: bool,
) -> RuntimeComponents:
    symbols = resolve_symbols(raw_symbols)
    auto_trader = _load_auto_trader(_env_flag("ENABLE_AUTO_TRADER", "true"))
    state_store = ReadyStateStore()
    analyzer = _build_analyzer_service()
    notifier = ReadyNotifier()
    ipc_manager = SharedMemoryIPC(size=int(os.getenv("IPC_SHARED_MEMORY_SIZE", "1024")))

    if use_mock:
        logger.info("Mode: MOCK")
        collector = MockCollector(symbols, ws_host=ws_host, ws_port=ws_port, auto_trader=auto_trader)
        return RuntimeComponents(
            state_store=state_store,
            analyzer=analyzer,
            collector=collector,
            notifier=notifier,
            ipc_manager=ipc_manager,
            symbols=symbols,
            auto_trader=auto_trader,
        )

    auto_scan = os.getenv("SINOPAC_AUTO_SCAN", "false").lower() == "true"
    if auto_scan:
        logger.info("Mode: SINOPAC AUTO-SCAN top=%s", os.getenv("SINOPAC_SCAN_TOP", "100"))
        scanned = _scan_symbols_sync()
        if scanned:
            if raw_symbols.strip():
                symbols = _stable_unique([*symbols, *scanned])
                logger.info("Merged configured symbols with auto-scan symbols total=%d", len(symbols))
            else:
                logger.info(
                    "Auto-scan completed top_symbols=%d but frontend feed keeps the default universe total=%d",
                    len(scanned),
                    len(symbols),
                )
        else:
            logger.warning("Auto scan returned no symbols, falling back to default universe")
    else:
        logger.info("Mode: SINOPAC")

    bridge_module = importlib.import_module("sinopac_bridge")
    collector = bridge_module.collector_from_env(symbols, auto_trader=auto_trader)
    return RuntimeComponents(
        state_store=state_store,
        analyzer=analyzer,
        collector=collector,
        notifier=notifier,
        ipc_manager=ipc_manager,
        symbols=symbols,
        auto_trader=auto_trader,
    )


async def main() -> None:
    raw_symbols = os.getenv("VITE_SYMBOLS", "").strip()
    ws_host = os.getenv("WS_HOST", "127.0.0.1")
    ws_port = int(os.getenv("WS_PORT", "8765"))
    use_mock = os.getenv("SINOPAC_MOCK", "false").lower() == "true"

    runtime = build_runtime_components(
        raw_symbols=raw_symbols,
        ws_host=ws_host,
        ws_port=ws_port,
        use_mock=use_mock,
    )

    if runtime.auto_trader is not None:
        import datetime as _dt
        _today = _dt.datetime.now(tz=_TZ_TW).strftime("%Y%m%d")
        _restored = await runtime.auto_trader.restore_positions(_today)
        if _restored:
            logger.info("Restored %d open position(s) from today's DB snapshot", _restored)

    supervisor = create_supervisor_from_runtime(runtime)
    logger.info(
        "Collector running on ws://%s:%d symbols=%d. Press Ctrl+C to stop.",
        ws_host,
        ws_port,
        len(runtime.symbols),
    )
    await supervisor.run()


if __name__ == "__main__":
    asyncio.run(main())

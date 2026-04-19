from __future__ import annotations

import asyncio
from collections import deque
import datetime
import importlib
import inspect
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from main import SharedMemoryIPC
from market_universe import DEFAULT_TW_SYMBOLS
from strategy_runtime import build_strategy_dependencies, prime_institutional_flow_cache

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
logger = logging.getLogger("run")

_MOCK_BASE: dict[str, float] = {
    "2330": 920.0,
    "2317": 105.0,
    "2454": 1280.0,
    "2382": 245.0,
    "2412": 128.0,
}


def _today_trade_date() -> str:
    return datetime.datetime.now(tz=_TZ_TW).strftime("%Y-%m-%d")


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
        self._quote_detail_subscriptions: dict[object, str | None] = {}
        self._accepting = True
        self._server = None
        self._tasks: list[asyncio.Task] = []
        self._prices = {symbol: _MOCK_BASE.get(symbol, 100.0) for symbol in symbols}
        self._previous_close = dict(self._prices)
        self._session_high = dict(self._prices)
        self._session_low = dict(self._prices)
        self._total_volume = {symbol: 0 for symbol in symbols}
        self._trade_tape_buffers: dict[str, deque[dict[str, Any]]] = {
            symbol: deque(maxlen=20) for symbol in symbols
        }
        self._last_trade_prices = {symbol: self._prices[symbol] for symbol in symbols}
        self._market_price = 20000.0
        self._market_prev_close = 20000.0

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
        self._quote_detail_subscriptions[websocket] = None
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
                message_type = message.get("type")
                if message_type == "subscribe_quote_detail":
                    symbol = str(message.get("symbol", "")).strip()
                    if symbol in self._symbols:
                        self._quote_detail_subscriptions[websocket] = symbol
                        await self._send_quote_detail_snapshots(websocket, symbol)
                    continue
                if message_type == "unsubscribe_quote_detail":
                    self._quote_detail_subscriptions[websocket] = None
                    continue
                if message_type == "paper_trade":
                    if self._auto_trader is None:
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "PAPER_TRADE_RESULT",
                                    "status": "error",
                                    "error": "paper_trade_unavailable",
                                },
                                separators=(",", ":"),
                            )
                        )
                        continue
                    try:
                        snapshot = await self._auto_trader.execute_manual_trade(
                            symbol=str(message.get("symbol", "")).strip(),
                            action=str(message.get("action", "")).upper().strip(),
                            shares=int(message.get("shares", 1000)),
                            ts_ms=int(message.get("ts", time.time() * 1000)),
                        )
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "PAPER_TRADE_RESULT",
                                    "status": "ok",
                                    "symbol": str(message.get("symbol", "")).strip(),
                                    "action": str(message.get("action", "")).upper().strip(),
                                    "shares": int(message.get("shares", 1000)),
                                },
                                separators=(",", ":"),
                            )
                        )
                        await self._broadcast(json.dumps(snapshot, separators=(",", ":")))
                    except Exception as exc:
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "PAPER_TRADE_RESULT",
                                    "status": "error",
                                    "error": str(exc),
                                },
                                separators=(",", ":"),
                            )
                        )
                    continue
                if message_type not in {"session_bars", "history_bars"}:
                    continue
                symbol = str(message.get("symbol", "")).strip()
                if not symbol:
                    continue
                if message_type == "session_bars":
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
            self._quote_detail_subscriptions.pop(websocket, None)
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
        try:
            while self._accepting:
                await asyncio.sleep(random.uniform(10.0, 20.0))
                now_tw = datetime.datetime.now(tz=_TZ_TW)
                t = now_tw.hour * 60 + now_tw.minute
                if not (8 * 60 <= t <= 17 * 60):
                    continue

                self._market_price = max(1.0, self._market_price * (1 + random.gauss(0, 0.0004)))
                self._market_price = round(self._market_price, 2)
                change_pct = (
                    (self._market_price - self._market_prev_close) / self._market_prev_close * 100
                    if self._market_prev_close
                    else 0.0
                )

                if self._auto_trader is not None:
                    self._auto_trader.update_market_index(change_pct)

                logger.debug("MockMarket: %.2f (%+.2f%%)", self._market_price, change_pct)
        except asyncio.CancelledError:
            return

    async def _tick_loop(self, symbol: str) -> None:
        price = self._prices[symbol]
        try:
            while self._accepting:
                await asyncio.sleep(random.uniform(0.2, 1.0))
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
                self._record_trade_tape(symbol, price=price, volume=volume, ts_ms=ts_ms)

                prev_close = self._previous_close[symbol]
                change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0
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
                    "nearLimitUp": change_pct >= 9.5,
                    "nearLimitDown": change_pct <= -9.5,
                }

                if self._auto_trader is not None and in_trading:
                    try:
                        await self._auto_trader.on_tick(tick_data)
                    except Exception as exc:
                        logger.warning("MockCollector auto_trader.on_tick error: %s", exc)

                    if self._clients:
                        try:
                            snapshot = self._auto_trader.get_portfolio_snapshot()
                            await self._broadcast(json.dumps(snapshot, separators=(",", ":")))
                        except Exception:
                            pass

                await self._broadcast(json.dumps(tick_data, separators=(",", ":")))
                await self._broadcast_quote_detail(symbol)
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

    async def _broadcast_quote_detail(self, symbol: str) -> None:
        for client, subscribed_symbol in list(self._quote_detail_subscriptions.items()):
            if subscribed_symbol != symbol:
                continue
            try:
                await self._send_quote_detail_snapshots(client, symbol)
            except Exception:
                self._clients.discard(client)
                self._quote_detail_subscriptions.pop(client, None)

    async def _send_quote_detail_snapshots(self, websocket, symbol: str) -> None:
        await websocket.send(json.dumps(self._build_order_book_snapshot(symbol), separators=(",", ":")))
        await websocket.send(json.dumps(self._build_trade_tape_snapshot(symbol), separators=(",", ":")))

    def _build_order_book_snapshot(self, symbol: str) -> dict[str, Any]:
        price = float(self._prices.get(symbol, 0.0))
        step = self._price_step(price)
        asks = [
            {"level": level, "price": round(price + step * level, 2), "volume": int(200 + level * 75)}
            for level in range(1, 6)
        ]
        bids = [
            {"level": level, "price": round(max(0.01, price - step * level), 2), "volume": int(260 + level * 90)}
            for level in range(1, 6)
        ]
        return {
            "type": "ORDER_BOOK_SNAPSHOT",
            "symbol": symbol,
            "timestamp": int(time.time() * 1000),
            "asks": asks,
            "bids": bids,
        }

    def _build_trade_tape_snapshot(self, symbol: str) -> dict[str, Any]:
        return {
            "type": "TRADE_TAPE_SNAPSHOT",
            "symbol": symbol,
            "timestamp": int(time.time() * 1000),
            "rows": list(self._trade_tape_buffers.get(symbol, ())),
        }

    def _record_trade_tape(self, symbol: str, *, price: float, volume: int, ts_ms: int) -> None:
        if volume <= 0:
            return
        previous_price = self._last_trade_prices.get(symbol, price)
        if price > previous_price:
            side = "outer"
        elif price < previous_price:
            side = "inner"
        else:
            side = "neutral"
        self._last_trade_prices[symbol] = price
        timestamp = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=_TZ_TW)
        self._trade_tape_buffers.setdefault(symbol, deque(maxlen=20)).appendleft(
            {
                "time": timestamp.strftime("%H:%M:%S"),
                "price": round(price, 2),
                "volume": int(volume // 1000 if volume >= 1000 else volume),
                "side": side,
            }
        )

    @staticmethod
    def _price_step(price: float) -> float:
        if price >= 1000:
            return 1.0
        if price >= 500:
            return 0.5
        if price >= 100:
            return 0.1
        return 0.05


def _scan_symbols_sync() -> Any | None:
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
        if result and hasattr(result, "top_sector") and result.top_sector:
            logger.info("Auto scan: top sector=%s symbols=%d", result.top_sector, len(result.top_symbols))
        return result
    except Exception as exc:
        logger.error("Auto scan failed: %s", exc)
        return None


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


SECTOR_MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sector_map.json")
FULL_SECTOR_MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "full_sector_map.json")
DAILY_PRICE_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "daily_price_cache.json")
DAILY_PRICE_MIN_BARS = 15


def _prime_daily_price_cache(symbols: list[str]) -> Any:
    try:
        cache_module = importlib.import_module("daily_price_cache")
        cache = cache_module.DailyPriceCache()
        cache.load(DAILY_PRICE_CACHE_PATH)

        symbols_to_backfill = [s for s in symbols if not cache.has_enough_data(s, DAILY_PRICE_MIN_BARS)]
        if symbols_to_backfill:
            try:
                fetcher_module = importlib.import_module("historical_data")
                fetcher = fetcher_module.TWSEHistoricalFetcher()
                end_date = _today_trade_date()
                start_date = (
                    datetime.date.fromisoformat(end_date) - datetime.timedelta(days=90)
                ).isoformat()
                logger.info(
                    "Backfilling daily price history for %d symbols (%s -> %s)",
                    len(symbols_to_backfill),
                    start_date,
                    end_date,
                )
                for symbol in symbols_to_backfill:
                    try:
                        bars = fetcher.fetch_bars(symbol, start_date, end_date)
                        for bar in bars:
                            cache.add_bar(
                                symbol,
                                cache_module.DailyBar(
                                    date=datetime.datetime.fromtimestamp(
                                        bar.ts_ms / 1000,
                                        tz=datetime.timezone(datetime.timedelta(hours=8)),
                                    ).strftime("%Y-%m-%d"),
                                    open=bar.open,
                                    high=bar.high,
                                    low=bar.low,
                                    close=bar.close,
                                    volume=bar.volume,
                                ),
                            )
                    except Exception as exc:
                        logger.warning("Daily price backfill failed for %s: %s", symbol, exc)
                cache.prune()
                os.makedirs(os.path.dirname(DAILY_PRICE_CACHE_PATH), exist_ok=True)
                cache.save(DAILY_PRICE_CACHE_PATH)
                logger.info("Daily price cache saved: %d symbols", len(cache.symbols()))
            except Exception as exc:
                logger.warning("Daily price backfill skipped: %s", exc)
        return cache
    except Exception as exc:
        logger.warning("Daily price cache init failed: %s", exc)
        return None


def inject_daily_price_cache(auto_trader: Any, symbols: list[str]) -> None:
    if auto_trader is None:
        return
    cache = _prime_daily_price_cache(symbols)
    if cache is not None and hasattr(auto_trader, "set_daily_price_cache"):
        auto_trader.set_daily_price_cache(cache, DAILY_PRICE_CACHE_PATH)


def _save_sector_map(sector_map: dict[str, str]) -> None:
    try:
        os.makedirs(os.path.dirname(SECTOR_MAP_PATH), exist_ok=True)
        with open(SECTOR_MAP_PATH, "w", encoding="utf-8") as file:
            json.dump(sector_map, file, ensure_ascii=False)
        logger.info("Saved sector map: %d symbols -> %s", len(sector_map), SECTOR_MAP_PATH)
    except Exception as exc:
        logger.warning("Failed to save sector map: %s", exc)


def _prime_full_sector_map() -> dict[str, str]:
    try:
        from sector_data import fetch_sector_map

        return fetch_sector_map(cache_path=FULL_SECTOR_MAP_PATH)
    except Exception as exc:
        logger.warning("Full sector map fetch failed, falling back to scan-only map: %s", exc)
        return {}


def _load_sector_map_into_trader(auto_trader: Any) -> None:
    if auto_trader is None or not hasattr(auto_trader, "set_symbol_sector"):
        return

    sector_map: dict[str, str] = _prime_full_sector_map()
    if os.path.exists(SECTOR_MAP_PATH):
        try:
            with open(SECTOR_MAP_PATH, encoding="utf-8") as file:
                scan_map: dict[str, str] = json.load(file)
            sector_map.update(scan_map)
        except Exception as exc:
            logger.warning("Failed to load scan sector map: %s", exc)

    for symbol, sector in sector_map.items():
        auto_trader.set_symbol_sector(symbol, sector)
    logger.info("Loaded sector map: %d symbols total", len(sector_map))


def load_auto_trader(
    enabled: bool,
    *,
    strategy_mode: str = "intraday",
    build_strategy_dependencies_fn: Callable[[str], dict[str, Any]] = build_strategy_dependencies,
    prime_institutional_flow_cache_fn: Callable[[dict[str, Any]], None] = prime_institutional_flow_cache,
) -> Any | None:
    if not enabled:
        logger.info("Auto trader disabled by ENABLE_AUTO_TRADER")
        return None

    try:
        trader_module = importlib.import_module("auto_trader")
        trader_factory = getattr(trader_module, "trader_from_env")
        strategy_dependencies = build_strategy_dependencies_fn(strategy_mode)
        prime_institutional_flow_cache_fn(strategy_dependencies)
        trader = trader_factory(**strategy_dependencies)
        _load_sector_map_into_trader(trader)
        return trader
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


def _load_dynamic_shioaji_universe_from_env() -> dict[str, dict[str, Any]]:
    import shioaji as sj

    bridge_module = importlib.import_module("sinopac_bridge")
    api = sj.Shioaji(simulation=os.getenv("SINOPAC_SIMULATION", "false").lower() == "true")
    api.login(
        api_key=os.environ["SINOPAC_API_KEY"],
        secret_key=os.environ["SINOPAC_SECRET_KEY"],
    )
    try:
        return bridge_module.load_shioaji_stock_universe(api)
    finally:
        try:
            api.logout()
        except Exception:
            pass


def resolve_runtime_symbols(
    *,
    raw_symbols: str = "",
    use_mock: bool,
    auto_universe_loader: Any | None = None,
) -> list[str]:
    if raw_symbols.strip():
        return resolve_symbols(raw_symbols)
    if use_mock:
        return resolve_symbols("")

    loader = auto_universe_loader or _load_dynamic_shioaji_universe_from_env
    try:
        universe = loader()
        if isinstance(universe, dict):
            symbols = [str(symbol).strip() for symbol in universe.keys() if str(symbol).strip()]
        else:
            symbols = [str(symbol).strip() for symbol in universe if str(symbol).strip()]
        if not symbols:
            raise RuntimeError("dynamic_universe_empty")
        return _stable_unique(symbols)
    except Exception as exc:
        logger.warning(
            "Dynamic Shioaji universe load failed, falling back to DEFAULT_TW_SYMBOLS: %s",
            exc,
        )
        return list(DEFAULT_TW_SYMBOLS)


def build_runtime_components(
    *,
    raw_symbols: str,
    ws_host: str,
    ws_port: int,
    use_mock: bool,
    resolve_runtime_symbols_fn: Callable[..., list[str]] = resolve_runtime_symbols,
    load_auto_trader_fn: Callable[..., Any | None] = load_auto_trader,
    inject_daily_price_cache_fn: Callable[[Any, list[str]], None] = inject_daily_price_cache,
) -> RuntimeComponents:
    strategy_mode = os.getenv("STRATEGY_MODE", "intraday").strip() or "intraday"
    auto_trader = load_auto_trader_fn(
        _env_flag("ENABLE_AUTO_TRADER", "true"),
        strategy_mode=strategy_mode,
    )
    state_store = ReadyStateStore()
    analyzer = _build_analyzer_service()
    notifier = ReadyNotifier()
    ipc_manager = SharedMemoryIPC(size=int(os.getenv("IPC_SHARED_MEMORY_SIZE", "1024")))

    if use_mock:
        symbols = resolve_runtime_symbols_fn(raw_symbols=raw_symbols, use_mock=True)
        inject_daily_price_cache_fn(auto_trader, symbols)
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

    symbols = resolve_runtime_symbols_fn(raw_symbols=raw_symbols, use_mock=False)
    auto_scan = os.getenv("SINOPAC_AUTO_SCAN", "false").lower() == "true"
    if auto_scan:
        logger.info("Mode: SINOPAC AUTO-SCAN top=%s", os.getenv("SINOPAC_SCAN_TOP", "100"))
        scan_result = _scan_symbols_sync()
        if scan_result is not None:
            if hasattr(scan_result, "symbol_details") and scan_result.symbol_details:
                scanned = [item.code for item in scan_result.symbol_details]
                sector_map = {item.code: item.sector for item in scan_result.symbol_details if item.sector}
                if auto_trader is not None:
                    for symbol, sector in sector_map.items():
                        auto_trader.set_symbol_sector(symbol, sector)
                    logger.info("Wired sector mapping for %d symbols", len(sector_map))
                if sector_map:
                    _save_sector_map(sector_map)
            elif hasattr(scan_result, "top_symbols"):
                scanned = list(scan_result.top_symbols)
            else:
                scanned = list(scan_result)
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
            logger.warning("Auto scan returned no symbols, falling back to default universe")
    else:
        logger.info("Mode: SINOPAC")

    inject_daily_price_cache_fn(auto_trader, symbols)
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

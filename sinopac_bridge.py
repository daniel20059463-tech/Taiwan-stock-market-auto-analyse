from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import websockets
import websockets.server

logger = logging.getLogger(__name__)

# ?? ?啗鈭斗??挾撣豢 ??????????????????????????????????????????????????????????
_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
_MARKET_OPEN_MIN  = 8 * 60   # 08:00
_MARKET_CLOSE_MIN = 17 * 60  # 17:00
_LIMIT_UP_PCT = 9.5
_LIMIT_DOWN_PCT = -9.5
_TAIEX_SYMBOL = "TSE001"          # 加權指數在 shioaji 的合約代號

class SinopacCollector:
    def __init__(
        self,
        symbols: list[str],
        *,
        api_key: str,
        secret_key: str,
        ws_host: str = "127.0.0.1",
        ws_port: int = 8765,
        simulation: bool = False,
        bootstrap_symbol_limit: int = 24,
        bootstrap_bar_limit: int = 8,
        flush_interval_ms: int = 250,
        auto_trader: Any = None,
        sentiment_consumer: Any = None,   # SentimentConsumer | None
    ) -> None:
        self._symbols = symbols
        self._api_key = api_key
        self._secret_key = secret_key
        self._ws_host = ws_host
        self._ws_port = ws_port
        self._simulation = simulation
        self._auto_trader = auto_trader
        self._sentiment_consumer = sentiment_consumer
        self._bootstrap_symbol_limit = max(0, bootstrap_symbol_limit)
        self._bootstrap_bar_limit = max(0, bootstrap_bar_limit)

        self._api: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[websockets.server.WebSocketServerProtocol] = set()
        self._accepting = True
        self._server: websockets.server.WebSocketServer | None = None
        self._broadcast_task: asyncio.Task[None] | None = None
        self._sentiment_task: asyncio.Task[None] | None = None
        self._market_meta: dict[str, dict[str, Any]] = {}
        self._bootstrapped_total_volume: dict[str, int] = {}
        self._current_ticks: dict[str, dict[str, Any]] = {}
        self._dirty_symbols: set[str] = set()
        self._tick_event: asyncio.Event | None = None
        self._dropped_ticks = 0
        self._flush_interval_seconds = max(0.05, flush_interval_ms / 1_000)
        self._taiex_prev_close: float = 0.0   # 加權指數前收（用於計算漲跌幅）
        self._last_tick_monotonic: float = 0.0
        self._watchdog_task: asyncio.Task[None] | None = None
        self._reconnecting: bool = False

    def _get_contract_sync(self, symbol: str) -> Any | None:
        if self._api is None:
            return None

        for market in ("TSE", "OTC", "OES"):
            try:
                return getattr(self._api.Contracts.Stocks, market)[symbol]
            except Exception:
                continue
        return None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._accepting = True
        self._tick_event = asyncio.Event()
        self._server = await websockets.serve(self._ws_handler, self._ws_host, self._ws_port)
        self._broadcast_task = asyncio.create_task(self._broadcast_loop(), name="sinopac-broadcast")
        if self._sentiment_consumer is not None:
            await self._sentiment_consumer.start()
        await self._loop.run_in_executor(None, self._login_and_subscribe_sync)
        self._last_tick_monotonic = time.monotonic()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop(), name="sinopac-watchdog")
        logger.info("SinopacCollector ready on ws://%s:%d symbols=%s", self._ws_host, self._ws_port, self._symbols)

    async def stop_accepting(self) -> None:
        self._accepting = False

    async def stop(self) -> None:
        self._accepting = False
        if self._sentiment_consumer is not None:
            await self._sentiment_consumer.stop()
        for task in (self._broadcast_task, self._watchdog_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self._api is not None:
            try:
                self._api.logout()
            except Exception:
                pass
            self._api = None

    def pending_count(self) -> int:
        return len(self._dirty_symbols)

    async def _watchdog_loop(self) -> None:
        """每 60 秒檢查一次：交易時段內超過 5 分鐘無 tick，自動重新登入並訂閱。"""
        _CHECK_INTERVAL = 60.0
        _TICK_TIMEOUT = 300.0  # 5 分鐘
        try:
            while self._accepting:
                await asyncio.sleep(_CHECK_INTERVAL)
                if not self._accepting or self._reconnecting:
                    continue
                now_tw = datetime.datetime.now(tz=_TZ_TW)
                t = now_tw.hour * 60 + now_tw.minute
                if not (_MARKET_OPEN_MIN <= t <= _MARKET_CLOSE_MIN):
                    continue
                elapsed = time.monotonic() - self._last_tick_monotonic
                if elapsed < _TICK_TIMEOUT:
                    continue
                logger.warning(
                    "交易時段內 %.0f 秒無 tick，重新連線永豐 API…", elapsed
                )
                loop = self._loop
                if loop is None:
                    continue
                try:
                    await loop.run_in_executor(None, self._reconnect_sync)
                    logger.info("永豐 API 重新連線成功")
                except Exception as exc:
                    logger.error("永豐 API 重新連線失敗: %s", exc)
        except asyncio.CancelledError:
            return

    def _reconnect_sync(self) -> None:
        """斷線重連：登出舊 API → 重新 login + subscribe。"""
        self._reconnecting = True
        try:
            if self._api is not None:
                try:
                    self._api.logout()
                except Exception:
                    pass
                self._api = None
            self._login_and_subscribe_sync()
            self._last_tick_monotonic = time.monotonic()
        finally:
            self._reconnecting = False

    def _offer_tick(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get("symbol", ""))
        if not symbol:
            self._dropped_ticks += 1
            return
        self._last_tick_monotonic = time.monotonic()
        self._current_ticks[symbol] = payload
        self._dirty_symbols.add(symbol)
        if self._tick_event is not None:
            self._tick_event.set()

    def _offer_tick_threadsafe(self, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._offer_tick, payload)

    def _login_and_subscribe_sync(self) -> None:
        import shioaji as sj
        from shioaji.constant import QuoteType

        api = sj.Shioaji(simulation=self._simulation)
        api.login(api_key=self._api_key, secret_key=self._secret_key)
        self._api = api
        loop = self._loop
        today = datetime.date.today().strftime("%Y-%m-%d")

        contracts_by_symbol: dict[str, Any] = {}
        should_bootstrap = self._bootstrap_bar_limit > 0 and len(self._symbols) <= self._bootstrap_symbol_limit
        official_meta = _load_twse_seed_quotes(self._symbols)
        if not should_bootstrap:
            logger.info(
                "Skipping kbar bootstrap symbols=%d symbol_limit=%d bar_limit=%d",
                len(self._symbols),
                self._bootstrap_symbol_limit,
                self._bootstrap_bar_limit,
            )
        for symbol in self._symbols:
            contract = self._get_contract_sync(symbol)
            if contract is None:
                exc = RuntimeError("contract_not_found")
                logger.warning("Contract load failed for %s: %s", symbol, exc)
                continue

            contracts_by_symbol[symbol] = contract
            meta = self._load_symbol_meta_sync(contract)
            if symbol in official_meta:
                meta = _merge_seed_meta(meta, official_meta[symbol])
            self._market_meta[symbol] = meta
            self._emit_seed_payload(symbol, self._market_meta[symbol])
            if should_bootstrap:
                self._bootstrap_kbars_sync(symbol, today)

        @api.on_tick_stk_v1()
        def _on_tick(exchange: Any, tick: Any) -> None:
            if not self._accepting or loop is None or loop.is_closed():
                return
            symbol = str(getattr(tick, "code", ""))
            payload = _normalise_tick(tick, self._market_meta.get(symbol, {}))
            if payload is None:
                return
            self._offer_tick_threadsafe(payload)

        for symbol, contract in contracts_by_symbol.items():
            try:
                api.quote.subscribe(contract, quote_type=QuoteType.Tick)
                logger.info("Subscribed live tick: %s", symbol)
            except Exception as exc:
                logger.warning("Subscription failed for %s: %s", symbol, exc)

        # ── 訂閱加權指數（大盤方向過濾）────────────────────────────────────────
        try:
            taiex_contract = api.Contracts.Indices.TSE[_TAIEX_SYMBOL]
            snaps = api.snapshots([taiex_contract])
            if snaps:
                prev = _safe_number(snaps[0], ("reference", "reference_price", "close"), default=None)
                if prev and prev > 0:
                    self._taiex_prev_close = prev
            api.quote.subscribe(taiex_contract, quote_type=QuoteType.Tick)
            logger.info(
                "Subscribed TAIEX index (%s) prev_close=%.2f",
                _TAIEX_SYMBOL, self._taiex_prev_close,
            )
        except Exception as exc:
            logger.warning("TAIEX index subscription failed（大盤過濾將不生效）: %s", exc)

        def _on_idx_tick(exchange: Any, tick: Any) -> None:
            """接收加權指數 tick，更新 AutoTrader 的大盤漲跌幅。"""
            if loop is None or loop.is_closed() or self._auto_trader is None:
                return
            try:
                code = str(getattr(tick, "code", "") or "")
                if code != _TAIEX_SYMBOL:
                    return
                price = float(
                    getattr(tick, "close", None)
                    or getattr(tick, "price", None)
                    or 0
                )
                if price <= 0:
                    return
                prev = self._taiex_prev_close or price
                change_pct = (price - prev) / prev * 100 if prev else 0.0
                # update_market_index 是同步方法，可安全用 call_soon_threadsafe
                loop.call_soon_threadsafe(
                    self._auto_trader.update_market_index, change_pct
                )
            except Exception as exc:
                logger.debug("TAIEX tick normalisation error: %s", exc)

        if not _bind_index_tick_handler(api, _on_idx_tick):
            logger.warning("TAIEX index tick hook unavailable in this Shioaji version; market filter disabled")

    def _load_symbol_meta_sync(self, contract: Any) -> dict[str, Any]:
        symbol = str(getattr(contract, "code", ""))
        meta = {
            "name": str(getattr(contract, "name", symbol) or symbol),
            "sector": str(getattr(contract, "category", "Market") or "Market"),
            "lastPrice": None,
            "previousClose": None,
            "open": None,
            "high": None,
            "low": None,
            "totalVolume": 0,
        }

        if self._api is None:
            return meta

        try:
            snapshots = self._api.snapshots([contract])
            if snapshots:
                snapshot = snapshots[0]
                meta["lastPrice"] = _safe_number(snapshot, ("close", "close_price", "price", "last_price"), default=None)
                meta["previousClose"] = _safe_number(snapshot, ("reference", "reference_price", "close"), default=None)
                meta["open"] = _safe_number(snapshot, ("open",), default=meta["previousClose"])
                meta["high"] = _safe_number(snapshot, ("high",), default=meta["open"])
                meta["low"] = _safe_number(snapshot, ("low",), default=meta["open"])
                meta["totalVolume"] = int(_safe_number(snapshot, ("total_volume", "volume", "trade_volume"), default=0))
        except Exception as exc:
            logger.debug("Snapshot load failed for %s: %s", symbol, exc)

        return meta

    def _bootstrap_kbars_sync(self, symbol: str, date: str) -> None:
        loop = self._loop
        if loop is None or self._api is None:
            return

        try:
            contract = self._get_contract_sync(symbol)
            if contract is None:
                logger.info("No contract for %s", symbol)
                return
            kbars = self._api.kbars(contract, start=date, end=date)
            if kbars is None or not hasattr(kbars, "ts") or len(kbars.ts) == 0:
                logger.info("No kbars for %s on %s", symbol, date)
                return

            meta = self._market_meta.get(symbol, {})
            running_total_volume = int(meta.get("totalVolume") or 0)
            count = 0
            total_bars = len(kbars.ts)
            start_index = max(0, total_bars - self._bootstrap_bar_limit)

            for index in range(start_index, total_bars):
                ts_raw = kbars.ts[index]
                open_ = kbars.Open[index]
                high = kbars.High[index]
                low = kbars.Low[index]
                close = kbars.Close[index]
                vol = kbars.Volume[index]
                ts_s = _to_epoch_seconds(ts_raw)
                bar_volume = max(1, int(vol))
                partial = max(1, bar_volume // 4)

                staged_ticks = (
                    (0, float(open_), float(open_), float(open_), partial),
                    (15, float(high), float(high), float(open_), partial),
                    (30, float(low), float(high), float(low), partial),
                    (59, float(close), float(high), float(low), bar_volume - partial * 3),
                )

                for delta_s, price, bar_high, bar_low, delta_volume in staged_ticks:
                    volume_piece = max(1, int(delta_volume))
                    running_total_volume += volume_piece
                    payload = {
                        "symbol": symbol,
                        "name": meta.get("name", symbol),
                        "sector": meta.get("sector", "Market"),
                        "price": round(price, 2),
                        "volume": volume_piece,
                        "totalVolume": running_total_volume,
                        "previousClose": meta.get("previousClose", float(open_)),
                        "open": meta.get("open", float(open_)),
                        "high": round(float(bar_high), 2),
                        "low": round(float(bar_low), 2),
                        "ts": (ts_s + delta_s) * 1000,
                    }
                    self._offer_tick_threadsafe(payload)

                count += 1

            self._bootstrapped_total_volume[symbol] = running_total_volume
            logger.info("Bootstrapped %d kbars for %s", count, symbol)
        except Exception as exc:
            logger.warning("kbar bootstrap failed for %s: %s", symbol, exc)

    def _emit_seed_payload(self, symbol: str, meta: dict[str, Any]) -> None:
        price = _coalesce_number(meta.get("lastPrice"), meta.get("open"), meta.get("previousClose"))
        if price is None:
            return

        previous_close = _coalesce_number(meta.get("previousClose"), price) or price
        open_price = _coalesce_number(meta.get("open"), previous_close, price) or price
        high_price = _coalesce_number(meta.get("high"), price, open_price) or price
        low_price = _coalesce_number(meta.get("low"), price, open_price) or price
        payload = _sanitize_quote_payload({
            "symbol": symbol,
            "name": meta.get("name", symbol),
            "sector": meta.get("sector", "Market"),
            "price": round(float(price), 2),
            "volume": 0,
            "totalVolume": int(meta.get("totalVolume") or 0),
            "previousClose": previous_close,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "ts": int(time.time() * 1000),
        })
        if payload is not None:
            self._offer_tick_threadsafe(payload)

    def _session_bars_sync(self, symbol: str, limit: int = 240) -> list[dict[str, Any]]:
        if self._api is None:
            return []

        contract = self._get_contract_sync(symbol)
        if contract is None:
            return []

        today = datetime.date.today().strftime("%Y-%m-%d")
        try:
            kbars = self._api.kbars(contract, start=today, end=today)
        except Exception as exc:
            logger.warning("session kbars failed for %s: %s", symbol, exc)
            return []

        if kbars is None or not hasattr(kbars, "ts") or len(kbars.ts) == 0:
            return []

        bars: list[dict[str, Any]] = []
        start_index = max(0, len(kbars.ts) - max(1, limit))
        for index in range(start_index, len(kbars.ts)):
            bars.append(
                {
                    "time": _to_epoch_seconds(kbars.ts[index]) * 1000,
                    "open": round(float(kbars.Open[index]), 2),
                    "high": round(float(kbars.High[index]), 2),
                    "low": round(float(kbars.Low[index]), 2),
                    "close": round(float(kbars.Close[index]), 2),
                    "volume": int(kbars.Volume[index]),
                }
            )
        return bars

    def _history_bars_sync(self, symbol: str, months: int = 6) -> list[dict[str, Any]]:
        if self._api is None:
            return []

        contract = self._get_contract_sync(symbol)
        if contract is None:
            return []

        end_date = datetime.date.today()
        start_date = (end_date.replace(day=1) - datetime.timedelta(days=max(32, months * 32))).strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        try:
            kbars = self._api.kbars(contract, start=start_date, end=end_str)
        except Exception as exc:
            logger.warning("history kbars failed for %s: %s", symbol, exc)
            return []

        if kbars is None or not hasattr(kbars, "ts") or len(kbars.ts) == 0:
            return []

        daily: dict[str, dict[str, Any]] = {}
        for index in range(len(kbars.ts)):
            dt = datetime.datetime.fromtimestamp(_to_epoch_seconds(kbars.ts[index]))
            day_key = dt.strftime("%Y-%m-%d")
            open_ = round(float(kbars.Open[index]), 2)
            high = round(float(kbars.High[index]), 2)
            low = round(float(kbars.Low[index]), 2)
            close = round(float(kbars.Close[index]), 2)
            volume = int(kbars.Volume[index])

            if day_key not in daily:
                daily[day_key] = {
                    "time": int(datetime.datetime(dt.year, dt.month, dt.day, 17, 0).timestamp() * 1000),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
                continue

            candle = daily[day_key]
            candle["high"] = max(float(candle["high"]), high)
            candle["low"] = min(float(candle["low"]), low)
            candle["close"] = close
            candle["volume"] = int(candle["volume"]) + volume

        return [daily[key] for key in sorted(daily.keys())][-max(1, months * 31) :]

    async def _handle_ws_message(self, websocket: websockets.server.WebSocketServerProtocol, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return

        if not isinstance(payload, dict):
            return

        symbol = str(payload.get("symbol", "")).strip()
        if not symbol:
            return

        loop = self._loop
        if loop is None:
            return

        if payload.get("type") == "session_bars":
            limit = max(1, int(payload.get("limit", 240)))
            candles = await loop.run_in_executor(None, self._session_bars_sync, symbol, limit)
            source = "sinopac" if candles else "fallback"
            message = {
                "type": "SESSION_BARS",
                "symbol": symbol,
                "candles": candles,
                "source": source,
            }
            if not candles:
                message["error"] = "session_bars_unavailable"
            await websocket.send(json.dumps(message, separators=(",", ":")))
            return

        if payload.get("type") == "history_bars":
            months = max(1, int(payload.get("months", 6)))
            candles = await loop.run_in_executor(None, self._history_bars_sync, symbol, months)
            source = "sinopac" if candles else "fallback"
            message = {
                "type": "HISTORY_BARS",
                "symbol": symbol,
                "candles": candles,
                "source": source,
            }
            if not candles:
                message["error"] = "history_bars_unavailable"
            await websocket.send(json.dumps(message, separators=(",", ":")))

    async def _ws_handler(
        self,
        websocket: websockets.server.WebSocketServerProtocol,
        path: str = "/",
    ) -> None:
        self._clients.add(websocket)
        remote = getattr(websocket, "remote_address", "?")
        logger.info("Dashboard connected: %s (total=%d)", remote, len(self._clients))
        try:
            if self._current_ticks:
                await websocket.send(json.dumps(list(self._current_ticks.values()), separators=(",", ":")))
            if self._auto_trader is not None:
                try:
                    snapshot = self._auto_trader.get_portfolio_snapshot()
                    await websocket.send(json.dumps(snapshot, separators=(",", ":")))
                except Exception as exc:
                    logger.warning("Initial portfolio snapshot failed: %s", exc)
            async for raw in websocket:
                if isinstance(raw, str):
                    await self._handle_ws_message(websocket, raw)
        finally:
            self._clients.discard(websocket)
            logger.info("Dashboard disconnected: %s (total=%d)", remote, len(self._clients))

    async def _broadcast_loop(self) -> None:
        while True:
            try:
                tick_event = self._tick_event
                if tick_event is None:
                    return
                try:
                    await asyncio.wait_for(tick_event.wait(), timeout=self._flush_interval_seconds)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                return

            if tick_event is not None:
                tick_event.clear()

            if not self._dirty_symbols:
                continue

            batch = [self._current_ticks[symbol] for symbol in self._dirty_symbols if symbol in self._current_ticks]
            self._dirty_symbols.clear()
            if not batch:
                continue

            if self._clients:
                message = json.dumps(batch, separators=(",", ":"))
                dead: list[websockets.server.WebSocketServerProtocol] = []
                for client in list(self._clients):
                    try:
                        await client.send(message)
                    except Exception:
                        dead.append(client)
                for client in dead:
                    self._clients.discard(client)

            if self._auto_trader is not None:
                portfolio_dirty = False
                for payload in batch:
                    try:
                        await self._auto_trader.on_tick(payload)
                        portfolio_dirty = True
                    except Exception as exc:
                        logger.warning("AutoTrader.on_tick error: %s", exc)

                # 撱???唳??翰?抒策???蝡?                if portfolio_dirty and self._clients:
                    try:
                        snapshot = self._auto_trader.get_portfolio_snapshot()
                        msg = json.dumps(snapshot, separators=(",", ":"))
                        dead2: list[websockets.server.WebSocketServerProtocol] = []
                        for client in list(self._clients):
                            try:
                                await client.send(msg)
                            except Exception:
                                dead2.append(client)
                        for client in dead2:
                            self._clients.discard(client)
                    except Exception as exc:
                        logger.warning("Portfolio broadcast error: %s", exc)


def _to_epoch_seconds(ts_raw: Any) -> int:
    if isinstance(ts_raw, (int, float)):
        value = int(ts_raw)
        if value > 1_000_000_000_000_000:
            return value // 1_000_000_000
        if value > 1_000_000_000_000:
            return value // 1_000_000
        if value > 1_000_000_000:
            return value
        return value
    if hasattr(ts_raw, "timestamp"):
        return int(ts_raw.timestamp())
    return int(str(ts_raw))


def _bind_index_tick_handler(api: Any, callback: Any) -> bool:
    decorator_factory = getattr(api, "on_tick_idx_v1", None)
    if not callable(decorator_factory):
        return False
    decorator_factory()(callback)
    return True


def _safe_number(obj: Any, attrs: tuple[str, ...], default: float | None = None) -> float | None:
    for attr in attrs:
        value = getattr(obj, attr, None)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return default


def _coalesce_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


def _parse_mis_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _parse_mis_level(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    first = str(value).split("_", 1)[0].strip()
    return _parse_mis_number(first)


def _mis_last_price(item: dict[str, Any]) -> float | None:
    direct = _parse_mis_number(item.get("z"))
    if direct is not None:
        return direct

    bid = _parse_mis_level(item.get("b"))
    ask = _parse_mis_level(item.get("a"))
    if bid is not None and ask is not None:
        return round((bid + ask) / 2, 2)
    return bid or ask


def _load_twse_seed_quotes(symbols: list[str], batch_size: int = 50) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        channels = "|".join(f"tse_{symbol}.tw" for symbol in batch)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={channels}&json=1&delay=0"
        try:
            with urlopen(url, timeout=8) as response:
                payload = json.load(response)
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.debug("TWSE MIS seed fetch failed batch_start=%d: %s", start, exc)
            continue

        for item in payload.get("msgArray", []):
            symbol = str(item.get("c", "")).strip()
            if not symbol:
                continue
            last_price = _mis_last_price(item)
            previous_close = _parse_mis_number(item.get("y"))
            open_price = _parse_mis_number(item.get("o"))
            high_price = _parse_mis_number(item.get("h"))
            low_price = _parse_mis_number(item.get("l"))
            total_volume = int(_parse_mis_number(item.get("v")) or 0)
            results[symbol] = {
                "name": str(item.get("n") or symbol),
                "lastPrice": last_price,
                "previousClose": previous_close,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "totalVolume": total_volume,
            }
    return results


def _merge_seed_meta(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in fallback.items():
        if value in (None, "", 0):
            continue
        if merged.get(key) in (None, "", 0):
            merged[key] = value
    return merged


def _sanitize_quote_payload(payload: dict[str, Any], *, max_deviation_pct: float = 15.0) -> dict[str, Any] | None:
    symbol = str(payload.get("symbol", "")).strip()
    if not symbol:
        return None

    price = _coalesce_number(payload.get("price"))
    previous_close = _coalesce_number(payload.get("previousClose"), price)
    open_price = _coalesce_number(payload.get("open"), previous_close, price)
    high_price = _coalesce_number(payload.get("high"), price, open_price)
    low_price = _coalesce_number(payload.get("low"), price, open_price)

    if price is None or price <= 0 or previous_close is None or previous_close <= 0:
        return None

    if open_price is None or open_price <= 0:
        open_price = previous_close
    if high_price is None or high_price <= 0:
        high_price = max(price, open_price)
    if low_price is None or low_price <= 0:
        low_price = min(price, open_price)

    high_price = max(high_price, price, open_price)
    low_price = min(low_price, price, open_price)

    deviation_pct = abs((price - previous_close) / previous_close * 100) if previous_close else 0.0
    if deviation_pct > max_deviation_pct:
        logger.warning(
            "Dropping abnormal quote symbol=%s price=%s previous_close=%s deviation_pct=%.2f",
            symbol,
            price,
            previous_close,
            deviation_pct,
        )
        return None

    volume = max(0, int(_coalesce_number(payload.get("volume"), 0) or 0))
    total_volume = max(volume, int(_coalesce_number(payload.get("totalVolume"), volume) or volume))
    ts_ms = int(_coalesce_number(payload.get("ts"), time.time() * 1000) or int(time.time() * 1000))
    change_pct = (price - previous_close) / previous_close * 100 if previous_close else 0.0
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=_TZ_TW)
    current_minute = dt.hour * 60 + dt.minute

    return {
        "symbol": symbol,
        "name": payload.get("name", symbol),
        "sector": payload.get("sector", "Market"),
        "price": round(float(price), 2),
        "volume": volume,
        "totalVolume": total_volume,
        "previousClose": round(float(previous_close), 2),
        "open": round(float(open_price), 2),
        "high": round(float(high_price), 2),
        "low": round(float(low_price), 2),
        "ts": ts_ms,
        "changePct": round(change_pct, 2),
        "inTradingHours": _MARKET_OPEN_MIN <= current_minute <= _MARKET_CLOSE_MIN,
        "nearLimitUp": change_pct >= _LIMIT_UP_PCT,
        "nearLimitDown": change_pct <= _LIMIT_DOWN_PCT,
    }


def _normalise_tick(tick: Any, meta: dict[str, Any]) -> dict[str, Any] | None:
    try:
        symbol = str(getattr(tick, "code"))
        price = float(getattr(tick, "close"))
        volume = int(getattr(tick, "volume"))
        raw_ts = getattr(tick, "ts")

        if isinstance(raw_ts, float) and raw_ts < 1e12:
            ts_ms = int(raw_ts * 1_000)
        elif raw_ts > 1_000_000_000_000_000:
            ts_ms = int(raw_ts // 1_000_000)
        elif raw_ts > 1_000_000_000_000:
            ts_ms = int(raw_ts // 1_000)
        else:
            ts_ms = int(raw_ts * 1_000)

        total_volume = int(
            _safe_number(tick, ("total_volume", "total_vol", "acc_volume", "acc_vol", "volume_total"), default=None)
            or meta.get("totalVolume")
            or volume
        )
        previous_close = _safe_number(tick, ("reference", "reference_price", "ref_price", "yesterday_close"), default=meta.get("previousClose"))
        open_price = _safe_number(tick, ("open", "open_price"), default=meta.get("open") or previous_close or price)
        high_price = _safe_number(tick, ("high", "high_price"), default=meta.get("high") or price)
        low_price = _safe_number(tick, ("low", "low_price"), default=meta.get("low") or price)
        prev = previous_close if previous_close is not None else price

        return _sanitize_quote_payload({
            "symbol": symbol,
            "name": meta.get("name", symbol),
            "sector": meta.get("sector", "Market"),
            "price": price,
            "volume": volume,
            "totalVolume": total_volume,
            "previousClose": prev,
            "open": open_price if open_price is not None else price,
            "high": high_price if high_price is not None else price,
            "low": low_price if low_price is not None else price,
            "ts": ts_ms,
        })
    except Exception as exc:
        logger.debug("Tick normalisation error: %s", exc)
        return None


def collector_from_env(
    symbols: list[str],
    auto_trader: Any = None,
    sentiment_consumer: Any = None,
) -> SinopacCollector:
    return SinopacCollector(
        symbols=symbols,
        api_key=os.environ["SINOPAC_API_KEY"],
        secret_key=os.environ["SINOPAC_SECRET_KEY"],
        ws_host=os.getenv("WS_HOST", "127.0.0.1"),
        ws_port=int(os.getenv("WS_PORT", "8765")),
        simulation=os.getenv("SINOPAC_SIMULATION", "false").lower() == "true",
        bootstrap_symbol_limit=int(os.getenv("SINOPAC_BOOTSTRAP_SYMBOL_LIMIT", "24")),
        bootstrap_bar_limit=int(os.getenv("SINOPAC_BOOTSTRAP_BAR_LIMIT", "8")),
        flush_interval_ms=int(os.getenv("SINOPAC_FLUSH_INTERVAL_MS", "250")),
        auto_trader=auto_trader,
        sentiment_consumer=sentiment_consumer,
    )

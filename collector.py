from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Optional, Set

import aiohttp

logger = logging.getLogger(__name__)


class TokenBucket:
    def __init__(self, rate: float, capacity: float) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    async def acquire(self, tokens: float = 1.0) -> None:
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait_time = deficit / self.rate
            await asyncio.sleep(wait_time)


class CoalescingQueue:
    def __init__(self, maxsize: int = 500) -> None:
        self.maxsize = maxsize
        self._data: dict[str, Any] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()

    async def put(self, symbol: str, data: Any) -> None:
        async with self._lock:
            if symbol in self._data:
                self._data[symbol] = data
            else:
                if len(self._data) >= self.maxsize:
                    return
                self._data[symbol] = data
                self._order.append(symbol)
            self._not_empty.set()

    async def get(self) -> tuple[str, Any]:
        while True:
            await self._not_empty.wait()
            async with self._lock:
                if self._order:
                    symbol = self._order.pop(0)
                    data = self._data.pop(symbol)
                    if not self._order:
                        self._not_empty.clear()
                    return symbol, data
                else:
                    self._not_empty.clear()

    def qsize(self) -> int:
        return len(self._data)


class RateLimitedFetcher:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        token_bucket: TokenBucket,
        max_retries: int = 5,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
    ) -> None:
        self.session = session
        self.semaphore = semaphore
        self.token_bucket = token_bucket
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff

    def _jitter(self, attempt: int) -> float:
        cap = min(self.base_backoff * (2 ** attempt), self.max_backoff)
        return random.uniform(0, cap)

    async def fetch(self, url: str, **kwargs: Any) -> Any:
        for attempt in range(self.max_retries):
            await self.token_bucket.acquire()
            try:
                async with self.semaphore:
                    async with self.session.get(url, **kwargs) as resp:
                        if resp.status == 429:
                            wait = self._jitter(attempt)
                            logger.warning("429 rate limited, backing off %.2fs", wait)
                            await asyncio.sleep(wait)
                            continue
                        resp.raise_for_status()
                        return await resp.json()
            except aiohttp.ClientError as exc:
                wait = self._jitter(attempt)
                logger.warning("ClientError on attempt %d: %s, retrying in %.2fs", attempt, exc, wait)
                if attempt >= self.max_retries - 1:
                    raise
                await asyncio.sleep(wait)
        return None


class WebSocketCollector:
    def __init__(
        self,
        uri: str,
        queue: CoalescingQueue,
        task_set: Set[asyncio.Task],
        reconnect_base: float = 1.0,
        reconnect_max: float = 60.0,
        ws_connect: Any = None,
    ) -> None:
        self.uri = uri
        self.queue = queue
        self.task_set = task_set
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self._ws_connect = ws_connect
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def _get_ws_connect(self) -> Any:
        if self._ws_connect is not None:
            return self._ws_connect
        import websockets
        return websockets.connect

    def start(self) -> None:
        self._running = True
        self._ws_connect = self._get_ws_connect()
        task = asyncio.get_running_loop().create_task(self._run_loop())
        self._task = task
        self.task_set.add(task)
        task.add_done_callback(self.task_set.discard)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def _run_loop(self) -> None:
        delay = self.reconnect_base
        while self._running:
            try:
                async with self._ws_connect(self.uri) as ws:
                    delay = self.reconnect_base
                    async for raw in ws:
                        if not self._running:
                            return
                        try:
                            data = json.loads(raw)
                            symbol = data.get("symbol", "unknown")
                            await self.queue.put(symbol, data)
                        except Exception as exc:
                            logger.warning("Failed to parse WS message: %s", exc)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if not self._running:
                    return
                logger.warning("WS error: %s, reconnecting in %.2fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max)


class NewsCollector:
    def __init__(
        self,
        urls: list[str],
        fetcher: RateLimitedFetcher,
        task_set: Set[asyncio.Task],
        interval: float = 60.0,
    ) -> None:
        self.urls = urls
        self.fetcher = fetcher
        self.task_set = task_set
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        self._running = True
        task = asyncio.get_running_loop().create_task(self._poll_loop())
        self._task = task
        self.task_set.add(task)
        task.add_done_callback(self.task_set.discard)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def _poll_loop(self) -> None:
        while self._running:
            for url in self.urls:
                if not self._running:
                    return
                try:
                    await self.fetcher.fetch(url)
                except Exception as exc:
                    logger.warning("News fetch error for %s: %s", url, exc)
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                return


class CollectorService:
    def __init__(
        self,
        ws_uri: str,
        news_urls: list[str],
        semaphore_limit: int = 5,
        qps_rate: float = 10.0,
        qps_capacity: float = 20.0,
        queue_maxsize: int = 500,
        ws_connect: Any = None,
        session: Any = None,
        news_interval: float = 60.0,
    ) -> None:
        self.ws_uri = ws_uri
        self.news_urls = news_urls
        self.semaphore_limit = semaphore_limit
        self.qps_rate = qps_rate
        self.qps_capacity = qps_capacity
        self.queue_maxsize = queue_maxsize
        self._ws_connect = ws_connect
        self._injected_session = session
        self.news_interval = news_interval
        self.task_set: set[asyncio.Task] = set()
        self.queue = CoalescingQueue(maxsize=queue_maxsize)
        self._session: Any = None
        self._ws_collector: Optional[WebSocketCollector] = None
        self._news_collector: Optional[NewsCollector] = None

    async def start(self) -> None:
        if self._injected_session is not None:
            self._session = self._injected_session
        else:
            self._session = aiohttp.ClientSession()

        semaphore = asyncio.Semaphore(self.semaphore_limit)
        token_bucket = TokenBucket(self.qps_rate, self.qps_capacity)
        fetcher = RateLimitedFetcher(self._session, semaphore, token_bucket)

        self._ws_collector = WebSocketCollector(
            uri=self.ws_uri,
            queue=self.queue,
            task_set=self.task_set,
            ws_connect=self._ws_connect,
        )
        self._ws_collector.start()

        self._news_collector = NewsCollector(
            urls=self.news_urls,
            fetcher=fetcher,
            task_set=self.task_set,
            interval=self.news_interval,
        )
        self._news_collector.start()

    async def stop(self) -> None:
        if self._ws_collector is not None:
            await self._ws_collector.stop()
        if self._news_collector is not None:
            await self._news_collector.stop()
        if self._session is not None and self._injected_session is None:
            await self._session.close()
        elif self._session is not None and self._injected_session is not None:
            await self._session.close()

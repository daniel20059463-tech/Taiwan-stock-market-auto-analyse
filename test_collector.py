from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from collector import (
    CoalescingQueue,
    CollectorService,
    RateLimitedFetcher,
    TokenBucket,
)


# ---------------------------------------------------------------------------
# Helper classes
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self) -> None:
        self.status = 200

    def raise_for_status(self) -> None:
        pass

    async def json(self) -> dict:
        return {}

    async def __aenter__(self) -> _MockResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class TrackingMockSession:
    """Tracks peak concurrent requests."""

    def __init__(self, counter: list, call_times: list) -> None:
        self.counter = counter  # [current_concurrent, peak_concurrent]
        self.call_times = call_times
        self.closed = False

    def get(self, url: str, **kwargs: Any) -> _TrackingCM:
        return _TrackingCM(self.counter, self.call_times)

    async def close(self) -> None:
        self.closed = True


class _TrackingCM:
    def __init__(self, counter: list, call_times: list) -> None:
        self._counter = counter
        self._call_times = call_times
        self.status = 200
        self._resp = _MockResponse()

    async def __aenter__(self) -> _TrackingCM:
        self._counter[0] += 1
        if self._counter[0] > self._counter[1]:
            self._counter[1] = self._counter[0]
        self._call_times.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.02)
        return self._resp

    async def __aexit__(self, *args: Any) -> None:
        self._counter[0] -= 1


class FakeWSProtocol:
    """Async iterator that yields messages then raises OSError."""

    def __init__(self, messages: list[str], close_after: int, msg_interval: float = 0.05) -> None:
        self._messages = messages
        self._close_after = close_after
        self._msg_interval = msg_interval
        self._count = 0

    def __aiter__(self) -> FakeWSProtocol:
        return self

    async def __anext__(self) -> str:
        if self._count >= self._close_after:
            raise OSError("simulated disconnect")
        await asyncio.sleep(self._msg_interval)
        msg = self._messages[self._count % len(self._messages)]
        self._count += 1
        return msg


class FakeWSConnectFactory:
    """Callable that returns an async context manager wrapping FakeWSProtocol."""

    def __init__(self, messages: list[str], close_after: int, msg_interval: float = 0.05) -> None:
        self._messages = messages
        self._close_after = close_after
        self._msg_interval = msg_interval
        self.connect_count = 0

    def __call__(self, uri: str) -> _FakeWSConnectCM:
        self.connect_count += 1
        return _FakeWSConnectCM(self._messages, self._close_after, self._msg_interval)


class _FakeWSConnectCM:
    def __init__(self, messages: list[str], close_after: int, msg_interval: float) -> None:
        self._messages = messages
        self._close_after = close_after
        self._msg_interval = msg_interval

    async def __aenter__(self) -> FakeWSProtocol:
        return FakeWSProtocol(self._messages, self._close_after, self._msg_interval)

    async def __aexit__(self, *args: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Test A: heartbeat drift under 1000 qps flood
# ---------------------------------------------------------------------------

async def test_heartbeat_drift_under_1000_qps() -> None:
    HEARTBEAT_MS = 50
    DRIFT_LIMIT_MS = 30
    DURATION_S = 3.0

    queue: CoalescingQueue = CoalescingQueue(500)
    violations: list[float] = []
    stop_event = asyncio.Event()

    async def heartbeat() -> None:
        while not stop_event.is_set():
            t0 = asyncio.get_running_loop().time()
            await asyncio.sleep(HEARTBEAT_MS / 1000.0)
            elapsed_ms = (asyncio.get_running_loop().time() - t0) * 1000.0
            drift = elapsed_ms - HEARTBEAT_MS
            if drift > DRIFT_LIMIT_MS:
                violations.append(drift)

    async def flood_producer() -> None:
        counter = 0
        while not stop_event.is_set():
            for _ in range(10):
                symbol = f"SYM{counter % 200}"
                await queue.put(symbol, {"v": counter})
                counter += 1
            await asyncio.sleep(0)

    async def consumer() -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                pass

    hb_task = asyncio.get_running_loop().create_task(heartbeat())
    fp_task = asyncio.get_running_loop().create_task(flood_producer())
    cs_task = asyncio.get_running_loop().create_task(consumer())

    await asyncio.sleep(DURATION_S)
    stop_event.set()

    for task in (hb_task, fp_task, cs_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert len(violations) == 0, (
        f"Heartbeat drift exceeded {DRIFT_LIMIT_MS}ms on {len(violations)} occasions: {violations[:5]}"
    )


# ---------------------------------------------------------------------------
# Test B: rate limiter enforces semaphore and QPS
# ---------------------------------------------------------------------------

async def test_rate_limiter_enforces_semaphore_and_qps() -> None:
    SEMAPHORE_LIMIT = 3
    RATE = 20.0
    CAPACITY = 5.0
    N = 30

    counter = [0, 0]  # [current, peak]
    call_times: list[float] = []

    session = TrackingMockSession(counter, call_times)
    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    token_bucket = TokenBucket(RATE, CAPACITY)
    fetcher = RateLimitedFetcher(session, semaphore, token_bucket, max_retries=1)

    start = asyncio.get_running_loop().time()
    await asyncio.gather(*[fetcher.fetch("http://fake/url") for _ in range(N)])
    elapsed = asyncio.get_running_loop().time() - start

    peak = counter[1]
    assert peak <= SEMAPHORE_LIMIT, f"Peak concurrent {peak} exceeded semaphore limit {SEMAPHORE_LIMIT}"

    min_expected = (N - CAPACITY) / RATE * 0.9
    assert elapsed >= min_expected, (
        f"Elapsed {elapsed:.3f}s < expected {min_expected:.3f}s — token bucket not enforcing QPS"
    )


# ---------------------------------------------------------------------------
# Test C: soak reconnect and cleanup
# ---------------------------------------------------------------------------

async def test_soak_reconnect_and_cleanup() -> None:
    SOAK_SECONDS = 5
    CLOSE_AFTER_MSGS = 5

    messages = ['{"symbol": "AAPL", "price": 100}']
    ws_factory = FakeWSConnectFactory(messages=messages, close_after=CLOSE_AFTER_MSGS, msg_interval=0.1)

    class TrackedSession:
        def __init__(self) -> None:
            self.closed = False

        def get(self, url: str, **kwargs: Any) -> _MockResponse:
            return _MockResponse()

        async def close(self) -> None:
            self.closed = True

    mock_session = TrackedSession()

    service = CollectorService(
        ws_uri="ws://fake-host/stream",
        news_urls=["http://fake-news/feed"],
        ws_connect=ws_factory,
        session=mock_session,
        qps_rate=100.0,
        qps_capacity=100.0,
        news_interval=2.0,
    )

    await service.start()
    await asyncio.sleep(SOAK_SECONDS)
    await service.stop()
    await asyncio.sleep(0.2)

    assert len(service.task_set) == 0, (
        f"Ghost tasks remain after stop: {len(service.task_set)}"
    )
    assert mock_session.closed is False, "注入的 session 不應由 CollectorService 關閉（ownership 在呼叫方）"
    assert ws_factory.connect_count > 1, (
        f"Expected reconnects but connect_count={ws_factory.connect_count}"
    )

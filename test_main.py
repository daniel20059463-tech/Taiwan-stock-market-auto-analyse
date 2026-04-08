from __future__ import annotations

import asyncio
import multiprocessing
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from main import AppSupervisor, LifecycleState, SharedMemoryIPC, SupervisorConfig, create_supervisor_from_runtime


class FakeStateStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.ready = False

    async def start(self) -> None:
        self.events.append("state_store.start")
        self.ready = True

    async def wait_ready(self, timeout: float | None = None) -> bool:
        self.events.append("state_store.wait_ready")
        return self.ready

    async def stop(self) -> None:
        self.events.append("state_store.stop")


class FakeCollector:
    def __init__(self, events: list[str], *, pending_items: int = 1) -> None:
        self.events = events
        self.accepting = True
        self.started = False
        self.pending_items = pending_items

    async def start(self) -> None:
        self.events.append("collector.start")
        self.started = True

    async def stop_accepting(self) -> None:
        self.events.append("collector.stop_accepting")
        self.accepting = False
        self.pending_items = 0

    async def stop(self) -> None:
        self.events.append("collector.stop")
        self.started = False

    def pending_count(self) -> int:
        return self.pending_items


class FakeNotifier:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def start(self) -> None:
        self.events.append("notifier.start")

    async def stop(self) -> None:
        self.events.append("notifier.stop")


def analyzer_worker(stop_event: multiprocessing.synchronize.Event) -> None:
    while not stop_event.is_set():
        time.sleep(0.05)


class FakeAnalyzer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.ctx = multiprocessing.get_context("spawn")
        self.stop_event = self.ctx.Event()
        self.process: multiprocessing.Process | None = None

    def start(self, ipc: SharedMemoryIPC) -> None:
        self.events.append("analyzer.start")
        self.process = self.ctx.Process(target=analyzer_worker, args=(self.stop_event,))
        self.process.start()

    def is_alive(self) -> bool:
        return bool(self.process and self.process.is_alive())

    @property
    def exitcode(self) -> int | None:
        return None if self.process is None else self.process.exitcode

    def send_stop(self) -> None:
        self.events.append("analyzer.send_stop")
        self.stop_event.set()

    def join(self, timeout: float) -> None:
        self.events.append("analyzer.join")
        if self.process is not None:
            self.process.join(timeout)

    def terminate(self) -> None:
        self.events.append("analyzer.terminate")
        if self.process is not None and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=1)

    def crash(self) -> None:
        if self.process is not None and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=1)


async def wait_for_state(supervisor: AppSupervisor, target: LifecycleState, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if target in supervisor.state_history:
            return
        await asyncio.sleep(0.02)
    pytest.fail(f"state {target.value} not reached, history={supervisor.state_history}")


@pytest.mark.asyncio
async def test_normal_startup_and_graceful_shutdown() -> None:
    events: list[str] = []
    ipc = SharedMemoryIPC(size=64)
    supervisor = AppSupervisor(
        state_store=FakeStateStore(events),
        analyzer=FakeAnalyzer(events),
        collector=FakeCollector(events),
        notifier=FakeNotifier(events),
        ipc_manager=ipc,
        config=SupervisorConfig(
            sentinel_interval_seconds=0.05,
            drain_timeout_seconds=0.2,
            drain_poll_interval_seconds=0.01,
            analyzer_join_timeout_seconds=0.5,
        ),
    )

    try:
        await supervisor.start()
        assert supervisor.state is LifecycleState.RUNNING
        assert supervisor.trading_gate_open is True

        await supervisor.handle_interrupt("SIGINT")

        assert LifecycleState.DRAINING in supervisor.state_history
        assert supervisor.state is LifecycleState.STOPPED
        assert multiprocessing.active_children() == []
        assert ipc.cleaned is True
        assert events.index("state_store.wait_ready") < events.index("collector.start")
        assert events.index("analyzer.send_stop") < events.index("collector.stop")
    finally:
        if supervisor.state is not LifecycleState.STOPPED:
            await supervisor.shutdown(reason="test_cleanup")


@pytest.mark.asyncio
async def test_analyzer_crash_triggers_fail_closed_shutdown() -> None:
    events: list[str] = []
    analyzer = FakeAnalyzer(events)
    ipc = SharedMemoryIPC(size=64)
    supervisor = AppSupervisor(
        state_store=FakeStateStore(events),
        analyzer=analyzer,
        collector=FakeCollector(events),
        notifier=FakeNotifier(events),
        ipc_manager=ipc,
        config=SupervisorConfig(
            sentinel_interval_seconds=0.05,
            drain_timeout_seconds=0.2,
            drain_poll_interval_seconds=0.01,
            analyzer_join_timeout_seconds=0.2,
        ),
    )

    try:
        await supervisor.start()
        assert supervisor.state is LifecycleState.RUNNING

        analyzer.crash()
        await wait_for_state(supervisor, LifecycleState.FAILED)
        await wait_for_state(supervisor, LifecycleState.STOPPED)

        assert supervisor.failure_reason == "analyzer_worker_died"
        assert supervisor.trading_gate_open is False
        assert "collector.stop_accepting" in events
        assert ipc.cleaned is True
        assert multiprocessing.active_children() == []
    finally:
        if supervisor.state is not LifecycleState.STOPPED:
            await supervisor.shutdown(reason="test_cleanup")


@pytest.mark.asyncio
async def test_create_supervisor_from_runtime_uses_runtime_components() -> None:
    events: list[str] = []
    runtime = SimpleNamespace(
        state_store=FakeStateStore(events),
        analyzer=FakeAnalyzer(events),
        collector=FakeCollector(events),
        notifier=FakeNotifier(events),
        ipc_manager=SharedMemoryIPC(size=64),
    )

    supervisor = create_supervisor_from_runtime(
        runtime,
        config=SupervisorConfig(
            sentinel_interval_seconds=0.05,
            drain_timeout_seconds=0.2,
            drain_poll_interval_seconds=0.01,
            analyzer_join_timeout_seconds=0.2,
        ),
    )

    try:
        await supervisor.start()
        assert supervisor.state is LifecycleState.RUNNING
        await supervisor.handle_interrupt("SIGINT")
        assert supervisor.state is LifecycleState.STOPPED
    finally:
        if supervisor.state is not LifecycleState.STOPPED:
            await supervisor.shutdown(reason="test_cleanup")

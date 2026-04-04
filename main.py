from __future__ import annotations

import asyncio
import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum
from multiprocessing.shared_memory import SharedMemory
from typing import Any, Awaitable, Callable, Protocol


class LifecycleState(Enum):
    INIT = "INIT"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    STOPPING = "STOPPING"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class StateStoreLike(Protocol):
    async def start(self) -> None: ...
    async def wait_ready(self, timeout: float | None = None) -> bool: ...
    async def stop(self) -> None: ...


class CollectorLike(Protocol):
    async def start(self) -> None: ...
    async def stop_accepting(self) -> None: ...
    async def stop(self) -> None: ...
    def pending_count(self) -> int: ...


class NotifierLike(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class IPCResourceLike(Protocol):
    async def start(self) -> None: ...
    async def cleanup(self) -> None: ...
    @property
    def ready(self) -> bool: ...


class AnalyzerLike(Protocol):
    def start(self, ipc: IPCResourceLike) -> None: ...
    def is_alive(self) -> bool: ...
    @property
    def exitcode(self) -> int | None: ...
    def send_stop(self) -> None: ...
    def join(self, timeout: float) -> None: ...
    def terminate(self) -> None: ...


@dataclass(slots=True)
class SupervisorConfig:
    sentinel_interval_seconds: float = 1.0
    drain_timeout_seconds: float = 3.0
    drain_poll_interval_seconds: float = 0.05
    analyzer_join_timeout_seconds: float = 3.0
    ipc_shared_memory_size: int = 1024


class SharedMemoryIPC:
    def __init__(self, *, size: int = 1024, name: str | None = None) -> None:
        self.size = size
        self.name = name
        self.shared_memory: SharedMemory | None = None
        self._cleaned = False

    @property
    def ready(self) -> bool:
        return self.shared_memory is not None

    @property
    def cleaned(self) -> bool:
        return self._cleaned

    async def start(self) -> None:
        if self.shared_memory is None:
            self.shared_memory = SharedMemory(create=True, size=self.size, name=self.name)

    async def cleanup(self) -> None:
        shm = self.shared_memory
        self.shared_memory = None
        if shm is None:
            self._cleaned = True
            return

        try:
            shm.close()
        finally:
            try:
                shm.unlink()
            except FileNotFoundError:
                pass
            self._cleaned = True


async def noop_preflight() -> None:
    return None


class AppSupervisor:
    def __init__(
        self,
        *,
        state_store: StateStoreLike,
        analyzer: AnalyzerLike,
        collector: CollectorLike,
        notifier: NotifierLike,
        ipc_manager: IPCResourceLike | None = None,
        preflight: Callable[[], Awaitable[None]] | None = None,
        config: SupervisorConfig | None = None,
    ) -> None:
        self.state_store = state_store
        self.analyzer = analyzer
        self.collector = collector
        self.notifier = notifier
        self.ipc_manager = ipc_manager or SharedMemoryIPC()
        self.preflight = preflight or noop_preflight
        self.config = config or SupervisorConfig()

        self.state = LifecycleState.INIT
        self.state_history: list[LifecycleState] = [self.state]
        self.trading_gate_open = False
        self.failure_reason: str | None = None

        self._sentinel_task: asyncio.Task[None] | None = None
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_complete = asyncio.Event()
        self._interrupt_count = 0
        self._notifier_started = False
        self._collector_started = False
        self._signals_installed = False

    async def start(self) -> None:
        if self.state is not LifecycleState.INIT:
            raise RuntimeError(f"cannot start from state {self.state.value}")

        self._set_state(LifecycleState.STARTING)
        try:
            await self.preflight()
            await self.state_store.start()

            ready = await self.state_store.wait_ready(timeout=self.config.drain_timeout_seconds)
            if not ready:
                raise RuntimeError("state store did not become ready")

            await self.ipc_manager.start()
            if not self.ipc_manager.ready:
                raise RuntimeError("ipc/shared memory did not initialize")

            self.analyzer.start(self.ipc_manager)
            if not self.analyzer.is_alive():
                raise RuntimeError("analyzer worker failed during startup")

            await self.collector.start()
            self._collector_started = True

            try:
                await self.notifier.start()
                self._notifier_started = True
            except Exception:
                self._notifier_started = False

            self.trading_gate_open = True
            self._set_state(LifecycleState.RUNNING)
            self._sentinel_task = asyncio.create_task(self._sentinel_loop(), name="analyzer-sentinel")
        except Exception as exc:
            await self.fail_closed(f"startup_failure:{exc}")
            raise

    async def run(self) -> LifecycleState:
        self.install_signal_handlers()
        try:
            await self.start()
            await self._shutdown_complete.wait()
        except KeyboardInterrupt:
            await self.handle_interrupt("KeyboardInterrupt")
        return self.state

    def install_signal_handlers(self) -> None:
        if self._signals_installed:
            return

        loop = asyncio.get_running_loop()
        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, lambda name=sig_name: asyncio.create_task(self.handle_interrupt(name)))
            except (NotImplementedError, RuntimeError):
                continue
        self._signals_installed = True

    async def handle_interrupt(self, signal_name: str = "SIGINT") -> None:
        self._interrupt_count += 1
        if self._interrupt_count >= 2:
            raise SystemExit(1)

        await self.shutdown(reason=f"interrupt:{signal_name}")

    async def fail_closed(self, reason: str) -> None:
        if self.state in {LifecycleState.STOPPING, LifecycleState.STOPPED}:
            return

        self.failure_reason = reason
        self.trading_gate_open = False
        self._set_state(LifecycleState.FAILED)
        if self._collector_started:
            await self.collector.stop_accepting()
        await self.shutdown(reason=reason, from_failure=True)

    async def shutdown(self, *, reason: str = "shutdown", from_failure: bool = False) -> None:
        async with self._shutdown_lock:
            if self._shutdown_complete.is_set():
                return

            if not from_failure and self.state not in {LifecycleState.DRAINING, LifecycleState.STOPPING, LifecycleState.FAILED}:
                self._set_state(LifecycleState.DRAINING)
            elif self.state not in {LifecycleState.FAILED, LifecycleState.DRAINING, LifecycleState.STOPPING}:
                self._set_state(LifecycleState.DRAINING)

            self.trading_gate_open = False
            if self._collector_started:
                await self.collector.stop_accepting()

            await self._drain_collector_queue()
            self._set_state(LifecycleState.STOPPING)

            await self._cancel_background_tasks()
            if self._notifier_started:
                await self._safe_async_call(self.notifier.stop)

            await self._stop_analyzer()
            if self._collector_started:
                await self._safe_async_call(self.collector.stop)
            await self._safe_async_call(self.state_store.stop)
            await self.ipc_manager.cleanup()

            self._set_state(LifecycleState.STOPPED)
            self._shutdown_complete.set()

    async def _sentinel_loop(self) -> None:
        try:
            while self.state in {LifecycleState.RUNNING, LifecycleState.DRAINING}:
                await asyncio.sleep(self.config.sentinel_interval_seconds)
                if self.state is not LifecycleState.RUNNING:
                    continue

                if not self.analyzer.is_alive() or self.analyzer.exitcode not in (None, 0):
                    await self.fail_closed("analyzer_worker_died")
                    return
        except asyncio.CancelledError:
            return

    async def _drain_collector_queue(self) -> None:
        deadline = time.monotonic() + self.config.drain_timeout_seconds
        while time.monotonic() < deadline:
            if self.collector.pending_count() == 0:
                return
            await asyncio.sleep(self.config.drain_poll_interval_seconds)

    async def _cancel_background_tasks(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in (self._sentinel_task,) if task is not None and task is not current and not task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _stop_analyzer(self) -> None:
        self.analyzer.send_stop()
        self.analyzer.join(self.config.analyzer_join_timeout_seconds)
        if self.analyzer.is_alive():
            self.analyzer.terminate()

    async def _safe_async_call(self, func: Callable[[], Awaitable[Any]]) -> None:
        try:
            await func()
        except Exception:
            return

    def _set_state(self, new_state: LifecycleState) -> None:
        if self.state is new_state:
            return
        self.state = new_state
        self.state_history.append(new_state)


def main() -> int:
    print("AppSupervisor is designed for dependency-injected startup. Instantiate AppSupervisor in your runtime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

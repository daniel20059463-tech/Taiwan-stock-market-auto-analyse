import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketDataProvider } from "./MarketDataProvider";
import { useMarketStore } from "../store";
import type { WorkerOutboundMessage } from "../types/market";

const mockDesktopBridge = vi.hoisted(() => ({
  getBackendStatus: vi.fn(),
  isDesktopRuntime: vi.fn(),
  restartBackend: vi.fn(),
}));

const mockDesktopUpdater = vi.hoisted(() => ({
  checkForDesktopUpdate: vi.fn(),
  installDesktopUpdate: vi.fn(),
}));

vi.mock("../desktopBridge", () => mockDesktopBridge);
vi.mock("../desktopUpdater", () => mockDesktopUpdater);

class WorkerMock {
  static instances: WorkerMock[] = [];

  messages: unknown[] = [];
  terminated = false;
  listeners = new Map<string, EventListener>();

  constructor(public readonly url: URL | string) {
    WorkerMock.instances.push(this);
  }

  postMessage(message: unknown): void {
    this.messages.push(message);
  }

  terminate(): void {
    this.terminated = true;
  }

  addEventListener(type: string, listener: EventListener): void {
    this.listeners.set(type, listener);
  }

  removeEventListener(type: string): void {
    this.listeners.delete(type);
  }

  dispatchMessage(message: WorkerOutboundMessage): void {
    const listener = this.listeners.get("message");
    listener?.({ data: message } as unknown as Event);
  }
}

describe("MarketDataProvider", () => {
  beforeEach(() => {
    WorkerMock.instances = [];
    vi.stubGlobal("Worker", WorkerMock);
    vi.useFakeTimers();
    mockDesktopBridge.getBackendStatus.mockReset();
    mockDesktopBridge.getBackendStatus.mockResolvedValue({ phase: "idle", updatedAt: 1 });
    mockDesktopBridge.isDesktopRuntime.mockReset();
    mockDesktopBridge.restartBackend.mockReset();
    mockDesktopUpdater.checkForDesktopUpdate.mockReset();
    mockDesktopUpdater.checkForDesktopUpdate.mockResolvedValue({ status: "upToDate" });
    useMarketStore.setState({
      connectionState: "idle",
      snapshot: null,
      ticks: new Map(),
      portfolio: null,
      replayTrades: [],
      selectedSymbol: "",
      historyCache: new Map(),
      sessionCache: new Map(),
      historyLoadingSymbol: null,
      sessionLoadingSymbol: null,
      desktopRuntimeAvailable: false,
      desktopBackendStatus: { phase: "idle" },
      desktopBackendRetrying: false,
      desktopUpdate: { status: "idle" },
    });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("creates one worker, sends INIT, and stops it on unmount", () => {
    mockDesktopBridge.isDesktopRuntime.mockReturnValue(false);

    const { unmount } = render(
      <MarketDataProvider
        workerUrl="ws://127.0.0.1:8765"
        symbols={["2330", "2317"]}
        instruments={[]}
      >
        <div>market</div>
      </MarketDataProvider>,
    );

    expect(WorkerMock.instances).toHaveLength(1);
    expect(WorkerMock.instances[0].messages[0]).toMatchObject({
      type: "INIT",
      url: "ws://127.0.0.1:8765",
      symbols: ["2330", "2317"],
    });

    unmount();

    expect(WorkerMock.instances[0].messages.at(-1)).toEqual({ type: "STOP" });
    expect(WorkerMock.instances[0].terminated).toBe(true);
  });

  it("does not crash outside desktop runtime and keeps idle desktop status", () => {
    mockDesktopBridge.isDesktopRuntime.mockReturnValue(false);

    const { unmount } = render(
      <MarketDataProvider workerUrl="ws://127.0.0.1:8765" symbols={["2330"]} instruments={[]}>
        <div>market</div>
      </MarketDataProvider>,
    );

    expect(WorkerMock.instances).toHaveLength(1);
    expect(mockDesktopBridge.getBackendStatus).not.toHaveBeenCalled();
    expect(mockDesktopUpdater.checkForDesktopUpdate).not.toHaveBeenCalled();
    expect(useMarketStore.getState().desktopRuntimeAvailable).toBe(false);
    expect(useMarketStore.getState().desktopBackendStatus.phase).toBe("idle");
    expect(useMarketStore.getState().desktopUpdate.status).toBe("idle");

    unmount();
  });

  it("polls desktop backend status and updates retry flow in store", async () => {
    mockDesktopBridge.isDesktopRuntime.mockReturnValue(true);
    mockDesktopBridge.getBackendStatus
      .mockResolvedValueOnce({ phase: "starting", detail: "booting" })
      .mockResolvedValueOnce({ phase: "running", detail: "ready" });

    render(
      <MarketDataProvider workerUrl="ws://127.0.0.1:8765" symbols={["2330"]} instruments={[]}>
        <div>market</div>
      </MarketDataProvider>,
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(useMarketStore.getState().desktopBackendStatus.phase).toBe("starting");
    expect(mockDesktopUpdater.checkForDesktopUpdate).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(5_000);
      await Promise.resolve();
    });

    expect(useMarketStore.getState().desktopBackendStatus.phase).toBe("running");
  });

  it("clears history loading when a HISTORY message arrives", async () => {
    mockDesktopBridge.isDesktopRuntime.mockReturnValue(false);
    useMarketStore.getState().setHistoryLoadingSymbol("2330");

    render(
      <MarketDataProvider workerUrl="ws://127.0.0.1:8765" symbols={["2330"]} instruments={[]}>
        <div>market</div>
      </MarketDataProvider>,
    );

    await act(async () => {
      WorkerMock.instances[0].dispatchMessage({
        type: "HISTORY",
        symbol: "2330",
        candles: [],
        source: "fallback",
      });
    });

    expect(useMarketStore.getState().historyLoadingSymbol).toBeNull();
  });

  it("ignores stale poll results after a newer status update is already in store", async () => {
    mockDesktopBridge.isDesktopRuntime.mockReturnValue(true);

    let resolveFirstPoll: ((value: { phase: "error"; detail: string }) => void) | undefined;
    mockDesktopBridge.getBackendStatus
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirstPoll = resolve;
          }),
      )
      .mockResolvedValueOnce({ phase: "running", detail: "healthy" });

    render(
      <MarketDataProvider workerUrl="ws://127.0.0.1:8765" symbols={["2330"]} instruments={[]}>
        <div>market</div>
      </MarketDataProvider>,
    );

    useMarketStore.getState().setDesktopBackendStatus({
      phase: "starting",
      detail: "manual retry",
      updatedAt: Date.now() + 100,
    });

    await act(async () => {
      resolveFirstPoll?.({ phase: "error", detail: "stale failure" });
      await Promise.resolve();
    });

    expect(useMarketStore.getState().desktopBackendStatus.phase).toBe("starting");
    expect(useMarketStore.getState().desktopBackendStatus.detail).toBe("manual retry");

    await act(async () => {
      vi.advanceTimersByTime(5_000);
      await Promise.resolve();
    });

    expect(useMarketStore.getState().desktopBackendStatus.phase).toBe("running");
    expect(useMarketStore.getState().desktopBackendStatus.detail).toBe("healthy");
  });

  it("checks desktop updates once on startup in desktop runtime", async () => {
    mockDesktopBridge.isDesktopRuntime.mockReturnValue(true);
    mockDesktopUpdater.checkForDesktopUpdate.mockResolvedValue({
      status: "available",
      currentVersion: "0.1.0",
      availableVersion: "0.1.1",
    });

    render(
      <MarketDataProvider workerUrl="ws://127.0.0.1:8765" symbols={["2330"]} instruments={[]}>
        <div>market</div>
      </MarketDataProvider>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockDesktopUpdater.checkForDesktopUpdate).toHaveBeenCalledTimes(1);
    expect(useMarketStore.getState().desktopUpdate.status).toBe("available");
    expect(useMarketStore.getState().desktopUpdate.availableVersion).toBe("0.1.1");
  });
});

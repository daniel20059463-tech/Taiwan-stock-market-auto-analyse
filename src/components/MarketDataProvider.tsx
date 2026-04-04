/**
 * MarketDataProvider.tsx — 全站 Worker 生命週期管理
 *
 * 職責：
 *   - 在應用程式根層啟動唯一的 WebSocket Worker
 *   - 將所有 Worker 訊息寫入 Zustand store（各頁面直接讀取）
 *   - 透過 workerBridge 暴露 postWorkerMessage() 供任意元件傳送訊息
 *   - 元件卸載時自動停止 Worker 並釋放資源
 */

import { startTransition, useEffect, type ReactNode } from "react";
import { getBackendStatus, isDesktopRuntime } from "../desktopBridge";
import { checkForDesktopUpdate } from "../desktopUpdater";
import { useMarketStore } from "../store";
import { bindWorker, postWorkerMessage } from "../workerBridge";
import type {
  InstrumentDefinition,
  WorkerInboundMessage,
  WorkerOutboundMessage,
} from "../types/market";

interface MarketDataProviderProps {
  workerUrl: string;
  symbols: string[];
  instruments?: InstrumentDefinition[];
  children: ReactNode;
}

export function MarketDataProvider({
  workerUrl,
  symbols,
  instruments = [],
  children,
}: MarketDataProviderProps) {
  const setConnectionState  = useMarketStore((s) => s.setConnectionState);
  const setSnapshot         = useMarketStore((s) => s.setSnapshot);
  const applyTick           = useMarketStore((s) => s.applyTick);
  const setPortfolio        = useMarketStore((s) => s.setPortfolio);
  const setHistoryEntry     = useMarketStore((s) => s.setHistoryEntry);
  const setSessionEntry     = useMarketStore((s) => s.setSessionEntry);
  const setHistoryLoading   = useMarketStore((s) => s.setHistoryLoadingSymbol);
  const setSessionLoading   = useMarketStore((s) => s.setSessionLoadingSymbol);
  const setDesktopRuntimeAvailable = useMarketStore((s) => s.setDesktopRuntimeAvailable);
  const setDesktopBackendStatus = useMarketStore((s) => s.setDesktopBackendStatus);
  const setDesktopUpdate = useMarketStore((s) => s.setDesktopUpdate);

  const symbolsKey     = symbols.join("|");
  const instrumentsKey = instruments.map((i) => i.symbol).join("|");

  useEffect(() => {
    const worker = new Worker(
      new URL("../workers/data.worker.ts", import.meta.url),
      { type: "module" },
    );
    bindWorker(worker);

    const handleMessage = (event: MessageEvent<WorkerOutboundMessage>) => {
      const msg = event.data;

      // 高頻 tick — 直接寫入 store，不觸發整棵元件樹 re-render
      if (msg.type === "TICK_DELTA") {
        applyTick(msg);
        return;
      }

      if (msg.type === "STATUS") {
        setConnectionState(msg.connectionState);
        return;
      }

      if (msg.type === "HISTORY") {
        setHistoryEntry(msg.symbol, {
          candles: msg.candles,
          source: (msg.source as string) === "twse" ? "fallback" : (msg.source as "sinopac" | "fallback"),
          error: msg.error,
        });
        setHistoryLoading(null);
        return;
      }

      if (msg.type === "SESSION") {
        setSessionEntry(msg.symbol, {
          candles: msg.candles,
          source: msg.source,
          error: msg.error,
        });
        setSessionLoading(null);
        return;
      }

      if (msg.type === "PAPER_PORTFOLIO") {
        startTransition(() => setPortfolio(msg));
        return;
      }

      // SNAPSHOT — 低頻全量更新，發 ACK 給 Worker 繼續下一批
      postWorkerMessage({
        type: "ACK",
        snapshotId: msg.snapshot.snapshotId,
      } satisfies WorkerInboundMessage);

      startTransition(() => {
        setConnectionState(msg.snapshot.connectionState);
        setSnapshot(msg.snapshot);
      });
    };

    worker.addEventListener("message", handleMessage);

    // Worker 初始化
    worker.postMessage({
      type: "INIT",
      url: workerUrl,
      symbols,
      instruments,
      candleLimit: 240,
      flushIntervalMs: 250,
      reconnectBaseMs: 600,
      reconnectMaxMs: 8_000,
      candleResolutionMs: 60_000,
    } satisfies WorkerInboundMessage);

    return () => {
      worker.removeEventListener("message", handleMessage);
      worker.postMessage({ type: "STOP" } satisfies WorkerInboundMessage);
      worker.terminate();
      bindWorker(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey, instrumentsKey, workerUrl]);

  useEffect(() => {
    const desktopRuntime = isDesktopRuntime();
    setDesktopRuntimeAvailable(desktopRuntime);

    if (!desktopRuntime) {
      setDesktopBackendStatus({ phase: "idle", updatedAt: Date.now() });
      setDesktopUpdate({ status: "idle" });
      return;
    }

    let active = true;
    let timer: number | undefined;
    let pollInFlight = false;
    let latestPollStartedAt = 0;

    const syncDesktopBackendStatus = async () => {
      if (pollInFlight) {
        return;
      }

      pollInFlight = true;
      const startedAt = Date.now();
      latestPollStartedAt = startedAt;

      try {
        const status = await getBackendStatus();
        if (!active) {
          return;
        }

        const currentStatus = useMarketStore.getState().desktopBackendStatus;
        if ((currentStatus.updatedAt ?? 0) > startedAt || latestPollStartedAt !== startedAt) {
          return;
        }

        setDesktopBackendStatus({
          ...status,
          updatedAt: status.updatedAt ?? Date.now(),
        });
      } finally {
        pollInFlight = false;
      }
    };

    void syncDesktopBackendStatus();
    timer = window.setInterval(() => {
      void syncDesktopBackendStatus();
    }, 5_000);

    return () => {
      active = false;
      if (timer !== undefined) {
        window.clearInterval(timer);
      }
    };
  }, [setDesktopBackendStatus, setDesktopRuntimeAvailable, setDesktopUpdate]);

  useEffect(() => {
    if (!isDesktopRuntime()) {
      return;
    }

    let active = true;
    setDesktopUpdate({ status: "checking" });

    void checkForDesktopUpdate().then((state) => {
      if (!active) {
        return;
      }

      setDesktopUpdate(state);
    });

    return () => {
      active = false;
    };
  }, [setDesktopUpdate]);

  return <>{children}</>;
}

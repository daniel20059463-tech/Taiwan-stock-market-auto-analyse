import { startTransition, useEffect, type ReactNode } from "react";
import { getBackendStatus, isDesktopRuntime } from "../desktopBridge";
import { checkForDesktopUpdate } from "../desktopUpdater";
import { useMarketStore } from "../store";
import type { NewsFeed } from "../store";
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
  const setConnectionState = useMarketStore((state) => state.setConnectionState);
  const setSnapshot = useMarketStore((state) => state.setSnapshot);
  const applyTick = useMarketStore((state) => state.applyTick);
  const setPortfolio = useMarketStore((state) => state.setPortfolio);
  const setHistoryEntry = useMarketStore((state) => state.setHistoryEntry);
  const setSessionEntry = useMarketStore((state) => state.setSessionEntry);
  const setHistoryLoading = useMarketStore((state) => state.setHistoryLoadingSymbol);
  const setSessionLoading = useMarketStore((state) => state.setSessionLoadingSymbol);
  const setOrderBook = useMarketStore((state) => state.setOrderBook);
  const setTradeTape = useMarketStore((state) => state.setTradeTape);
  const setDesktopRuntimeAvailable = useMarketStore((state) => state.setDesktopRuntimeAvailable);
  const setDesktopBackendStatus = useMarketStore((state) => state.setDesktopBackendStatus);
  const setDesktopUpdate = useMarketStore((state) => state.setDesktopUpdate);
  const setNewsFeed = useMarketStore((state) => state.setNewsFeed);

  const symbolsKey = symbols.join("|");
  const instrumentsKey = instruments.map((item) => item.symbol).join("|");

  useEffect(() => {
    const worker = new Worker(new URL("../workers/data.worker.ts", import.meta.url), {
      type: "module",
    });
    bindWorker(worker);

    const handleMessage = (event: MessageEvent<WorkerOutboundMessage>) => {
      const message = event.data;

      if (message.type === "TICK_DELTA") {
        applyTick(message);
        return;
      }

      if (message.type === "STATUS") {
        setConnectionState(message.connectionState);
        return;
      }

      if (message.type === "HISTORY") {
        setHistoryEntry(message.symbol, {
          candles: message.candles,
          source: (message.source as string) === "twse" ? "fallback" : message.source,
          error: message.error,
        });
        setHistoryLoading(null);
        return;
      }

      if (message.type === "SESSION") {
        setSessionEntry(message.symbol, {
          candles: message.candles,
          source: message.source,
          error: message.error,
        });
        setSessionLoading(null);
        return;
      }

      if (message.type === "PAPER_PORTFOLIO") {
        startTransition(() => setPortfolio(message));
        return;
      }

      if (message.type === "ORDER_BOOK_SNAPSHOT") {
        setOrderBook({
          symbol: message.symbol,
          timestamp: message.timestamp,
          asks: message.asks,
          bids: message.bids,
        });
        return;
      }

      if (message.type === "TRADE_TAPE_SNAPSHOT") {
        setTradeTape({
          symbol: message.symbol,
          timestamp: message.timestamp,
          rows: message.rows,
        });
        return;
      }

      if ((message as { type: string }).type === "INTERNATIONAL_NEWS") {
        const raw = message as unknown as NewsFeed & { type: string };
        setNewsFeed({ updatedAt: raw.updatedAt, items: raw.items });
        return;
      }

      postWorkerMessage({
        type: "ACK",
        snapshotId: message.snapshot.snapshotId,
      } satisfies WorkerInboundMessage);

      startTransition(() => {
        setConnectionState(message.snapshot.connectionState);
        setSnapshot(message.snapshot);
      });
    };

    worker.addEventListener("message", handleMessage);
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
  }, [
    applyTick,
    instruments,
    instrumentsKey,
    setConnectionState,
    setHistoryEntry,
    setHistoryLoading,
    setOrderBook,
    setPortfolio,
    setSessionEntry,
    setSessionLoading,
    setSnapshot,
    setTradeTape,
    symbols,
    symbolsKey,
    workerUrl,
  ]);

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

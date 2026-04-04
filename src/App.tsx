import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { restartBackend } from "./desktopBridge";
import { installDesktopUpdate } from "./desktopUpdater";
import { AppShell } from "./components/AppShell";
import { DesktopBackendBanner } from "./components/DesktopBackendBanner";
import { DesktopUpdateBanner } from "./components/DesktopUpdateBanner";
import Dashboard from "./components/Dashboard";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { MarketDataProvider } from "./components/MarketDataProvider";
import { CORE_TW_SYMBOLS, DEFAULT_TW_STOCKS } from "./data/twStocks";
import { Performance } from "./pages/Performance";
import { StrategyConfig } from "./pages/StrategyConfig";
import { StrategyWorkbench } from "./pages/StrategyWorkbench";
import { TradeReplay } from "./pages/TradeReplay";
import {
  useDesktopBackendRetrying,
  useDesktopBackendStatus,
  useDesktopRuntimeAvailable,
  useDesktopUpdateState,
  useMarketStore,
} from "./store";
import type { DesktopBackendStatus, DesktopUpdateState } from "./types/desktop";

const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://127.0.0.1:8765";

const rawSymbols =
  typeof import.meta.env.VITE_SYMBOLS === "string"
    ? import.meta.env.VITE_SYMBOLS.trim()
    : "";

const SYMBOLS = (rawSymbols || CORE_TW_SYMBOLS.join(","))
  .split(",")
  .map((symbol: string) => symbol.trim())
  .filter(Boolean);

const INSTRUMENTS = DEFAULT_TW_STOCKS;

function DesktopBackendBannerSlot() {
  const desktopRuntimeAvailable = useDesktopRuntimeAvailable();
  const status = useDesktopBackendStatus();
  const isRetrying = useDesktopBackendRetrying();
  const setDesktopBackendRetrying = useMarketStore((state) => state.setDesktopBackendRetrying);
  const setDesktopBackendStatus = useMarketStore((state) => state.setDesktopBackendStatus);

  const handleRetry = async () => {
    setDesktopBackendRetrying(true);
    setDesktopBackendStatus({
      phase: "starting",
      detail: "正在重新啟動桌面後端…",
      updatedAt: Date.now(),
    } satisfies DesktopBackendStatus);

    try {
      const nextStatus = await restartBackend();
      setDesktopBackendStatus({
        ...nextStatus,
        updatedAt: nextStatus.updatedAt ?? Date.now(),
      });
    } finally {
      setDesktopBackendRetrying(false);
    }
  };

  if (!desktopRuntimeAvailable) {
    return null;
  }

  return (
    <DesktopBackendBanner
      status={status}
      isRetrying={isRetrying}
      onRetry={() => void handleRetry()}
    />
  );
}

function DesktopUpdateBannerSlot() {
  const desktopRuntimeAvailable = useDesktopRuntimeAvailable();
  const updateState = useDesktopUpdateState();
  const setDesktopUpdate = useMarketStore((state) => state.setDesktopUpdate);
  const dismissDesktopUpdate = useMarketStore((state) => state.dismissDesktopUpdate);
  const [isUpdating, setIsUpdating] = useState(false);

  const handleUpdateNow = async () => {
    setIsUpdating(true);
    setDesktopUpdate({
      ...updateState,
      status: "downloading",
      message: "正在下載更新…",
    } satisfies DesktopUpdateState);

    try {
      const nextState = await installDesktopUpdate();
      setDesktopUpdate(nextState);
    } finally {
      setIsUpdating(false);
    }
  };

  if (!desktopRuntimeAvailable) {
    return null;
  }

  return (
    <DesktopUpdateBanner
      state={updateState}
      isUpdating={isUpdating}
      onUpdateNow={() => void handleUpdateNow()}
      onDismiss={dismissDesktopUpdate}
    />
  );
}

export function App() {
  return (
    <ErrorBoundary label="台股模擬交易主畫面">
      <BrowserRouter>
        <MarketDataProvider workerUrl={WS_URL} symbols={SYMBOLS} instruments={INSTRUMENTS}>
          <AppShell
            topBanner={
              <>
                <DesktopUpdateBannerSlot />
                <DesktopBackendBannerSlot />
              </>
            }
          >
            <Routes>
              <Route
                path="/"
                element={
                  <ErrorBoundary label="即時總覽">
                    <Dashboard
                      symbols={SYMBOLS}
                      instruments={INSTRUMENTS}
                      title="台股模擬交易雷達"
                    />
                  </ErrorBoundary>
                }
              />
              <Route
                path="/strategy"
                element={
                  <ErrorBoundary label="策略作戰台">
                    <StrategyWorkbench />
                  </ErrorBoundary>
                }
              />
              <Route
                path="/replay"
                element={
                  <ErrorBoundary label="交易回放">
                    <TradeReplay />
                  </ErrorBoundary>
                }
              />
              <Route
                path="/performance"
                element={
                  <ErrorBoundary label="績效分析">
                    <Performance />
                  </ErrorBoundary>
                }
              />
              <Route
                path="/config"
                element={
                  <ErrorBoundary label="策略設定">
                    <StrategyConfig />
                  </ErrorBoundary>
                }
              />
            </Routes>
          </AppShell>
        </MarketDataProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

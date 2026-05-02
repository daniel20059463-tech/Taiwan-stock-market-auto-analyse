/**
 * store.ts — Zustand 全域狀態管理
 *
 * 架構原則：
 *   - 只有「真正需要顯示該資料的最小元件」透過 selector 訂閱，其他元件不 re-render。
 *   - Worker 傳回的高頻 tick 寫入 store 後，只有訂閱到對應 symbol 的元件才更新。
 *   - 圖表系列（lightweight-charts）完全不走 React state，只走 useRef + 指令式 update。
 *   - historyCache / sessionCache 統一存在 store，MarketDataProvider 寫入，各頁面讀取。
 */

import { create } from "zustand";
import type { DesktopBackendStatus, DesktopUpdateState } from "./types/desktop";
import type {
  AggregatedSnapshot,
  ConnectionState,
  DecisionReport,
  HistoryCacheEntry,
  OrderBookLevel,
  PaperPortfolio,
  PaperTrade,
  SymbolSnapshot,
  TradeTapeRow,
} from "./types/market";

// ── 單筆即時 Tick delta（從 Worker 的 TICK_DELTA 訊息來）────────────────────
export interface TickDelta {
  symbol: string;
  price: number;
  changePct: number;
  volume: number;
  turnover: number;
  high: number;
  low: number;
  ts: number;
  activeCandle: {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  } | null;
}

export interface OrderBookSnapshot {
  symbol: string;
  timestamp: number;
  asks: OrderBookLevel[];
  bids: OrderBookLevel[];
}

export interface TradeTapeSnapshot {
  symbol: string;
  timestamp: number;
  rows: TradeTapeRow[];
}

// ── 國際新聞 ──────────────────────────────────────────────────────────────────

export interface NewsItem {
  title: string;
  summary: string;
  source: string;
  url: string;
  published_at: string;
}

export interface NewsFeed {
  updatedAt: string;
  items: NewsItem[];
}

// ── Store 型別定義 ────────────────────────────────────────────────────────────

interface MarketState {
  // 連線狀態
  connectionState: ConnectionState;
  setConnectionState: (state: ConnectionState, reason?: string) => void;

  // 全量快照（250 ms 一次，用於清單排序/篩選）
  snapshot: AggregatedSnapshot | null;
  setSnapshot: (snapshot: AggregatedSnapshot) => void;

  // 精準 tick 更新（每筆 tick 一次，僅更新指定 symbol）
  ticks: Map<string, TickDelta>;
  applyTick: (delta: TickDelta) => void;

  // 模擬交易帳本
  portfolio: PaperPortfolio | null;
  setPortfolio: (portfolio: PaperPortfolio) => void;
  replayTrades: PaperTrade[];
  replayDecisions: DecisionReport[];
  appendReplayTrades: (trades: PaperTrade[]) => void;

  // UI 狀態（跨頁面共用）
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;

  // K 棒快取（由 MarketDataProvider 寫入，各頁面讀取）
  historyCache: Map<string, HistoryCacheEntry>;
  sessionCache: Map<string, HistoryCacheEntry>;
  historyLoadingSymbol: string | null;
  sessionLoadingSymbol: string | null;
  setHistoryEntry: (symbol: string, entry: HistoryCacheEntry) => void;
  setSessionEntry: (symbol: string, entry: HistoryCacheEntry) => void;
  setHistoryLoadingSymbol: (symbol: string | null) => void;
  setSessionLoadingSymbol: (symbol: string | null) => void;

  orderBooks: Map<string, OrderBookSnapshot>;
  tradeTapes: Map<string, TradeTapeSnapshot>;
  setOrderBook: (snapshot: OrderBookSnapshot) => void;
  setTradeTape: (snapshot: TradeTapeSnapshot) => void;

  newsFeed: NewsFeed | null;
  setNewsFeed: (feed: NewsFeed) => void;

  desktopRuntimeAvailable: boolean;
  setDesktopRuntimeAvailable: (available: boolean) => void;
  desktopBackendStatus: DesktopBackendStatus;
  setDesktopBackendStatus: (status: DesktopBackendStatus) => void;
  desktopBackendRetrying: boolean;
  setDesktopBackendRetrying: (retrying: boolean) => void;
  desktopUpdate: DesktopUpdateState;
  setDesktopUpdate: (state: DesktopUpdateState) => void;
  dismissDesktopUpdate: () => void;
}

const REPLAY_STORAGE_KEY = "taiwan-alpha-radar.replay-trades";
const DECISION_STORAGE_KEY = "taiwan-alpha-radar.replay-decisions";
const MAX_REPLAY_TRADES = 500;
const MAX_REPLAY_DECISIONS = 500;

function hasWindowStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function isPaperTrade(value: unknown): value is PaperTrade {
  if (!value || typeof value !== "object") {
    return false;
  }
  const trade = value as Record<string, unknown>;
  return (
    typeof trade.symbol === "string" &&
    (trade.action === "BUY" ||
      trade.action === "SELL" ||
      trade.action === "SHORT" ||
      trade.action === "COVER") &&
    typeof trade.price === "number" &&
    typeof trade.shares === "number" &&
    typeof trade.reason === "string" &&
    typeof trade.netPnl === "number" &&
    typeof trade.grossPnl === "number" &&
    typeof trade.ts === "number"
  );
}

function readReplayTrades(): PaperTrade[] {
  if (!hasWindowStorage()) {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(REPLAY_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isPaperTrade) : [];
  } catch {
    return [];
  }
}

function isDecisionFactor(value: unknown): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  const factor = value as Record<string, unknown>;
  return (
    (factor.kind === "support" || factor.kind === "oppose") &&
    typeof factor.label === "string" &&
    typeof factor.detail === "string"
  );
}

function isDecisionReport(value: unknown): value is DecisionReport {
  if (!value || typeof value !== "object") {
    return false;
  }
  const report = value as Record<string, unknown>;
  return (
    typeof report.reportId === "string" &&
    typeof report.symbol === "string" &&
    typeof report.ts === "number" &&
    typeof report.decisionType === "string" &&
    typeof report.triggerType === "string" &&
    typeof report.confidence === "number" &&
    typeof report.finalReason === "string" &&
    typeof report.summary === "string" &&
    Array.isArray(report.supportingFactors) &&
    report.supportingFactors.every(isDecisionFactor) &&
    Array.isArray(report.opposingFactors) &&
    report.opposingFactors.every(isDecisionFactor) &&
    Array.isArray(report.riskFlags) &&
    Array.isArray(report.sourceEvents) &&
    !!report.orderResult &&
    typeof report.orderResult === "object"
  );
}

function readReplayDecisions(): DecisionReport[] {
  if (!hasWindowStorage()) {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(DECISION_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isDecisionReport) : [];
  } catch {
    return [];
  }
}

function writeReplayTrades(trades: PaperTrade[]): void {
  if (!hasWindowStorage()) {
    return;
  }
  try {
    window.localStorage.setItem(REPLAY_STORAGE_KEY, JSON.stringify(trades.slice(-MAX_REPLAY_TRADES)));
  } catch {
    // Ignore storage write errors and keep in-memory replay history working.
  }
}

function writeReplayDecisions(decisions: DecisionReport[]): void {
  if (!hasWindowStorage()) {
    return;
  }
  try {
    window.localStorage.setItem(DECISION_STORAGE_KEY, JSON.stringify(decisions.slice(-MAX_REPLAY_DECISIONS)));
  } catch {
    // Ignore storage write errors and keep in-memory replay history working.
  }
}

function mergeReplayTrades(existing: PaperTrade[], incoming: PaperTrade[]): PaperTrade[] {
  const deduped = new Map<string, PaperTrade>();
  [...existing, ...incoming].forEach((trade) => {
    const key = [
      trade.symbol,
      trade.action,
      trade.price,
      trade.shares,
      trade.reason,
      trade.ts,
      trade.netPnl,
      trade.grossPnl,
    ].join("|");
    deduped.set(key, trade);
  });
  return Array.from(deduped.values())
    .sort((left, right) => left.ts - right.ts)
    .slice(-MAX_REPLAY_TRADES);
}

function mergeReplayDecisions(existing: DecisionReport[], incoming: DecisionReport[]): DecisionReport[] {
  const deduped = new Map<string, DecisionReport>();
  [...existing, ...incoming].forEach((report) => {
    deduped.set(report.reportId, report);
  });
  return Array.from(deduped.values())
    .sort((left, right) => left.ts - right.ts)
    .slice(-MAX_REPLAY_DECISIONS);
}

const initialReplayTrades = readReplayTrades();
const initialReplayDecisions = readReplayDecisions();

export const useMarketStore = create<MarketState>()((set) => ({
  connectionState: "idle",
  setConnectionState: (connectionState) => set({ connectionState }),

  snapshot: null,
  setSnapshot: (snapshot) => set({ snapshot }),

  // ticks 用 Map 儲存，applyTick 只替換該 symbol 的條目
  // 注意：必須建立新 Map 才能觸發 selector re-render
  ticks: new Map(),
  applyTick: (delta) =>
    set((state) => {
      const next = new Map(state.ticks);
      next.set(delta.symbol, delta);
      return { ticks: next };
    }),

  portfolio: null,
  replayTrades: initialReplayTrades,
  replayDecisions: initialReplayDecisions,
  appendReplayTrades: (trades) =>
    set((state) => {
      const replayTrades = mergeReplayTrades(state.replayTrades, trades);
      writeReplayTrades(replayTrades);
      return { replayTrades };
    }),
  setPortfolio: (portfolio) =>
    set((state) => {
      const replayTrades = mergeReplayTrades(state.replayTrades, portfolio.recentTrades ?? []);
      const replayDecisions = mergeReplayDecisions(state.replayDecisions, portfolio.recentDecisions ?? []);
      writeReplayTrades(replayTrades);
      writeReplayDecisions(replayDecisions);
      return { portfolio, replayTrades, replayDecisions };
    }),

  selectedSymbol: "",
  setSelectedSymbol: (selectedSymbol) => set({ selectedSymbol }),

  historyCache: new Map(),
  sessionCache: new Map(),
  historyLoadingSymbol: null,
  sessionLoadingSymbol: null,

  setHistoryEntry: (symbol, entry) =>
    set((state) => {
      const next = new Map(state.historyCache);
      next.set(symbol, entry);
      return { historyCache: next };
    }),

  setSessionEntry: (symbol, entry) =>
    set((state) => {
      const next = new Map(state.sessionCache);
      next.set(symbol, entry);
      return { sessionCache: next };
    }),

  setHistoryLoadingSymbol: (historyLoadingSymbol) => set({ historyLoadingSymbol }),
  setSessionLoadingSymbol: (sessionLoadingSymbol) => set({ sessionLoadingSymbol }),

  orderBooks: new Map(),
  tradeTapes: new Map(),
  setOrderBook: (snapshot) =>
    set((state) => {
      const next = new Map(state.orderBooks);
      next.set(snapshot.symbol, snapshot);
      return { orderBooks: next };
    }),
  setTradeTape: (snapshot) =>
    set((state) => {
      const next = new Map(state.tradeTapes);
      next.set(snapshot.symbol, snapshot);
      return { tradeTapes: next };
    }),

  newsFeed: null,
  setNewsFeed: (newsFeed) => set({ newsFeed }),

  desktopRuntimeAvailable: false,
  setDesktopRuntimeAvailable: (desktopRuntimeAvailable) => set({ desktopRuntimeAvailable }),
  desktopBackendStatus: { phase: "idle" },
  setDesktopBackendStatus: (desktopBackendStatus) => set({ desktopBackendStatus }),
  desktopBackendRetrying: false,
  setDesktopBackendRetrying: (desktopBackendRetrying) => set({ desktopBackendRetrying }),
  desktopUpdate: { status: "idle" },
  setDesktopUpdate: (desktopUpdate) => set({ desktopUpdate }),
  dismissDesktopUpdate: () =>
    set((state) => ({
      desktopUpdate: {
        ...state.desktopUpdate,
        status: "dismissed",
      },
    })),
}));

// ── 精準 selector（避免無關 re-render）──────────────────────────────────────

/** 只訂閱單一 symbol 的即時 tick，其他 symbol 跳動不觸發 re-render */
export function useTickDelta(symbol: string): TickDelta | null {
  return useMarketStore((state) => state.ticks.get(symbol) ?? null);
}

/** 訂閱快照中某 symbol 的完整 SymbolSnapshot（較低頻） */
export function useSymbolSnapshot(symbol: string): SymbolSnapshot | null {
  return useMarketStore(
    (state) =>
      state.snapshot?.symbols.find((s) => s.symbol === symbol) ?? null,
  );
}

/** 只訂閱連線狀態 */
export function useConnectionState(): ConnectionState {
  return useMarketStore((state) => state.connectionState);
}

export function useDesktopRuntimeAvailable(): boolean {
  return useMarketStore((state) => state.desktopRuntimeAvailable);
}

export function useDesktopBackendStatus(): DesktopBackendStatus {
  return useMarketStore((state) => state.desktopBackendStatus);
}

export function useDesktopUpdateState(): DesktopUpdateState {
  return useMarketStore((state) => state.desktopUpdate);
}

export function useDesktopBackendRetrying(): boolean {
  return useMarketStore((state) => state.desktopBackendRetrying);
}

/** 只訂閱 portfolio */
export function usePortfolio(): PaperPortfolio | null {
  return useMarketStore((state) => state.portfolio);
}

/** 只訂閱回放交易歷史 */
export function useReplayTrades(): PaperTrade[] {
  return useMarketStore((state) => state.replayTrades);
}

export function useReplayDecisions(): DecisionReport[] {
  return useMarketStore((state) => state.replayDecisions);
}

/** 只訂閱 selectedSymbol */
export function useSelectedSymbol(): string {
  return useMarketStore((state) => state.selectedSymbol);
}

/** 訂閱特定 symbol 的歷史快取 */
export function useHistoryCache(symbol: string): HistoryCacheEntry | undefined {
  return useMarketStore((state) => state.historyCache.get(symbol));
}

/** 訂閱特定 symbol 的盤中快取 */
export function useSessionCache(symbol: string): HistoryCacheEntry | undefined {
  return useMarketStore((state) => state.sessionCache.get(symbol));
}

export function useOrderBook(symbol: string): OrderBookSnapshot | undefined {
  return useMarketStore((state) => state.orderBooks.get(symbol));
}

export function useTradeTape(symbol: string): TradeTapeSnapshot | undefined {
  return useMarketStore((state) => state.tradeTapes.get(symbol));
}

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StrategyWorkbench } from "./StrategyWorkbench";
import { useMarketStore } from "../store";
import type { AggregatedSnapshot } from "../types/market";

vi.mock("lightweight-charts", () => {
  const createSeries = () => ({
    setData: vi.fn(),
    update: vi.fn(),
    applyOptions: vi.fn(),
  });

  const createChart = () => ({
    addCandlestickSeries: () => createSeries(),
    addHistogramSeries: () => createSeries(),
    timeScale: () => ({
      fitContent: vi.fn(),
      setVisibleLogicalRange: vi.fn(),
      subscribeVisibleLogicalRangeChange: vi.fn(),
    }),
    remove: vi.fn(),
  });

  return { createChart };
});

vi.mock("../workerBridge", () => ({
  postWorkerMessage: vi.fn(),
}));

function makeSnapshot(): AggregatedSnapshot {
  const now = Date.now();
  return {
    snapshotId: 1,
    emittedAt: now,
    backlog: 0,
    dropMode: false,
    droppedTicks: 0,
    connectionState: "open",
    symbols: Array.from({ length: 25 }, (_, index) => {
      const symbol = String(1101 + index);
      const changePct = index - 3;
      const base = 20 + index;
      const sector = index < 8 ? "24" : index < 16 ? "17" : "28";
      const volume = 10_000 + index * 5_000;
      return {
        symbol,
        quote: {
          symbol,
          name: `測試股${index + 1}`,
          sector,
          last: base + changePct * 0.4,
          open: base,
          high: base + 1.5,
          low: base - 1.5,
          previousClose: base - 0.5,
          change: changePct * 0.4,
          changePct,
          volume,
          turnover: volume * base,
          ts: now,
          droppedTicks: 0,
        },
        candles: Array.from({ length: 25 }, (_, candleIndex) => ({
          time: now - (25 - candleIndex) * 60_000,
          open: base - 0.4 + candleIndex * 0.02,
          high: base + 0.5 + candleIndex * 0.02,
          low: base - 0.8 + candleIndex * 0.02,
          close: base - 0.2 + candleIndex * 0.04,
          volume: 1_000 + candleIndex * 120,
        })),
        signalLabel: changePct > 5 ? "事件突破" : "等待行情",
      };
    }),
  };
}

describe("StrategyWorkbench", () => {
  beforeEach(() => {
    useMarketStore.setState((state) => ({
      ...state,
      connectionState: "open",
      snapshot: makeSnapshot(),
      ticks: new Map(),
      portfolio: null,
      replayTrades: [],
      replayDecisions: [],
      selectedSymbol: "",
      historyCache: new Map(),
      sessionCache: new Map(),
      historyLoadingSymbol: null,
      sessionLoadingSymbol: null,
    }));
  });

  it("renders only the top 20 ranked candidates", () => {
    render(<StrategyWorkbench />);

    const rows = screen.getAllByTestId("strategy-candidate-row");
    expect(rows).toHaveLength(20);
    expect(screen.queryByRole("button", { name: /1101 測試股1/ })).not.toBeInTheDocument();
  });

  it("prefers the held symbol when it is inside the ranked candidates", () => {
    useMarketStore.setState((state) => ({
      ...state,
      portfolio: {
        type: "PAPER_PORTFOLIO",
        positions: [
          {
            symbol: "1120",
            entryPrice: 39,
            currentPrice: 40,
            shares: 1000,
            pnl: 1000,
            pct: 2.56,
            entryTs: Date.now(),
          },
        ],
        recentTrades: [],
        recentDecisions: [],
        realizedPnl: 0,
        unrealizedPnl: 1000,
        totalPnl: 1000,
        tradeCount: 0,
        winRate: 0,
        marketChangePct: 0,
        riskStatus: {
          date: "2026-04-04",
          dailyPnl: 0,
          dailyLossLimit: -20000,
          isHalted: false,
          rolling5DayPnl: 0,
          rolling5DayLimit: -50000,
          isWeeklyHalted: false,
          dailyTradeCount: 1,
          maxPositions: 5,
          maxSinglePosition: 100000,
          txCostRoundtripPct: 0.585,
        },
      },
    }));

    render(<StrategyWorkbench />);

    expect(screen.getByRole("heading", { name: "1120 測試股20" })).toBeInTheDocument();
  });

  it("switches the detail panel when selecting another ranked candidate", () => {
    render(<StrategyWorkbench />);

    const target = screen.getByRole("button", { name: /1118 測試股18/ });
    fireEvent.click(target);

    expect(screen.getByRole("heading", { name: "1118 測試股18" })).toBeInTheDocument();
  });
});

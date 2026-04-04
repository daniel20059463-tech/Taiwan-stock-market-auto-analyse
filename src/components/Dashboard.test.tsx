import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";
import { useMarketStore } from "../store";
import type { AggregatedSnapshot, InstrumentDefinition } from "../types/market";

vi.mock("lightweight-charts", () => {
  const createSeries = () => ({
    setData: vi.fn(),
    update: vi.fn(),
    applyOptions: vi.fn(),
  });

  const createChart = () => ({
    addCandlestickSeries: () => createSeries(),
    addLineSeries: () => createSeries(),
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

const instruments: InstrumentDefinition[] = [
  { symbol: "1101", name: "台泥", sector: "01", previousClose: 23.7, averageVolume: 10000 },
  { symbol: "1102", name: "亞泥", sector: "01", previousClose: 35.25, averageVolume: 8000 },
];

const snapshot: AggregatedSnapshot = {
  snapshotId: 1,
  emittedAt: Date.now(),
  backlog: 0,
  dropMode: false,
  droppedTicks: 0,
  connectionState: "open",
  symbols: instruments.map((instrument) => ({
    symbol: instrument.symbol,
    quote: {
      symbol: instrument.symbol,
      name: instrument.name,
      sector: instrument.sector,
      last: instrument.previousClose,
      open: instrument.previousClose,
      high: instrument.previousClose,
      low: instrument.previousClose,
      previousClose: instrument.previousClose,
      change: 0,
      changePct: 0,
      volume: 0,
      turnover: 0,
      ts: Date.now(),
      droppedTicks: 0,
    },
    candles: [],
    signalLabel: "等待行情",
  })),
};

describe("Dashboard", () => {
  beforeEach(() => {
    useMarketStore.setState((state) => ({
      ...state,
      connectionState: "open",
      snapshot,
      ticks: new Map(),
      portfolio: null,
      replayTrades: [],
      selectedSymbol: "1101",
      historyCache: new Map(),
      sessionCache: new Map(),
      historyLoadingSymbol: null,
      sessionLoadingSymbol: null,
    }));
  });

  it("renders the market-first homepage sections", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    expect(screen.getByText("台股模擬交易雷達")).toBeInTheDocument();
    expect(screen.getByText("全市場機會")).toBeInTheDocument();
    expect(screen.getByText("類股熱度排行")).toBeInTheDocument();
    expect(screen.getByText("單一標的盤面")).toBeInTheDocument();
    expect(screen.getByText("標的摘要與帳本")).toBeInTheDocument();
  });

  it("prefers the held symbol for the detail panel default selection", () => {
    useMarketStore.setState((state) => ({
      ...state,
      selectedSymbol: "",
      portfolio: {
        type: "PAPER_PORTFOLIO",
        positions: [
          {
            symbol: "1102",
            entryPrice: 35.25,
            currentPrice: 35.25,
            shares: 1000,
            pnl: 0,
            pct: 0,
            entryTs: Date.now(),
          },
        ],
        recentTrades: [],
        realizedPnl: 0,
        unrealizedPnl: 0,
        totalPnl: 0,
        tradeCount: 0,
        winRate: 0,
        marketChangePct: 0,
      },
    }));

    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    expect(screen.getByRole("heading", { name: "1102 亞泥" })).toBeInTheDocument();
  });
});

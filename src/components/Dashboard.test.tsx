import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";
import { useMarketStore } from "../store";
import type { AggregatedSnapshot, InstrumentDefinition } from "../types/market";

const { postWorkerMessageMock, chartSeriesSpies } = vi.hoisted(() => ({
  postWorkerMessageMock: vi.fn(),
  chartSeriesSpies: {
    area: [] as Array<{ setData: ReturnType<typeof vi.fn>; applyOptions: ReturnType<typeof vi.fn> }>,
    candle: [] as Array<{ setData: ReturnType<typeof vi.fn>; applyOptions: ReturnType<typeof vi.fn> }>,
    histogram: [] as Array<{ setData: ReturnType<typeof vi.fn>; applyOptions: ReturnType<typeof vi.fn> }>,
    line: [] as Array<{ setData: ReturnType<typeof vi.fn>; applyOptions: ReturnType<typeof vi.fn> }>,
  },
}));

vi.mock("../workerBridge", () => ({
  postWorkerMessage: postWorkerMessageMock,
}));

vi.mock("lightweight-charts", () => {
  const createSeries = (bucket: keyof typeof chartSeriesSpies) => {
    const series = {
      setData: vi.fn(),
      update: vi.fn(),
      applyOptions: vi.fn(),
    };
    chartSeriesSpies[bucket].push(series);
    return series;
  };

  const createChart = () => ({
    addCandlestickSeries: () => createSeries("candle"),
    addLineSeries: () => createSeries("line"),
    addAreaSeries: () => createSeries("area"),
    addHistogramSeries: () => createSeries("histogram"),
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

function createSnapshot(): AggregatedSnapshot {
  return {
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
      signalLabel: "觀察",
    })),
  };
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    postWorkerMessageMock.mockReset();
    chartSeriesSpies.area.length = 0;
    chartSeriesSpies.candle.length = 0;
    chartSeriesSpies.histogram.length = 0;
    chartSeriesSpies.line.length = 0;
    useMarketStore.setState((state) => ({
      ...state,
      connectionState: "open",
      snapshot: createSnapshot(),
      ticks: new Map(),
      portfolio: null,
      replayTrades: [],
      selectedSymbol: "1101",
      historyCache: new Map(),
      sessionCache: new Map(),
      orderBooks: new Map(),
      tradeTapes: new Map(),
      historyLoadingSymbol: null,
      sessionLoadingSymbol: null,
    }));
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("renders the stock detail panel structure", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    expect(screen.getByText("個股詳細報價")).toBeInTheDocument();
    expect(screen.getByText("最佳五檔")).toBeInTheDocument();
    expect(screen.getByText("分時明細")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "買進" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "賣出" })).toBeInTheDocument();
  });

  it("shows the chart tabs for intraday and k-bar views", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    expect(screen.getByRole("button", { name: "分時線" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "日K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "週K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "月K" })).toBeInTheDocument();
  });

  it("shows intraday empty-state copy when there is no intraday data", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    expect(screen.getByText("載入分時線中...")).toBeInTheDocument();
  });

  it("shows k-bar empty-state copy when there is no history data", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    fireEvent.click(screen.getByRole("button", { name: "日K" }));

    expect(screen.getByText("載入K線中...")).toBeInTheDocument();
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

  it("subscribes quote detail for the selected symbol", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    expect(postWorkerMessageMock).toHaveBeenCalledWith({
      type: "SUBSCRIBE_QUOTE_DETAIL",
      symbol: "1101",
    });
  });

  it("retries history loading after the previous request stays stuck", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    fireEvent.click(screen.getByRole("button", { name: "日K" }));

    expect(postWorkerMessageMock).toHaveBeenCalledWith({
      type: "LOAD_HISTORY",
      symbol: "1101",
      months: 6,
    });

    postWorkerMessageMock.mockClear();

    act(() => {
      vi.advanceTimersByTime(4_000);
    });

    expect(postWorkerMessageMock).toHaveBeenCalledWith({
      type: "LOAD_HISTORY",
      symbol: "1101",
      months: 6,
    });
  });

  it("retries session loading after the previous request stays stuck", () => {
    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    expect(postWorkerMessageMock).toHaveBeenCalledWith({
      type: "LOAD_SESSION",
      symbol: "1101",
      limit: 240,
    });

    postWorkerMessageMock.mockClear();

    act(() => {
      vi.advanceTimersByTime(4_000);
    });

    expect(postWorkerMessageMock).toHaveBeenCalledWith({
      type: "LOAD_SESSION",
      symbol: "1101",
      limit: 240,
    });
  });

  it("feeds real history candles into the candlestick series when daily mode is selected", () => {
    useMarketStore.setState((state) => {
      const historyCache = new Map(state.historyCache);
      historyCache.set("1101", {
        candles: [
          { time: 1_768_294_800_000, open: 23.2, high: 23.9, low: 23.1, close: 23.7, volume: 1200 },
          { time: 1_768_381_200_000, open: 23.8, high: 24.1, low: 23.6, close: 24.0, volume: 1500 },
        ],
        source: "sinopac",
      });
      return {
        ...state,
        historyCache,
      };
    });

    render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

    fireEvent.click(screen.getByRole("button", { name: "日K" }));

    expect(chartSeriesSpies.candle[0].setData).toHaveBeenLastCalledWith([
      { time: 1768294800, open: 23.2, high: 23.9, low: 23.1, close: 23.7 },
      { time: 1768381200, open: 23.8, high: 24.1, low: 23.6, close: 24.0 },
    ]);
  });
});

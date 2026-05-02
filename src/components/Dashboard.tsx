import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  useConnectionState,
  useMarketStore,
  useOrderBook,
  usePortfolio,
  useSelectedSymbol,
  useTickDelta,
  useTradeTape,
} from "../store";
import type { Candle, InstrumentDefinition, SymbolSnapshot, WorkerInboundMessage } from "../types/market";
import { postWorkerMessage } from "../workerBridge";
import { NewsPanel } from "./NewsPanel";

const palette = {
  bg: "#0a0d12",
  panel: "#10161d",
  panelSoft: "#0c1117",
  panelHover: "#16202c",
  border: "#212b36",
  grid: "#1a2430",
  text: "#eef4ff",
  muted: "#8a97a6",
  accent: "#3b88ff",
  up: "#ff4d4f",
  down: "#00c853",
  flat: "#f1c232",
  volumeUp: "rgba(255,77,79,0.55)",
  volumeDown: "rgba(0,200,83,0.55)",
};

const mono = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums" as const,
};

type ChartMode = "intraday" | "daily" | "weekly" | "monthly";

const sectorMap: Record<string, string> = {
  All: "全部",
  "01": "水泥工業",
  "02": "食品工業",
  "03": "塑膠工業",
  "05": "電機機械",
  "06": "電器電纜",
  "10": "鋼鐵工業",
  "12": "汽車工業",
  "14": "建材營造",
  "15": "航運業",
  "16": "觀光餐旅",
  "17": "金融保險",
  "18": "貿易百貨",
  "20": "其他",
  "21": "化學工業",
  "22": "生技醫療",
  "23": "油電燃氣",
  "24": "半導體",
  "25": "電腦及週邊",
  "26": "光電業",
  "27": "通信網路",
  "28": "電子零組件",
  "29": "電子通路",
  "30": "資訊服務",
  "31": "其他電子",
  "33": "數位雲端",
  "35": "綠能環保",
  "36": "居家生活",
  "37": "運動休閒",
  "38": "存託憑證",
  "91": "創新板",
};

const sectorGroups = [
  { label: "全部", options: [{ value: "All", label: "全部" }] },
  {
    label: "電子",
    options: ["24", "25", "26", "27", "28", "29", "30", "31"].map((code) => ({
      value: code,
      label: sectorMap[code] ?? code,
    })),
  },
  {
    label: "傳產",
    options: ["01", "02", "03", "05", "06", "10", "12", "14", "15", "17", "21", "23"].map((code) => ({
      value: code,
      label: sectorMap[code] ?? code,
    })),
  },
  {
    label: "其他",
    options: ["16", "18", "20", "22", "33", "35", "36", "37", "38", "91"].map((code) => ({
      value: code,
      label: sectorMap[code] ?? code,
    })),
  },
];

function formatPrice(value: number) {
  return new Intl.NumberFormat("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatSignedPrice(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "" : ""}${formatPrice(value)}`;
}

function formatPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("zh-TW", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function tone(value: number) {
  if (value > 0) return palette.up;
  if (value < 0) return palette.down;
  return palette.flat;
}

function sideLabel(side: "outer" | "inner" | "neutral") {
  switch (side) {
    case "outer":
      return "外盤";
    case "inner":
      return "內盤";
    default:
      return "中性";
  }
}

function sideColor(side: "outer" | "inner" | "neutral") {
  switch (side) {
    case "outer":
      return palette.up;
    case "inner":
      return palette.down;
    default:
      return palette.flat;
  }
}

function sectorLabel(sector: string) {
  const label = sectorMap[sector] ?? sector;
  return sector === "All" ? label : `${sector} ${label}`;
}

function processCandles(candles: Candle[]) {
  const keyed = new Map<number, Candle>();
  candles.forEach((candle) => keyed.set(Math.floor(candle.time / 1000), candle));
  return Array.from(keyed.values()).sort(
    (left, right) => Math.floor(left.time / 1000) - Math.floor(right.time / 1000),
  );
}

function weekKey(ts: number) {
  const date = new Date(ts);
  const day = date.getDay();
  const offset = day === 0 ? -6 : 1 - day;
  date.setDate(date.getDate() + offset);
  date.setHours(0, 0, 0, 0);
  return date.toISOString().slice(0, 10);
}

function monthKey(ts: number) {
  const date = new Date(ts);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function aggregateCandles(candles: Candle[], mode: "weekly" | "monthly") {
  const normalized = processCandles(candles);
  const groups = new Map<string, Candle[]>();

  for (const candle of normalized) {
    const key = mode === "weekly" ? weekKey(candle.time) : monthKey(candle.time);
    const bucket = groups.get(key) ?? [];
    bucket.push(candle);
    groups.set(key, bucket);
  }

  return Array.from(groups.values()).map((bucket) => ({
    time: bucket[0].time,
    open: bucket[0].open,
    high: Math.max(...bucket.map((item) => item.high)),
    low: Math.min(...bucket.map((item) => item.low)),
    close: bucket[bucket.length - 1].close,
    volume: bucket.reduce((sum, item) => sum + item.volume, 0),
  }));
}

function movingAverage(candles: Candle[], period: number) {
  const normalized = processCandles(candles);
  const output: { time: UTCTimestamp; value: number }[] = [];
  let sum = 0;

  for (let index = 0; index < normalized.length; index += 1) {
    sum += normalized[index].close;
    if (index >= period) {
      sum -= normalized[index - period].close;
    }
    if (index >= period - 1) {
      output.push({
        time: Math.floor(normalized[index].time / 1000) as UTCTimestamp,
        value: Number((sum / period).toFixed(2)),
      });
    }
  }

  return output;
}

function fallbackSnapshot(instrument: InstrumentDefinition): SymbolSnapshot {
  return {
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
  };
}

function chartModeLabel(mode: ChartMode) {
  switch (mode) {
    case "intraday":
      return "分時線";
    case "daily":
      return "日K";
    case "weekly":
      return "週K";
    case "monthly":
      return "月K";
  }
}

function useQuoteRows(
  symbols: string[],
  instruments: InstrumentDefinition[],
  snapshot: ReturnType<typeof useMarketStore.getState>["snapshot"],
  ticks: ReturnType<typeof useMarketStore.getState>["ticks"],
) {
  return useMemo(() => {
    const liveMap = new Map(snapshot?.symbols?.map((item) => [item.symbol, item]) ?? []);
    const tickMap = ticks ?? new Map();
    const source =
      instruments.length > 0
        ? instruments
        : symbols.map((symbol) => ({
            symbol,
            name: symbol,
            sector: "All",
            previousClose: 0,
            averageVolume: 0,
          }));

    return source.map((instrument) => {
      const base = liveMap.get(instrument.symbol) ?? fallbackSnapshot(instrument);
      const tick = tickMap.get(instrument.symbol);
      if (!tick) {
        return base;
      }

      const previousClose = base.quote.previousClose || instrument.previousClose || tick.price;
      const change = tick.price - previousClose;

      return {
        ...base,
        quote: {
          ...base.quote,
          last: tick.price,
          high: tick.high || base.quote.high,
          low: tick.low || base.quote.low,
          volume: tick.volume,
          turnover: tick.turnover,
          ts: tick.ts,
          change,
          changePct: tick.changePct,
        },
        candles:
          tick.activeCandle && base.candles.length === 0
            ? [
                {
                  time: tick.activeCandle.time,
                  open: tick.activeCandle.open,
                  high: tick.activeCandle.high,
                  low: tick.activeCandle.low,
                  close: tick.activeCandle.close,
                  volume: tick.activeCandle.volume,
                },
              ]
            : base.candles,
      };
    });
  }, [instruments, snapshot?.symbols, symbols, ticks]);
}

function usePreferredSymbol(rows: SymbolSnapshot[], portfolio: ReturnType<typeof usePortfolio>) {
  return useMemo(
    () =>
      portfolio?.positions?.[0]?.symbol ??
      portfolio?.recentTrades?.slice(-1)[0]?.symbol ??
      rows[0]?.symbol ??
      "",
    [portfolio, rows],
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div style={{ display: "grid", gap: "3px" }}>
      <div style={{ fontSize: "15px", fontWeight: 800, color: palette.text }}>{title}</div>
      {subtitle ? <div style={{ fontSize: "11px", color: palette.muted }}>{subtitle}</div> : null}
    </div>
  );
}

function HeaderMetric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: "grid", gap: "2px" }}>
      <div style={{ fontSize: "11px", color: palette.muted }}>{label}</div>
      <div style={{ fontSize: "14px", color: color ?? palette.text, ...mono }}>{value}</div>
    </div>
  );
}


export interface DashboardProps {
  symbols: string[];
  instruments?: InstrumentDefinition[];
  title?: string;
}

export function Dashboard({
  symbols,
  instruments = [],
  title = "台股模擬交易雷達",
}: DashboardProps) {
  const historyRetryTimerRef = useRef<number | null>(null);
  const sessionRetryTimerRef = useRef<number | null>(null);
  const snapshot = useMarketStore((state) => state.snapshot);
  const ticks = useMarketStore((state) => state.ticks);
  const selectedSymbol = useSelectedSymbol();
  const setSelectedSymbol = useMarketStore((state) => state.setSelectedSymbol);
  const historyCache = useMarketStore((state) => state.historyCache);
  const sessionCache = useMarketStore((state) => state.sessionCache);
  const historyLoadingSymbol = useMarketStore((state) => state.historyLoadingSymbol);
  const sessionLoadingSymbol = useMarketStore((state) => state.sessionLoadingSymbol);
  const setHistoryLoadingSymbol = useMarketStore((state) => state.setHistoryLoadingSymbol);
  const setSessionLoadingSymbol = useMarketStore((state) => state.setSessionLoadingSymbol);
  const connectionState = useConnectionState();
  const portfolio = usePortfolio();

  const [search, setSearch] = useState("");
  const [filterKey, setFilterKey] = useState("All");
  const [chartMode, setChartMode] = useState<ChartMode>("intraday");

  const rows = useQuoteRows(symbols, instruments, snapshot, ticks);
  const preferredSymbol = usePreferredSymbol(rows, portfolio);

  useEffect(() => {
    if (!selectedSymbol && preferredSymbol) {
      setSelectedSymbol(preferredSymbol);
    }
  }, [preferredSymbol, selectedSymbol, setSelectedSymbol]);

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return rows.filter((row) => {
      const hasLiveQuote =
        row.quote.last > 0 &&
        (row.quote.volume > 0 ||
          row.quote.turnover > 0 ||
          Math.abs(row.quote.changePct) > 0 ||
          row.quote.previousClose > 0);
      if (!hasLiveQuote) {
        return false;
      }
      const matchesFilter = filterKey === "All" || row.quote.sector === filterKey;
      const matchesSearch =
        !query ||
        row.symbol.toLowerCase().includes(query) ||
        row.quote.name.toLowerCase().includes(query) ||
        sectorLabel(row.quote.sector).toLowerCase().includes(query);
      return matchesFilter && matchesSearch;
    });
  }, [filterKey, rows, search]);

  const visiblePreloadSymbols = useMemo(
    () => filteredRows.slice(0, 12).map((row) => row.symbol),
    [filteredRows],
  );

  const detailSymbol = selectedSymbol || preferredSymbol;
  const selectedRow = rows.find((row) => row.symbol === detailSymbol) ?? rows[0] ?? null;
  const selectedQuote = selectedRow?.quote ?? null;
  const orderBook = useOrderBook(selectedRow?.symbol ?? "");
  const tradeTape = useTradeTape(selectedRow?.symbol ?? "");
  const selectedTick = useTickDelta(selectedRow?.symbol ?? "");
  const historyEntry = selectedRow ? historyCache.get(selectedRow.symbol) : undefined;
  const sessionEntry = selectedRow ? sessionCache.get(selectedRow.symbol) : undefined;

  const intradayFallbackCandle = selectedTick?.activeCandle
    ? {
        time: selectedTick.activeCandle.time,
        open: selectedTick.activeCandle.open,
        high: selectedTick.activeCandle.high,
        low: selectedTick.activeCandle.low,
        close: selectedTick.activeCandle.close,
        volume: selectedTick.activeCandle.volume,
      }
    : null;

  const intradayCandles = processCandles(
    sessionEntry?.candles?.length
      ? sessionEntry.candles
      : intradayFallbackCandle
        ? [intradayFallbackCandle]
        : [],
  );
  const dailyCandles = processCandles(
    historyEntry?.candles?.length
      ? historyEntry.candles
      : [],
  );
  const weeklyCandles = useMemo(() => aggregateCandles(dailyCandles, "weekly"), [dailyCandles]);
  const monthlyCandles = useMemo(() => aggregateCandles(dailyCandles, "monthly"), [dailyCandles]);

  const chartCandles = useMemo(() => {
    switch (chartMode) {
      case "intraday":
        return intradayCandles;
      case "daily":
        return dailyCandles;
      case "weekly":
        return weeklyCandles;
      case "monthly":
        return monthlyCandles;
    }
  }, [chartMode, dailyCandles, intradayCandles, monthlyCandles, weeklyCandles]);

  const chartMessage =
    !selectedRow
      ? "選取股票後顯示圖表"
      : chartMode === "intraday"
        ? chartCandles.length > 0
          ? null
          : "尚無當日資料"
        : chartCandles.length > 0
          ? null
          : "尚無K線資料";

  const shouldLoadSession =
    !!selectedRow &&
    chartMode === "intraday" &&
    connectionState === "open" &&
    sessionLoadingSymbol !== selectedRow.symbol &&
    (!sessionEntry || !!sessionEntry.error || sessionEntry.candles.length === 0);

  const shouldLoadHistory =
    !!selectedRow &&
    chartMode !== "intraday" &&
    connectionState === "open" &&
    historyLoadingSymbol !== selectedRow.symbol &&
    (!historyEntry || !!historyEntry.error || historyEntry.candles.length === 0);

  const displayChartMessage =
    !selectedRow
      ? "選取股票後顯示圖表"
      : chartMode === "intraday" && sessionLoadingSymbol === selectedRow.symbol
        ? "載入分時線中..."
        : chartMode !== "intraday" && historyLoadingSymbol === selectedRow.symbol
          ? "載入K線中..."
          : chartMessage;

  useEffect(() => {
    if (historyRetryTimerRef.current !== null) {
      window.clearTimeout(historyRetryTimerRef.current);
      historyRetryTimerRef.current = null;
    }

    if (!selectedRow || historyLoadingSymbol !== selectedRow.symbol) {
      return;
    }

    historyRetryTimerRef.current = window.setTimeout(() => {
      const state = useMarketStore.getState();
      const entry = state.historyCache.get(selectedRow.symbol);
      if (
        state.historyLoadingSymbol === selectedRow.symbol &&
        (!entry || !!entry.error || entry.candles.length === 0)
      ) {
        state.setHistoryLoadingSymbol(null);
      }
    }, 4_000);

    return () => {
      if (historyRetryTimerRef.current !== null) {
        window.clearTimeout(historyRetryTimerRef.current);
        historyRetryTimerRef.current = null;
      }
    };
  }, [historyLoadingSymbol, selectedRow]);

  useEffect(() => {
    if (sessionRetryTimerRef.current !== null) {
      window.clearTimeout(sessionRetryTimerRef.current);
      sessionRetryTimerRef.current = null;
    }

    if (!selectedRow || sessionLoadingSymbol !== selectedRow.symbol) {
      return;
    }

    sessionRetryTimerRef.current = window.setTimeout(() => {
      const state = useMarketStore.getState();
      const entry = state.sessionCache.get(selectedRow.symbol);
      if (
        state.sessionLoadingSymbol === selectedRow.symbol &&
        (!entry || !!entry.error || entry.candles.length === 0)
      ) {
        state.setSessionLoadingSymbol(null);
      }
    }, 4_000);

    return () => {
      if (sessionRetryTimerRef.current !== null) {
        window.clearTimeout(sessionRetryTimerRef.current);
        sessionRetryTimerRef.current = null;
      }
    };
  }, [selectedRow, sessionLoadingSymbol]);

  useEffect(() => {
    if (!selectedRow || connectionState !== "open") {
      return;
    }

    if (shouldLoadSession) {
      setSessionLoadingSymbol(selectedRow.symbol);
      postWorkerMessage({
        type: "LOAD_SESSION",
        symbol: selectedRow.symbol,
        limit: 240,
      } satisfies WorkerInboundMessage);
      return;
    }

    if (shouldLoadHistory) {
      setHistoryLoadingSymbol(selectedRow.symbol);
      postWorkerMessage({
        type: "LOAD_HISTORY",
        symbol: selectedRow.symbol,
        months: 6,
      } satisfies WorkerInboundMessage);
    }
  }, [
    chartMode,
    connectionState,
    historyEntry,
    historyLoadingSymbol,
    selectedRow,
    sessionEntry,
    sessionLoadingSymbol,
    setHistoryLoadingSymbol,
    setSessionLoadingSymbol,
    shouldLoadHistory,
    shouldLoadSession,
  ]);

  useEffect(() => {
    if (!selectedRow) {
      return;
    }
    postWorkerMessage({
      type: "SUBSCRIBE_QUOTE_DETAIL",
      symbol: selectedRow.symbol,
    } satisfies WorkerInboundMessage);
  }, [selectedRow?.symbol]);

  useEffect(() => {
    if (connectionState !== "open" || visiblePreloadSymbols.length === 0) {
      return;
    }
    postWorkerMessage({
      type: "PRELOAD_HISTORY",
      symbols: visiblePreloadSymbols,
      months: 6,
    } satisfies WorkerInboundMessage);
  }, [connectionState, visiblePreloadSymbols]);

  const mainHostRef = useRef<HTMLDivElement | null>(null);
  const volumeHostRef = useRef<HTMLDivElement | null>(null);
  const mainChartRef = useRef<IChartApi | null>(null);
  const volumeChartRef = useRef<IChartApi | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma5Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma10Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma20Ref = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const mainHost = mainHostRef.current;
    const volumeHost = volumeHostRef.current;
    if (!mainHost || !volumeHost) {
      return;
    }

    const mainChart = createChart(mainHost, {
      autoSize: true,
      layout: {
        background: { color: "rgba(0,0,0,0)" },
        textColor: palette.muted,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border, timeVisible: true, secondsVisible: false },
      crosshair: {
        vertLine: { color: "#314157", labelBackgroundColor: "#1a2430" },
        horzLine: { color: "#314157", labelBackgroundColor: "#1a2430" },
      },
    });

    const volumeChart = createChart(volumeHost, {
      autoSize: true,
      layout: {
        background: { color: "rgba(0,0,0,0)" },
        textColor: palette.muted,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(0,0,0,0)" },
        horzLines: { color: "rgba(0,0,0,0)" },
      },
      rightPriceScale: {
        borderColor: palette.border,
        scaleMargins: { top: 0.12, bottom: 0.04 },
      },
      timeScale: { borderColor: palette.border, timeVisible: true, secondsVisible: false },
    });

    areaRef.current = mainChart.addAreaSeries({
      lineColor: "#4d8dff",
      topColor: "rgba(77, 141, 255, 0.32)",
      bottomColor: "rgba(77, 141, 255, 0.02)",
      lineWidth: 2,
      priceLineVisible: true,
      crosshairMarkerVisible: false,
    });

    candleRef.current = mainChart.addCandlestickSeries({
      upColor: palette.up,
      downColor: palette.down,
      borderVisible: false,
      wickUpColor: palette.up,
      wickDownColor: palette.down,
      priceLineVisible: true,
    });

    volumeRef.current = volumeChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });

    ma5Ref.current = mainChart.addLineSeries({
      color: "#ffbd2e",
      lineWidth: 1,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });
    ma10Ref.current = mainChart.addLineSeries({
      color: "#3aa0ff",
      lineWidth: 1,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });
    ma20Ref.current = mainChart.addLineSeries({
      color: "#b088ff",
      lineWidth: 1,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });

    mainChartRef.current = mainChart;
    volumeChartRef.current = volumeChart;

    mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        volumeChart.timeScale().setVisibleLogicalRange(range);
      }
    });
    volumeChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        mainChart.timeScale().setVisibleLogicalRange(range);
      }
    });

    return () => {
      mainChart.remove();
      volumeChart.remove();
    };
  }, []);

  useEffect(() => {
    if (!areaRef.current || !candleRef.current || !volumeRef.current) {
      return;
    }

    const areaData = chartCandles.map((candle) => ({
      time: Math.floor(candle.time / 1000) as UTCTimestamp,
      value: candle.close,
    }));

    const candleData = chartCandles.map((candle) => ({
      time: Math.floor(candle.time / 1000) as UTCTimestamp,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));

    const volumeData = chartCandles.map((candle, index, list) => ({
      time: Math.floor(candle.time / 1000) as UTCTimestamp,
      value: candle.volume,
      color:
        candle.close >= (list[index - 1]?.close ?? candle.open)
          ? palette.volumeUp
          : palette.volumeDown,
    }));

    areaRef.current.applyOptions({ visible: chartMode === "intraday" });
    areaRef.current.setData(chartMode === "intraday" ? areaData : []);

    candleRef.current.applyOptions({ visible: chartMode !== "intraday" });
    candleRef.current.setData(chartMode !== "intraday" ? candleData : []);

    volumeRef.current.setData(volumeData);

    ma5Ref.current?.applyOptions({ visible: chartMode !== "intraday" });
    ma10Ref.current?.applyOptions({ visible: chartMode !== "intraday" });
    ma20Ref.current?.applyOptions({ visible: chartMode !== "intraday" });
    ma5Ref.current?.setData(chartMode !== "intraday" ? movingAverage(chartCandles, 5) : []);
    ma10Ref.current?.setData(chartMode !== "intraday" ? movingAverage(chartCandles, 10) : []);
    ma20Ref.current?.setData(chartMode !== "intraday" ? movingAverage(chartCandles, 20) : []);

    mainChartRef.current?.timeScale().fitContent();
    volumeChartRef.current?.timeScale().fitContent();
  }, [chartCandles, chartMode]);

  const bestFiveRows = useMemo(() => {
    const asks = [...(orderBook?.asks ?? [])].sort((left, right) => left.level - right.level);
    const bids = [...(orderBook?.bids ?? [])].sort((left, right) => left.level - right.level);
    return Array.from({ length: 5 }, (_, index) => ({
      ask: asks[4 - index] ?? null,
      bid: bids[index] ?? null,
    }));
  }, [orderBook]);

  const tapeRows = tradeTape?.rows ?? [];

  return (
    <div
      style={{
        height: "calc(100vh - 8px)",
        background: palette.bg,
        color: palette.text,
        padding: "8px 10px",
        boxSizing: "border-box",
        fontFamily: "var(--font-sans)",
        display: "grid",
        gridTemplateRows: "74px minmax(0, 1fr) 110px",
        gap: "10px",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1fr) 230px auto",
          gap: "10px",
          alignItems: "center",
          padding: "8px 12px",
          background: palette.panel,
          border: `1px solid ${palette.border}`,
          minHeight: 0,
        }}
      >
        <div style={{ display: "grid", gap: "2px", minWidth: 0 }}>
          <div style={{ fontSize: "11px", color: palette.muted, letterSpacing: "0.12em" }}>TAR DASHBOARD</div>
          <div style={{ fontSize: "18px", fontWeight: 800 }}>{title}</div>
          <div style={{ color: palette.muted, fontSize: "11px" }}>左側清單固定捲動，右側集中顯示個股明細。</div>
        </div>

        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="搜尋代號 / 名稱 / 類股"
          style={{
            padding: "8px 10px",
            background: "rgba(255,255,255,0.04)",
            border: `1px solid ${palette.border}`,
            color: palette.text,
            fontSize: "12px",
            outline: "none",
          }}
        />

        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: "24px", fontWeight: 900, color: tone(selectedQuote?.changePct ?? 0), ...mono }}>
            {selectedQuote ? formatPrice(selectedQuote.last) : "--"}
          </div>
          <div style={{ fontSize: "12px", color: palette.muted }}>
            {selectedRow ? `${selectedRow.symbol} ${selectedRow.quote.name}` : "未選擇股票"}
          </div>
        </div>
      </div>

      <div
        style={{
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: "300px minmax(0, 1fr)",
          gap: "10px",
          overflow: "hidden",
        }}
      >
        <section
          style={{
            minHeight: 0,
            background: palette.panel,
            border: `1px solid ${palette.border}`,
            display: "grid",
            gridTemplateRows: "auto auto minmax(0, 1fr)",
            gap: "8px",
            padding: "10px",
            overflow: "hidden",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "end", gap: "10px" }}>
            <SectionTitle title="股票清單" subtitle="左欄固定捲動，避免整頁過長。" />
            <div style={{ color: palette.muted, fontSize: "11px" }}>
              {connectionState === "open" ? "已連線" : connectionState}
            </div>
          </div>

          <select
            value={filterKey}
            onChange={(event) => setFilterKey(event.target.value)}
            style={{
              padding: "8px 10px",
              background: "rgba(255,255,255,0.04)",
              border: `1px solid ${palette.border}`,
              color: palette.text,
              fontSize: "12px",
              outline: "none",
            }}
          >
            {sectorGroups.flatMap((group) =>
              group.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              )),
            )}
          </select>

          <div
            style={{
              minHeight: 0,
              overflowY: "auto",
              overflowX: "hidden",
              display: "grid",
              gap: "6px",
              alignContent: "start",
              paddingRight: "2px",
            }}
          >
            {filteredRows.map((row) => (
              <button
                key={row.symbol}
                type="button"
                onClick={() => setSelectedSymbol(row.symbol)}
                style={{
                  textAlign: "left",
                  display: "grid",
                  gap: "4px",
                  padding: "10px 10px",
                  border: `1px solid ${row.symbol === detailSymbol ? palette.accent : palette.border}`,
                  background: row.symbol === detailSymbol ? palette.panelHover : palette.panelSoft,
                  color: palette.text,
                  cursor: "pointer",
                }}
              >
                <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "8px" }}>
                  <div style={{ display: "grid", gap: "2px" }}>
                    <div style={{ fontWeight: 800, fontSize: "15px" }}>{row.symbol} {row.quote.name}</div>
                    <div style={{ color: palette.muted, fontSize: "11px" }}>{sectorLabel(row.quote.sector)}</div>
                  </div>
                  <div style={{ color: tone(row.quote.changePct), fontWeight: 700, fontSize: "12px", ...mono }}>
                    {formatPct(row.quote.changePct)}
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: "8px", alignItems: "center" }}>
                  <div style={{ color: palette.muted, fontSize: "11px" }}>{row.signalLabel}</div>
                  <div style={{ ...mono, fontSize: "13px" }}>{formatPrice(row.quote.last)}</div>
                  <div style={{ color: palette.muted, ...mono, fontSize: "11px" }}>{formatCompact(row.quote.turnover)}</div>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section
          style={{
            minHeight: 0,
            background: palette.panel,
            border: `1px solid ${palette.border}`,
            display: "grid",
            gridTemplateRows: "118px 1.18fr 1.08fr 62px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "10px 14px",
              borderBottom: `1px solid ${palette.border}`,
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) auto",
              gap: "16px",
              alignItems: "start",
            }}
          >
            <div style={{ display: "grid", gap: "4px", minWidth: 0 }}>
              <div style={{ fontSize: "11px", color: palette.muted }}>個股詳細報價</div>
              <h2 style={{ margin: 0, fontSize: "26px", fontWeight: 900, ...mono }}>
                {selectedRow ? `${selectedRow.symbol} ${selectedRow.quote.name}` : "未選擇股票"}
              </h2>
              <div style={{ display: "flex", gap: "10px", alignItems: "baseline", flexWrap: "wrap" }}>
                <span style={{ fontSize: "30px", fontWeight: 900, color: tone(selectedQuote?.changePct ?? 0), ...mono }}>
                  {selectedQuote ? formatPrice(selectedQuote.last) : "--"}
                </span>
                <span style={{ fontSize: "15px", color: tone(selectedQuote?.changePct ?? 0), ...mono }}>
                  {selectedQuote ? formatSignedPrice(selectedQuote.change) : "--"}
                </span>
                <span style={{ fontSize: "15px", color: tone(selectedQuote?.changePct ?? 0), ...mono }}>
                  {selectedQuote ? formatPct(selectedQuote.changePct) : "--"}
                </span>
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, minmax(82px, 1fr))",
                gap: "8px 14px",
                alignContent: "start",
              }}
            >
              <HeaderMetric label="開盤" value={selectedQuote ? formatPrice(selectedQuote.open) : "--"} />
              <HeaderMetric label="最高" value={selectedQuote ? formatPrice(selectedQuote.high) : "--"} color={palette.up} />
              <HeaderMetric label="最低" value={selectedQuote ? formatPrice(selectedQuote.low) : "--"} color={palette.down} />
              <HeaderMetric label="昨收" value={selectedQuote ? formatPrice(selectedQuote.previousClose) : "--"} />
              <HeaderMetric label="成交量" value={selectedQuote ? formatCompact(selectedQuote.volume) : "--"} />
              <HeaderMetric label="成交值" value={selectedQuote ? formatCompact(selectedQuote.turnover) : "--"} />
            </div>
          </div>

          <div
            style={{
              padding: "10px 14px",
              borderBottom: `1px solid ${palette.border}`,
              display: "grid",
              gridTemplateRows: "auto minmax(0, 1fr)",
              gap: "8px",
              minHeight: 0,
            }}
          >
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {(["intraday", "daily", "weekly", "monthly"] as ChartMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setChartMode(mode)}
                  style={{
                    minWidth: mode === "intraday" ? "56px" : "44px",
                    height: "32px",
                    padding: "0 12px",
                    border: `1px solid ${chartMode === mode ? palette.accent : palette.border}`,
                    background: chartMode === mode ? "#1a2740" : palette.panelSoft,
                    color: chartMode === mode ? palette.text : palette.muted,
                    fontWeight: 700,
                    fontSize: "13px",
                    lineHeight: 1,
                    whiteSpace: "nowrap",
                    wordBreak: "keep-all",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flex: "0 0 auto",
                    fontFamily:
                      '"Noto Sans TC","Microsoft JhengHei","PingFang TC","Heiti TC",system-ui,sans-serif',
                    letterSpacing: 0,
                    cursor: "pointer",
                    borderRadius: "6px",
                  }}
                >
                  {chartModeLabel(mode)}
                </button>
              ))}
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateRows: "minmax(0, 1fr) 64px",
                gap: "6px",
                minHeight: 0,
                background: palette.panelSoft,
                border: `1px solid ${palette.border}`,
                padding: "8px",
              }}
            >
              <div style={{ position: "relative", minHeight: 0 }}>
                <div ref={mainHostRef} style={{ width: "100%", height: "100%" }} />
                {chartMode !== "intraday" ? (
                  <div
                    style={{
                      position: "absolute",
                      left: 8,
                      top: 6,
                      display: "flex",
                      gap: "10px",
                      fontSize: "11px",
                      ...mono,
                    }}
                  >
                    <span style={{ color: "#ffbd2e" }}>MA5</span>
                    <span style={{ color: "#3aa0ff" }}>MA10</span>
                    <span style={{ color: "#b088ff" }}>MA20</span>
                  </div>
                ) : null}
                {displayChartMessage ? (
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      display: "grid",
                      placeItems: "center",
                      color: palette.muted,
                      fontSize: "14px",
                    }}
                  >
                    {displayChartMessage}
                  </div>
                ) : null}
              </div>
              <div ref={volumeHostRef} style={{ width: "100%", height: "64px" }} />
            </div>
          </div>

          <div
            style={{
              padding: "10px 14px",
              borderBottom: `1px solid ${palette.border}`,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "10px",
              minHeight: 0,
            }}
          >
            <div
              style={{
                minHeight: 0,
                border: `1px solid ${palette.border}`,
                background: palette.panelSoft,
                padding: "10px",
                display: "grid",
                gridTemplateRows: "auto auto minmax(0, 1fr)",
                gap: "8px",
              }}
            >
              <SectionTitle title="最佳五檔" subtitle="真實推播五檔，左賣右買。" />
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "52px 1fr 44px 44px 1fr 52px",
                  gap: "6px",
                  fontSize: "11px",
                  color: palette.muted,
                  ...mono,
                }}
              >
                <div style={{ textAlign: "right" }}>賣量</div>
                <div style={{ textAlign: "right" }}>賣價</div>
                <div style={{ textAlign: "center" }}>檔次</div>
                <div style={{ textAlign: "center" }}>檔次</div>
                <div style={{ textAlign: "left" }}>買價</div>
                <div style={{ textAlign: "left" }}>買量</div>
              </div>
              <div style={{ display: "grid", alignContent: "start", minHeight: 0 }}>
                {bestFiveRows.some((row) => row.ask || row.bid) ? (
                  bestFiveRows.map((row, index) => (
                    <div
                      key={`book-${index}`}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "52px 1fr 44px 44px 1fr 52px",
                        gap: "6px",
                        padding: "7px 0",
                        borderTop: index === 0 ? "none" : `1px solid ${palette.border}`,
                        fontSize: "14px",
                        alignItems: "center",
                        ...mono,
                      }}
                    >
                      <div style={{ textAlign: "right", color: palette.text }}>{row.ask ? formatCompact(row.ask.volume) : "--"}</div>
                      <div style={{ textAlign: "right", color: palette.up }}>{row.ask ? formatPrice(row.ask.price) : "--"}</div>
                      <div style={{ textAlign: "center", color: palette.muted }}>{row.ask?.level ?? "--"}</div>
                      <div style={{ textAlign: "center", color: palette.muted }}>{row.bid?.level ?? "--"}</div>
                      <div style={{ textAlign: "left", color: palette.down }}>{row.bid ? formatPrice(row.bid.price) : "--"}</div>
                      <div style={{ textAlign: "left", color: palette.text }}>{row.bid ? formatCompact(row.bid.volume) : "--"}</div>
                    </div>
                  ))
                ) : (
                  <div style={{ color: palette.muted, fontSize: "13px", paddingTop: "12px" }}>尚無五檔資料</div>
                )}
              </div>
            </div>

            <div
              style={{
                minHeight: 0,
                border: `1px solid ${palette.border}`,
                background: palette.panelSoft,
                padding: "10px",
                display: "grid",
                gridTemplateRows: "auto auto minmax(0, 1fr)",
                gap: "8px",
              }}
            >
              <SectionTitle title="分時明細" subtitle="真實逐筆成交，外盤紅、內盤綠。" />
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 72px 56px 48px",
                  gap: "8px",
                  fontSize: "11px",
                  color: palette.muted,
                  ...mono,
                }}
              >
                <div>時間</div>
                <div style={{ textAlign: "right" }}>價格</div>
                <div style={{ textAlign: "right" }}>單量</div>
                <div style={{ textAlign: "right" }}>盤別</div>
              </div>
              <div style={{ display: "grid", alignContent: "start", overflowY: "auto", minHeight: 0 }}>
                {tapeRows.length > 0 ? (
                  tapeRows.map((row, index) => (
                    <div
                      key={`tape-${index}-${row.time}`}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 72px 56px 48px",
                        gap: "8px",
                        padding: "7px 0",
                        borderTop: index === 0 ? "none" : `1px solid ${palette.border}`,
                        fontSize: "14px",
                        alignItems: "center",
                        ...mono,
                      }}
                    >
                      <div>{row.time}</div>
                      <div style={{ textAlign: "right", color: sideColor(row.side) }}>{formatPrice(row.price)}</div>
                      <div style={{ textAlign: "right" }}>{row.volume}</div>
                      <div style={{ textAlign: "right", color: sideColor(row.side) }}>{sideLabel(row.side)}</div>
                    </div>
                  ))
                ) : (
                  <div style={{ color: palette.muted, fontSize: "13px", paddingTop: "12px" }}>尚無逐筆資料</div>
                )}
              </div>
            </div>
          </div>

          <div
            style={{
              padding: "8px 14px",
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: "12px",
              alignItems: "center",
              borderTop: `1px solid ${palette.border}`,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span
                style={{
                  width: "8px",
                  height: "8px",
                  borderRadius: "50%",
                  background: palette.up,
                  display: "inline-block",
                  boxShadow: `0 0 6px ${palette.up}`,
                }}
              />
              <span style={{ fontSize: "12px", color: palette.muted }}>
                策略自動執行中 — 所有買賣由後端 AutoTrader 依策略條件觸發
              </span>
            </div>
            <span style={{ fontSize: "11px", color: palette.muted, fontFamily: "monospace" }}>
              {selectedRow?.symbol ?? "—"}
            </span>
          </div>
        </section>
      </div>

      <NewsPanel />
    </div>
  );
}

export default Dashboard;

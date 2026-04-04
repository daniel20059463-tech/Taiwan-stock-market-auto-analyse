import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useConnectionState, useMarketStore, usePortfolio, useSelectedSymbol, useTickDelta } from "../store";
import type { Candle, InstrumentDefinition, SymbolSnapshot, WorkerInboundMessage } from "../types/market";
import { postWorkerMessage } from "../workerBridge";

const palette = {
  bg: "#121212",
  panel: "#1a1a1c",
  panelSoft: "#151517",
  border: "#333333",
  text: "#f0f0f0",
  muted: "#8c8c8c",
  accent: "#00f5ff",
  success: "#00e676",
  warning: "#d4af37",
  danger: "#ff3366",
};

const mono = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums" as const,
};

const sectorMap: Record<string, string> = {
  "01": "水泥工業",
  "02": "食品工業",
  "03": "塑膠工業",
  "04": "紡織纖維",
  "05": "電機機械",
  "06": "電器電纜",
  "08": "玻璃陶瓷",
  "09": "造紙工業",
  "10": "鋼鐵工業",
  "11": "橡膠工業",
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
  "24": "半導體業",
  "25": "電腦週邊",
  "26": "光電業",
  "27": "通信網路業",
  "28": "電子零組件業",
  "29": "電子通路業",
  "30": "資訊服務業",
  "31": "其他電子業",
  "32": "文化創意",
  "33": "農業科技",
  "35": "綠能環保",
  "36": "數位雲端",
  "37": "運動休閒",
  "38": "居家生活",
  "91": "存託憑證",
};

const sectorGroups = [
  {
    label: "全部類別",
    options: [{ value: "All", label: "全部股票" }],
  },
  {
    label: "電子科技",
    options: ["24", "25", "26", "27", "28", "29", "30", "31"].map((code) => ({
      value: code,
      label: sectorMap[code] ?? code,
    })),
  },
  {
    label: "金融與傳產",
    options: ["01", "02", "03", "05", "06", "10", "12", "14", "15", "17", "21", "23"].map((code) => ({
      value: code,
      label: sectorMap[code] ?? code,
    })),
  },
  {
    label: "消費與其他",
    options: ["16", "18", "20", "22", "33", "35", "36", "37", "38", "91"].map((code) => ({
      value: code,
      label: sectorMap[code] ?? code,
    })),
  },
];

type ChartMode = "live" | "history";
type IndicatorKey = "ma5" | "ma20" | "ma60";

function formatPrice(value: number) {
  return new Intl.NumberFormat("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
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
  if (value > 0) return palette.success;
  if (value < 0) return palette.danger;
  return palette.muted;
}

function sectorLabel(sector: string) {
  const name = sectorMap[sector] ?? sector;
  return sector === "All" ? name : `${sector} ${name}`;
}

function ageLabel(ts?: number) {
  if (!ts) return "--";
  const delta = Math.max(0, Date.now() - ts);
  if (delta < 1000) return "剛更新";
  if (delta < 60_000) return `${Math.floor(delta / 1000)} 秒前`;
  return `${Math.floor(delta / 60_000)} 分鐘前`;
}

function processCandles(candles: Candle[]) {
  const keyed = new Map<number, Candle>();
  candles.forEach((candle) => keyed.set(Math.floor(candle.time / 1000), candle));
  return Array.from(keyed.values()).sort((left, right) => Math.floor(left.time / 1000) - Math.floor(right.time / 1000));
}

function smaValue(candles: Candle[], period: number) {
  const normalized = processCandles(candles);
  if (normalized.length < period) return null;
  const window = normalized.slice(-period);
  return Number((window.reduce((sum, candle) => sum + candle.close, 0) / period).toFixed(2));
}

function smaLine(candles: Candle[], period: number) {
  const normalized = processCandles(candles);
  const output: { time: UTCTimestamp; value: number }[] = [];
  let sum = 0;
  for (let index = 0; index < normalized.length; index += 1) {
    sum += normalized[index].close;
    if (index >= period) sum -= normalized[index - period].close;
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

function blockTitle(label: string, subtitle: string) {
  return (
    <div style={{ display: "grid", gap: "6px" }}>
      <div style={{ fontSize: "29px", fontWeight: 800, color: palette.text }}>{label}</div>
      <div style={{ fontSize: "14px", color: palette.muted, lineHeight: 1.6 }}>{subtitle}</div>
    </div>
  );
}

function metricCard(label: string, value: string, color = palette.text) {
  return (
    <div
      style={{
        display: "grid",
        gap: "6px",
        padding: "12px 14px",
        border: `1px solid ${palette.border}`,
        background: palette.panelSoft,
      }}
    >
      <div style={{ fontSize: "13px", color: palette.muted }}>{label}</div>
      <div style={{ fontSize: "18px", fontWeight: 800, color, ...mono }}>{value}</div>
    </div>
  );
}

function infoGroup(title: string, rows: Array<{ label: string; value: string; color?: string }>) {
  return (
    <div style={{ border: `1px solid ${palette.border}`, background: palette.panelSoft, padding: "14px" }}>
      <div style={{ fontSize: "15px", color: palette.text, fontWeight: 700, marginBottom: "12px" }}>{title}</div>
      <div style={{ display: "grid", gap: "8px" }}>
        {rows.map((row) => (
          <div
            key={row.label}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: "12px",
              alignItems: "center",
              borderBottom: `1px solid ${palette.border}`,
              paddingBottom: "7px",
              fontSize: "14px",
            }}
          >
            <span style={{ color: palette.muted }}>{row.label}</span>
            <span style={{ color: row.color ?? palette.text, ...mono }}>{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AccountPanel() {
  const portfolio = usePortfolio();
  const positions = portfolio?.positions ?? [];
  const trades = portfolio?.recentTrades ?? [];

  return (
    <div style={{ display: "grid", gap: "12px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "10px" }}>
        {metricCard("帳本損益", `${portfolio?.totalPnl && portfolio.totalPnl >= 0 ? "+" : ""}${(portfolio?.totalPnl ?? 0).toLocaleString()}`, tone(portfolio?.totalPnl ?? 0))}
        {metricCard("已實現", `${portfolio?.realizedPnl && portfolio.realizedPnl >= 0 ? "+" : ""}${(portfolio?.realizedPnl ?? 0).toLocaleString()}`, tone(portfolio?.realizedPnl ?? 0))}
        {metricCard("未實現", `${portfolio?.unrealizedPnl && portfolio.unrealizedPnl >= 0 ? "+" : ""}${(portfolio?.unrealizedPnl ?? 0).toLocaleString()}`, tone(portfolio?.unrealizedPnl ?? 0))}
      </div>

      <div style={{ display: "grid", gap: "12px", gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
        <div style={{ border: `1px solid ${palette.border}`, background: palette.panelSoft, padding: "14px" }}>
          <div style={{ fontSize: "15px", fontWeight: 700, color: palette.text, marginBottom: "10px" }}>目前持倉</div>
          {positions.length === 0 ? (
            <div style={{ color: palette.muted, fontSize: "14px" }}>目前沒有持倉部位。</div>
          ) : (
            <div style={{ display: "grid", gap: "8px" }}>
              {positions.slice(0, 4).map((position) => (
                <div key={position.symbol} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: "10px", ...mono }}>
                  <span>{position.symbol}</span>
                  <span>{formatPrice(position.currentPrice)}</span>
                  <span style={{ color: tone(position.pct) }}>{formatPct(position.pct)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ border: `1px solid ${palette.border}`, background: palette.panelSoft, padding: "14px" }}>
          <div style={{ fontSize: "15px", fontWeight: 700, color: palette.text, marginBottom: "10px" }}>最近成交</div>
          {trades.length === 0 ? (
            <div style={{ color: palette.muted, fontSize: "14px" }}>尚未出現可回放的模擬成交。</div>
          ) : (
            <div style={{ display: "grid", gap: "8px" }}>
              {trades.slice(-4).reverse().map((trade, index) => (
                <div key={`${trade.symbol}-${trade.ts}-${index}`} style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto", gap: "8px", ...mono }}>
                  <span>{trade.symbol}</span>
                  <span style={{ color: trade.action === "BUY" ? palette.success : palette.danger }}>{trade.action === "BUY" ? "買進" : "賣出"}</span>
                  <span>{formatPrice(trade.price)}</span>
                  <span style={{ color: tone(trade.netPnl) }}>{trade.action === "SELL" ? trade.netPnl.toLocaleString() : "--"}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export interface DashboardProps {
  symbols: string[];
  instruments?: InstrumentDefinition[];
  title?: string;
}

export function Dashboard({ symbols, instruments = [], title = "台股模擬交易雷達" }: DashboardProps) {
  const snapshot = useMarketStore((state) => state.snapshot);
  const selectedSymbol = useSelectedSymbol();
  const setSelectedSymbol = useMarketStore((state) => state.setSelectedSymbol);
  const historyCache = useMarketStore((state) => state.historyCache);
  const sessionCache = useMarketStore((state) => state.sessionCache);
  const setHistoryLoadingSymbol = useMarketStore((state) => state.setHistoryLoadingSymbol);
  const setSessionLoadingSymbol = useMarketStore((state) => state.setSessionLoadingSymbol);
  const connectionState = useConnectionState();
  const portfolio = usePortfolio();
  const liveTick = useTickDelta(selectedSymbol);

  const [search, setSearch] = useState("");
  const [filterKey, setFilterKey] = useState("All");
  const [chartMode, setChartMode] = useState<ChartMode>("live");
  const [indicators, setIndicators] = useState<Record<IndicatorKey, boolean>>({
    ma5: true,
    ma20: true,
    ma60: false,
  });

  const mainHostRef = useRef<HTMLDivElement | null>(null);
  const volumeHostRef = useRef<HTMLDivElement | null>(null);
  const mainChartRef = useRef<IChartApi | null>(null);
  const volumeChartRef = useRef<IChartApi | null>(null);
  const lineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma5Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma60Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const lastBarTimeRef = useRef<number | null>(null);

  const snapshots = useMemo(() => {
    const liveMap = new Map(snapshot?.symbols?.map((item) => [item.symbol, item]) ?? []);
    const source = instruments.length > 0
      ? instruments
      : symbols.map((symbol) => ({
          symbol,
          name: symbol,
          sector: "All",
          previousClose: 0,
          averageVolume: 0,
        }));
    return source.map((instrument) => liveMap.get(instrument.symbol) ?? fallbackSnapshot(instrument));
  }, [instruments, snapshot?.symbols, symbols]);

  const allRows = useMemo(
    () =>
      snapshots.map((row) => ({
        symbol: row.symbol,
        name: row.quote.name,
        sector: row.quote.sector,
        signalLabel: row.signalLabel,
        last: row.quote.last,
        changePct: row.quote.changePct,
        turnover: row.quote.turnover,
      })),
    [snapshots],
  );

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return allRows
      .filter((row) => {
        const matchesFilter = filterKey === "All" ? true : row.sector === filterKey;
        const matchesQuery =
          !query ||
          row.symbol.toLowerCase().includes(query) ||
          row.name.toLowerCase().includes(query) ||
          sectorLabel(row.sector).toLowerCase().includes(query);
        return matchesFilter && matchesQuery;
      })
      .sort((left, right) => Math.abs(right.changePct) * 1000 + right.turnover - (Math.abs(left.changePct) * 1000 + left.turnover));
  }, [allRows, filterKey, search]);

  const preferredSymbol = useMemo(
    () =>
      portfolio?.positions?.[0]?.symbol ??
      portfolio?.recentTrades?.slice(-1)[0]?.symbol ??
      filteredRows[0]?.symbol ??
      allRows[0]?.symbol ??
      "",
    [allRows, filteredRows, portfolio],
  );

  const sectorLeaders = useMemo(() => {
    const groups = new Map<string, { sector: string; count: number; avgChangePct: number; totalTurnover: number; leader: string; name: string }>();
    for (const row of allRows) {
      const current = groups.get(row.sector) ?? {
        sector: row.sector,
        count: 0,
        avgChangePct: 0,
        totalTurnover: 0,
        leader: row.symbol,
        name: row.name,
      };
      current.count += 1;
      current.avgChangePct += row.changePct;
      current.totalTurnover += row.turnover;
      if (Math.abs(row.changePct) >= Math.abs(current.avgChangePct / current.count || 0)) {
        current.leader = row.symbol;
        current.name = row.name;
      }
      groups.set(row.sector, current);
    }
    return Array.from(groups.values())
      .map((group) => ({
        ...group,
        avgChangePct: group.count > 0 ? group.avgChangePct / group.count : 0,
      }))
      .sort((left, right) => Math.abs(right.avgChangePct) - Math.abs(left.avgChangePct))
      .slice(0, 6);
  }, [allRows]);

  useEffect(() => {
    if (!selectedSymbol && preferredSymbol) {
      setSelectedSymbol(preferredSymbol);
    }
  }, [preferredSymbol, selectedSymbol, setSelectedSymbol]);

  useEffect(() => {
    if (selectedSymbol && !allRows.some((row) => row.symbol === selectedSymbol) && preferredSymbol) {
      setSelectedSymbol(preferredSymbol);
    }
  }, [allRows, preferredSymbol, selectedSymbol, setSelectedSymbol]);

  const detailSymbol = selectedSymbol || preferredSymbol;
  const selectedRow = snapshots.find((row) => row.symbol === detailSymbol) ?? snapshots[0] ?? null;
  const selectedQuote = selectedRow?.quote;
  const historyEntry = selectedRow ? historyCache.get(selectedRow.symbol) : undefined;
  const sessionEntry = selectedRow ? sessionCache.get(selectedRow.symbol) : undefined;
  const liveCandles = selectedRow?.candles.length
    ? selectedRow.candles
    : selectedRow
      ? [
          {
            time: selectedQuote?.ts ?? Date.now(),
            open: selectedQuote?.open ?? 0,
            high: selectedQuote?.high ?? 0,
            low: selectedQuote?.low ?? 0,
            close: selectedQuote?.last ?? 0,
            volume: selectedQuote?.volume ?? 0,
          },
        ]
      : [];
  const chartCandles =
    chartMode === "history"
      ? historyEntry?.candles ?? []
      : sessionEntry?.candles?.length
        ? sessionEntry.candles
        : liveCandles;
  const normalizedCandles = processCandles(chartCandles);
  const latestBar = normalizedCandles.at(-1);
  const latestPrice = liveTick?.price ?? selectedQuote?.last ?? 0;
  const latestPct = liveTick?.changePct ?? selectedQuote?.changePct ?? 0;
  const ma5 = smaValue(normalizedCandles, 5);
  const ma20 = smaValue(normalizedCandles, 20);
  const ma60 = smaValue(normalizedCandles, 60);

  useEffect(() => {
    if (!selectedRow || connectionState !== "open") return;
    if (chartMode === "history") {
      if (!historyEntry) {
        setHistoryLoadingSymbol(selectedRow.symbol);
        postWorkerMessage({ type: "LOAD_HISTORY", symbol: selectedRow.symbol, months: 6 } satisfies WorkerInboundMessage);
      }
      return;
    }
    if (!sessionEntry) {
      setSessionLoadingSymbol(selectedRow.symbol);
      postWorkerMessage({ type: "LOAD_SESSION", symbol: selectedRow.symbol, limit: 240 } satisfies WorkerInboundMessage);
    }
  }, [chartMode, connectionState, historyEntry, selectedRow, sessionEntry, setHistoryLoadingSymbol, setSessionLoadingSymbol]);

  useEffect(() => {
    const mainHost = mainHostRef.current;
    const volumeHost = volumeHostRef.current;
    if (!mainHost || !volumeHost) return;

    const mainChart = createChart(mainHost, {
      autoSize: true,
      layout: {
        background: { color: "rgba(0,0,0,0)" },
        textColor: palette.muted,
        fontFamily: '"IBM Plex Sans","Segoe UI",sans-serif',
      },
      grid: {
        vertLines: { color: palette.border },
        horzLines: { color: palette.border },
      },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border, timeVisible: true, secondsVisible: false },
      crosshair: {
        vertLine: { color: "rgba(255,255,255,0.08)" },
        horzLine: { color: "rgba(255,255,255,0.08)" },
      },
    });

    const volumeChart = createChart(volumeHost, {
      autoSize: true,
      layout: {
        background: { color: "rgba(0,0,0,0)" },
        textColor: palette.muted,
        fontFamily: '"IBM Plex Sans","Segoe UI",sans-serif',
      },
      grid: {
        vertLines: { color: palette.border },
        horzLines: { color: palette.border },
      },
      rightPriceScale: {
        borderColor: palette.border,
        scaleMargins: { top: 0.1, bottom: 0.05 },
      },
      timeScale: { borderColor: palette.border, timeVisible: true, secondsVisible: false },
    });

    lineRef.current = mainChart.addLineSeries({
      color: "#2ebdff",
      lineWidth: 2,
      priceLineVisible: true,
      crosshairMarkerVisible: false,
    });
    candleRef.current = mainChart.addCandlestickSeries({
      upColor: palette.success,
      downColor: palette.danger,
      borderVisible: false,
      wickUpColor: palette.success,
      wickDownColor: palette.danger,
    });
    volumeRef.current = volumeChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ma5Ref.current = mainChart.addLineSeries({ color: "#ffbd2e", lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false });
    ma20Ref.current = mainChart.addLineSeries({ color: "#b088ff", lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false });
    ma60Ref.current = mainChart.addLineSeries({ color: "#36cfc9", lineWidth: 1, priceLineVisible: false, crosshairMarkerVisible: false });

    mainChartRef.current = mainChart;
    volumeChartRef.current = volumeChart;

    mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) volumeChart.timeScale().setVisibleLogicalRange(range);
    });
    volumeChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) mainChart.timeScale().setVisibleLogicalRange(range);
    });

    return () => {
      lineRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      ma5Ref.current = null;
      ma20Ref.current = null;
      ma60Ref.current = null;
      mainChartRef.current = null;
      volumeChartRef.current = null;
      volumeChart.remove();
      mainChart.remove();
    };
  }, []);

  useEffect(() => {
    if (!selectedRow || !lineRef.current || !candleRef.current || !volumeRef.current) return;
    const processed = processCandles(normalizedCandles.length ? normalizedCandles : liveCandles);
    const lineData = processed.map((candle) => ({ time: Math.floor(candle.time / 1000) as UTCTimestamp, value: candle.close }));
    const candleData = processed.map((candle) => ({
      time: Math.floor(candle.time / 1000) as UTCTimestamp,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));
    const volumeData = processed.map((candle, index, list) => ({
      time: Math.floor(candle.time / 1000) as UTCTimestamp,
      value: candle.volume,
      color: candle.close >= (list[index - 1]?.close ?? candle.open) ? "#ff6b6b66" : "#22c55e66",
    }));

    lineRef.current.applyOptions({ visible: chartMode === "live" });
    candleRef.current.applyOptions({ visible: chartMode === "history" });
    lineRef.current.setData(chartMode === "live" ? lineData : []);
    candleRef.current.setData(chartMode === "history" ? candleData : []);
    volumeRef.current.setData(volumeData);
    ma5Ref.current?.applyOptions({ visible: indicators.ma5 });
    ma5Ref.current?.setData(indicators.ma5 ? smaLine(processed, 5) : []);
    ma20Ref.current?.applyOptions({ visible: indicators.ma20 });
    ma20Ref.current?.setData(indicators.ma20 ? smaLine(processed, 20) : []);
    ma60Ref.current?.applyOptions({ visible: indicators.ma60 });
    ma60Ref.current?.setData(indicators.ma60 ? smaLine(processed, 60) : []);
    lastBarTimeRef.current = processed.at(-1) ? Math.floor(processed.at(-1)!.time / 1000) : null;
    mainChartRef.current?.timeScale().fitContent();
    volumeChartRef.current?.timeScale().fitContent();
  }, [chartMode, indicators, liveCandles, normalizedCandles, selectedRow]);

  useEffect(() => {
    if (chartMode !== "live" || !liveTick?.activeCandle || !lineRef.current || !volumeRef.current) return;
    const bar = liveTick.activeCandle;
    const time = Math.floor(bar.time / 1000);
    if (lastBarTimeRef.current !== null && time < lastBarTimeRef.current) return;
    lineRef.current.update({ time: time as UTCTimestamp, value: bar.close });
    volumeRef.current.update({
      time: time as UTCTimestamp,
      value: bar.volume,
      color: bar.close >= bar.open ? "#ff6b6b66" : "#22c55e66",
    });
    lastBarTimeRef.current = time;
  }, [chartMode, liveTick]);

  return (
    <div
      style={{
        height: "100%",
        background: palette.bg,
        color: palette.text,
        padding: "18px 24px",
        fontFamily: "var(--font-sans)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        gap: "16px",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(240px, 1fr) minmax(240px, 320px) auto",
          gap: "16px",
          alignItems: "center",
          padding: "16px 20px",
          background: palette.panel,
          border: `1px solid ${palette.border}`,
          boxShadow: `4px 4px 0 ${palette.warning}`,
        }}
      >
        <div style={{ display: "grid", gap: "6px", minWidth: 0 }}>
          <div style={{ fontSize: "13px", color: palette.muted, letterSpacing: "0.14em", textTransform: "uppercase" }}>盤中總控台</div>
          <div style={{ fontSize: "30px", fontWeight: 800, ...mono }}>{title}</div>
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", color: palette.muted, fontSize: "14px" }}>
            <span>全市場掃描</span>
            <span>•</span>
            <span>盤中焦點類股</span>
            <span>•</span>
            <span>單一標的深入觀察</span>
          </div>
        </div>

        <div style={{ display: "grid", minWidth: 0 }}>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜尋代碼 / 名稱 / 類股"
            style={{
              padding: "10px 12px",
              background: "rgba(255,255,255,0.05)",
              border: `1px solid ${palette.border}`,
              color: palette.text,
              fontSize: "14px",
              outline: "none",
              minWidth: 0,
            }}
          />
        </div>

        <div style={{ textAlign: "right", minWidth: 0 }}>
          <div style={{ fontSize: "42px", fontWeight: 800, color: tone(latestPct), ...mono }}>{latestPrice ? formatPrice(latestPrice) : "--"}</div>
          <div style={{ fontSize: "18px", color: tone(latestPct), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {selectedRow ? `${selectedRow.symbol} ${selectedRow.quote.name}` : "請先選擇標的"}
          </div>
        </div>
      </div>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px", gap: "24px", minHeight: 0, overflowY: "auto", paddingRight: "4px", alignItems: "start" }}>
        <div style={{ display: "grid", gap: "18px", alignContent: "start", minWidth: 0 }}>
          <section
            style={{
              background: palette.panel,
              border: `1px solid ${palette.border}`,
              padding: "16px",
              display: "grid",
              gridTemplateRows: "auto auto minmax(0, 1fr)",
              gap: "14px",
              height: "clamp(520px, 62vh, 680px)",
              minWidth: 0,
              overflow: "hidden",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "14px", alignItems: "end", flexWrap: "wrap" }}>
              {blockTitle("全市場機會", "先看漲跌幅與成交量異動，再決定要深入哪一檔。")}
              <div style={{ color: palette.muted, fontSize: "14px" }}>預設標的：持倉 / 最近成交優先</div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: "10px" }}>
              <select
                value={filterKey}
                onChange={(event) => setFilterKey(event.target.value)}
                style={{
                  padding: "10px 12px",
                  background: "rgba(255,255,255,0.05)",
                  border: `1px solid ${palette.border}`,
                  color: palette.text,
                  fontSize: "14px",
                  outline: "none",
                  cursor: "pointer",
                }}
              >
                {sectorGroups.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "10px" }}>
                {metricCard("連線", connectionState === "open" ? "已連線" : connectionState === "reconnecting" ? "重連中" : connectionState === "connecting" ? "連線中" : "待命", connectionState === "open" ? palette.success : palette.warning)}
                {metricCard("追蹤檔數", String(allRows.length))}
                {metricCard("搜尋結果", String(filteredRows.length))}
                {metricCard("資料節流", snapshot?.dropMode ? "保留最新價" : "正常", snapshot?.dropMode ? palette.warning : palette.success)}
              </div>
            </div>

            <div style={{ minHeight: 0, height: "100%", overflowY: "auto", overflowX: "hidden", paddingRight: "6px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: "10px", alignContent: "start" }}>
              {filteredRows.map((row) => (
                <button
                  key={row.symbol}
                  type="button"
                  onClick={() => setSelectedSymbol(row.symbol)}
                  style={{
                    textAlign: "left",
                    display: "grid",
                    gap: "8px",
                    padding: "14px",
                    border: `1px solid ${row.symbol === detailSymbol ? palette.accent : palette.border}`,
                    background: row.symbol === detailSymbol ? "rgba(0,245,255,0.08)" : palette.panelSoft,
                    color: palette.text,
                    cursor: "pointer",
                  }}
                >
                    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "12px", alignItems: "start" }}>
                    <div style={{ display: "grid", gap: "4px", minWidth: 0 }}>
                      <div style={{ fontWeight: 800, fontSize: "18px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {row.symbol} {row.name}
                      </div>
                      <div style={{ color: palette.muted, fontSize: "13px" }}>{sectorLabel(row.sector)}</div>
                    </div>
                    <div style={{ color: tone(row.changePct), fontSize: "18px", fontWeight: 700, ...mono }}>{formatPct(row.changePct)}</div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: "10px", alignItems: "center" }}>
                    <div style={{ color: palette.muted, fontSize: "13px" }}>{row.signalLabel}</div>
                    <div style={{ ...mono, fontSize: "15px" }}>{formatPrice(row.last)}</div>
                    <div style={{ color: palette.muted, ...mono, fontSize: "13px" }}>{formatCompact(row.turnover)}</div>
                  </div>
                </button>
              ))}
              </div>
            </div>
          </section>

          <section style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px", display: "grid", gap: "14px" }}>
            {blockTitle("單一標的盤面", "圖表保留大畫面，方便你在掃完市場後快速深入一檔。")}

            <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 1fr) minmax(280px, auto)", gap: "16px", alignItems: "end" }}>
              <div style={{ display: "grid", gap: "6px", minWidth: 0 }}>
                <h2 style={{ margin: 0, fontSize: "34px", fontWeight: 900, lineHeight: 1.1, wordBreak: "break-word", ...mono }}>
                  {selectedRow ? `${selectedRow.symbol} ${selectedRow.quote.name}` : "請先選擇標的"}
                </h2>
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", color: palette.muted, fontSize: "14px" }}>
                  {selectedQuote ? <span>{sectorLabel(selectedQuote.sector)}</span> : null}
                  {selectedQuote ? <span style={{ color: tone(latestPct), ...mono }}>{formatPrice(latestPrice)}</span> : null}
                  {selectedQuote ? <span style={{ color: tone(latestPct), ...mono }}>{formatPct(latestPct)}</span> : null}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "10px", minWidth: 0 }}>
                <select
                  value={selectedRow?.symbol ?? ""}
                  onChange={(event) => setSelectedSymbol(event.target.value)}
                  style={{
                    width: "100%",
                    minWidth: 0,
                    padding: "10px 12px",
                    border: `1px solid ${palette.border}`,
                    background: "rgba(255,255,255,0.05)",
                    color: palette.text,
                    fontSize: "15px",
                    ...mono,
                  }}
                >
                  {filteredRows.map((row) => (
                    <option key={row.symbol} value={row.symbol}>
                      {row.symbol} {row.name}
                    </option>
                  ))}
                </select>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(72px, 1fr))", gap: "8px" }}>
                  {(["live", "history"] as ChartMode[]).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setChartMode(mode)}
                      style={{
                        padding: "10px 14px",
                        border: `1px solid ${chartMode === mode ? palette.accent : palette.border}`,
                        background: chartMode === mode ? "rgba(0,245,255,0.1)" : "transparent",
                        color: chartMode === mode ? palette.accent : palette.muted,
                        cursor: "pointer",
                        fontWeight: 700,
                      }}
                    >
                      {mode === "live" ? "即時" : "歷史"}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {(["ma5", "ma20", "ma60"] as IndicatorKey[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setIndicators((previous) => ({ ...previous, [key]: !previous[key] }))}
                  style={{
                    padding: "8px 12px",
                    border: `1px solid ${palette.border}`,
                    background: indicators[key]
                      ? key === "ma5"
                        ? "#ffbd2e"
                        : key === "ma20"
                          ? "#b088ff"
                          : "#36cfc9"
                      : "transparent",
                    color: indicators[key] ? "#000" : palette.muted,
                    cursor: "pointer",
                    fontSize: "13px",
                    ...mono,
                  }}
                >
                  {key.toUpperCase()}
                </button>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateRows: chartMode === "live" ? "360px 92px" : "400px 92px", gap: "8px", background: palette.panelSoft, border: `1px solid ${palette.border}`, padding: "14px" }}>
              <div ref={mainHostRef} style={{ width: "100%", height: chartMode === "live" ? "360px" : "400px" }} />
              <div ref={volumeHostRef} style={{ width: "100%", height: "92px" }} />
            </div>
          </section>
        </div>

        <div style={{ display: "grid", gap: "18px", alignContent: "start", minWidth: 0, position: "sticky", top: 0 }}>
          <section style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px", display: "grid", gap: "12px", minWidth: 0 }}>
            {blockTitle("類股熱度排行", "用類股平均漲跌與資金活躍度，快速找到今天最有聲量的族群。")}
            <div style={{ display: "grid", gap: "10px" }}>
              {sectorLeaders.map((sector, index) => (
                <button
                  key={sector.sector}
                  type="button"
                  onClick={() => setFilterKey(sector.sector)}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "42px 1fr auto",
                    gap: "12px",
                    alignItems: "center",
                    padding: "12px 14px",
                    background: palette.panelSoft,
                    border: `1px solid ${palette.border}`,
                    color: palette.text,
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div
                    style={{
                      width: "42px",
                      height: "42px",
                      display: "grid",
                      placeItems: "center",
                      border: `1px solid ${Math.abs(sector.avgChangePct) >= 1 ? (sector.avgChangePct > 0 ? palette.success : palette.danger) : palette.border}`,
                      color: Math.abs(sector.avgChangePct) >= 1 ? (sector.avgChangePct > 0 ? palette.success : palette.danger) : palette.text,
                      ...mono,
                    }}
                  >
                    {index + 1}
                  </div>
                  <div style={{ display: "grid", gap: "4px", minWidth: 0 }}>
                    <div style={{ fontWeight: 800, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sectorLabel(sector.sector)}</div>
                    <div style={{ color: palette.muted, fontSize: "13px" }}>
                      代表股 {sector.leader} {sector.name} ・ 活躍 {sector.count} 檔
                    </div>
                  </div>
                  <div style={{ textAlign: "right", ...mono }}>
                    <div style={{ color: tone(sector.avgChangePct), fontWeight: 800 }}>{formatPct(sector.avgChangePct)}</div>
                    <div style={{ color: palette.muted, fontSize: "13px" }}>{formatCompact(sector.totalTurnover)}</div>
                  </div>
                </button>
              ))}
            </div>
          </section>

          <section style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px", display: "grid", gap: "12px" }}>
            {blockTitle("標的摘要與帳本", "把價格結構、技術位階和帳本風險集中在右側，一眼就能完成判斷。")}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "10px" }}>
              {metricCard("資料來源", chartMode === "history" ? (historyEntry?.source === "sinopac" ? "永豐歷史日 K" : "即時快照回退") : sessionEntry?.source === "sinopac" ? "永豐即時盤中" : "即時快照", palette.accent)}
              {metricCard("最後更新", ageLabel(selectedQuote?.ts))}
              {metricCard("成交量", formatCompact(selectedQuote?.volume ?? 0))}
              {metricCard("成交額", formatCompact(selectedQuote?.turnover ?? 0))}
            </div>

            {infoGroup("價格結構", [
              { label: "開盤", value: selectedQuote ? formatPrice(selectedQuote.open) : "--" },
              { label: "最新價", value: selectedQuote ? formatPrice(latestPrice) : "--", color: tone(latestPct) },
              { label: "區間高點", value: selectedQuote ? formatPrice(selectedQuote.high) : "--", color: palette.success },
              { label: "區間低點", value: selectedQuote ? formatPrice(selectedQuote.low) : "--", color: palette.danger },
              { label: "距昨收", value: selectedQuote ? formatPrice(latestPrice - selectedQuote.previousClose) : "--", color: tone((latestPrice || 0) - (selectedQuote?.previousClose ?? 0)) },
              { label: "漲跌幅", value: selectedQuote ? formatPct(latestPct) : "--", color: tone(latestPct) },
            ])}

            {infoGroup("技術位階", [
              { label: "MA5", value: ma5 ? formatPrice(ma5) : "--" },
              { label: "MA20", value: ma20 ? formatPrice(ma20) : "--" },
              { label: "MA60", value: ma60 ? formatPrice(ma60) : "--" },
              { label: "K 棒數", value: String(normalizedCandles.length || (selectedRow ? 1 : 0)) },
              { label: "最新 K 棒", value: latestBar ? `${formatPrice(latestBar.open)} → ${formatPrice(latestBar.close)}` : "--", color: latestBar ? tone(latestBar.close - latestBar.open) : palette.text },
              { label: "量能", value: latestBar ? formatCompact(latestBar.volume) : "--" },
            ])}

            <AccountPanel />
          </section>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;

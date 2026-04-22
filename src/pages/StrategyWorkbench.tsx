import {
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, type CSSProperties } from "react";
import { useConnectionState, useMarketStore, usePortfolio, useSelectedSymbol, useTickDelta } from "../store";
import type { Candle, SymbolSnapshot, WorkerInboundMessage } from "../types/market";
import { postWorkerMessage } from "../workerBridge";

const palette = {
  bg: "#121212",
  panel: "#1a1a1c",
  border: "#333333",
  text: "#f0f0f0",
  muted: "#8c8c8c",
  accent: "#00f5ff",
  success: "#00e676",
  warning: "#d4af37",
  danger: "#ff3366",
};

const mono: CSSProperties = { fontFamily: "var(--font-mono)" };
const TOP_CANDIDATE_LIMIT = 20;

interface SignalScore {
  label: string;
  score: number;
  max: number;
  color: string;
  detail: string;
}

interface CandidateSignalData {
  scores: SignalScore[];
  overallPct: number;
  ma5: number | null;
  ma20: number | null;
}

interface StrategyCandidate {
  symbol: string;
  name: string;
  sector: string;
  signalLabel: string;
  last: number;
  changePct: number;
  volume: number;
  candidateScore: number;
  eventScore: number;
  technicalScore: number;
  sectorScore: number;
  riskScore: number;
}

function fmtPrice(value: number): string {
  return new Intl.NumberFormat("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function fmtPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number): string {
  return value > 0 ? palette.success : value < 0 ? palette.danger : palette.muted;
}

function processCandles(candles: Candle[]): Candle[] {
  const map = new Map<number, Candle>();
  for (const candle of candles) {
    map.set(Math.floor(candle.time / 1000), candle);
  }
  return Array.from(map.values()).sort(
    (left, right) => Math.floor(left.time / 1000) - Math.floor(right.time / 1000),
  );
}

function getSma(candles: Candle[], period: number): number | null {
  const normalized = processCandles(candles);
  if (normalized.length < period) {
    return null;
  }
  const window = normalized.slice(-period);
  return window.reduce((sum, candle) => sum + candle.close, 0) / period;
}

function fallbackCandles(snapshot: SymbolSnapshot | null): Candle[] {
  if (!snapshot) {
    return [];
  }
  if (snapshot.candles.length > 0) {
    return snapshot.candles;
  }
  return [
    {
      time: snapshot.quote.ts || Date.now(),
      open: snapshot.quote.open,
      high: Math.max(snapshot.quote.high, snapshot.quote.last),
      low: Math.min(snapshot.quote.low, snapshot.quote.last),
      close: snapshot.quote.last,
      volume: snapshot.quote.volume,
    },
  ];
}

function buildSignalScores(args: {
  selectedSymbol: string;
  selectedSnap: SymbolSnapshot | null;
  allSymbols: SymbolSnapshot[];
  displayCandles: Candle[];
  averageVolume: number;
  riskHalted: boolean;
  riskTradeUsage: number;
  positionCount: number;
}): CandidateSignalData {
  const {
    selectedSymbol,
    selectedSnap,
    allSymbols,
    displayCandles,
    averageVolume,
    riskHalted,
    riskTradeUsage,
    positionCount,
  } = args;
  const quote = selectedSnap?.quote;
  const last = quote?.last ?? 0;
  const prevClose = quote?.previousClose ?? 0;
  const changePct = quote?.changePct ?? 0;
  const ma5 = getSma(displayCandles, 5);
  const ma20 = getSma(displayCandles, 20);
  const latestBar = processCandles(displayCandles).at(-1);
  const sectorPeers = allSymbols.filter(
    (row) => row.quote.sector === quote?.sector && row.symbol !== selectedSymbol,
  );
  const sameDirectionPeers = sectorPeers.filter(
    (row) =>
      Math.sign(row.quote.changePct || 0) === Math.sign(changePct) &&
      Math.abs(row.quote.changePct || 0) >= 1,
  );
  const volumeRatio = averageVolume > 0 ? (quote?.volume ?? 0) / averageVolume : 0;
  const intradayRangePct =
    prevClose > 0
      ? (((quote?.high ?? last) - (quote?.low ?? last)) / prevClose) * 100
      : 0;
  const nearHighRatio =
    (quote?.high ?? last) > (quote?.low ?? last)
      ? (last - (quote?.low ?? last)) /
        ((quote?.high ?? last) - (quote?.low ?? last))
      : 0.5;

  const eventScore = Math.min(
    100,
    Math.round(
      Math.abs(changePct) * 11 +
        Math.min(35, volumeRatio * 20) +
        Math.min(20, intradayRangePct * 3),
    ),
  );
  const technicalScore = Math.min(
    100,
    Math.round(
      (ma5 && last >= ma5 ? 35 : 10) +
        (ma20 && last >= ma20 ? 30 : 10) +
        Math.max(0, Math.min(20, nearHighRatio * 20)) +
        (latestBar && latestBar.close >= latestBar.open ? 15 : 5),
    ),
  );
  const sectorScore = Math.min(
    100,
    Math.round(
      Math.min(55, sameDirectionPeers.length * 12) +
        Math.min(
          25,
          sectorPeers.length > 0
            ? (sameDirectionPeers.length / sectorPeers.length) * 45
            : 0,
        ),
    ),
  );
  const riskScore = riskHalted
    ? 0
    : Math.max(20, Math.round(100 - riskTradeUsage * 45 - positionCount * 8));

  return {
    scores: [
      {
        label: "事件強度",
        score: eventScore,
        max: 100,
        color: palette.accent,
        detail: selectedSnap?.signalLabel
          ? `目前訊號：${selectedSnap.signalLabel}`
          : "依漲跌幅、量能與區間振幅計算的盤中事件分數",
      },
      {
        label: "技術確認",
        score: technicalScore,
        max: 100,
        color: palette.warning,
        detail: "根據 MA5、MA20、近端高低位置與最新 K 棒狀態綜合評估",
      },
      {
        label: "類股共振",
        score: sectorScore,
        max: 100,
        color: palette.accent,
        detail: `同類股中有 ${sameDirectionPeers.length} 檔與 ${selectedSymbol} 同方向波動`,
      },
      {
        label: "風控放行",
        score: riskScore,
        max: 100,
        color: palette.success,
        detail: riskHalted
          ? "目前風控暫停交易，僅保留觀察"
          : `目前持倉 ${positionCount} 檔，風控仍允許新訊號進場`,
      },
    ],
    overallPct: Math.round((eventScore + technicalScore + sectorScore + riskScore) / 4),
    ma5,
    ma20,
  };
}

function buildStrategyCandidates(
  allSymbols: SymbolSnapshot[],
  riskHalted: boolean,
  riskTradeUsage: number,
  positionCount: number,
): StrategyCandidate[] {
  return allSymbols
    .map((row) => {
      const candles = fallbackCandles(row);
      const averageVolume =
        candles.length > 0
          ? candles.reduce((sum, candle) => sum + candle.volume, 0) / candles.length
          : row.quote.volume;
      const metrics = buildSignalScores({
        selectedSymbol: row.symbol,
        selectedSnap: row,
        allSymbols,
        displayCandles: candles,
        averageVolume,
        riskHalted,
        riskTradeUsage,
        positionCount,
      });
      const candidateScore = Math.round(
        metrics.scores[0].score * 0.35 +
          metrics.scores[1].score * 0.3 +
          metrics.scores[2].score * 0.2 +
          metrics.scores[3].score * 0.15,
      );
      return {
        symbol: row.symbol,
        name: row.quote.name,
        sector: row.quote.sector,
        signalLabel: row.signalLabel,
        last: row.quote.last,
        changePct: row.quote.changePct,
        volume: row.quote.volume,
        candidateScore,
        eventScore: metrics.scores[0].score,
        technicalScore: metrics.scores[1].score,
        sectorScore: metrics.scores[2].score,
        riskScore: metrics.scores[3].score,
      };
    })
    .sort((left, right) => {
      if (right.candidateScore !== left.candidateScore) {
        return right.candidateScore - left.candidateScore;
      }
      if (Math.abs(right.changePct) !== Math.abs(left.changePct)) {
        return Math.abs(right.changePct) - Math.abs(left.changePct);
      }
      return right.volume - left.volume;
    })
    .slice(0, TOP_CANDIDATE_LIMIT);
}

function TechRow({
  label,
  value,
  price,
}: {
  label: string;
  value: number | null;
  price: number;
}) {
  if (!value || !Number.isFinite(value)) {
    return (
      <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: `1px solid ${palette.border}`, ...mono, fontSize: "15px" }}>
        <span style={{ color: palette.muted }}>{label}</span>
        <span style={{ color: palette.muted }}>--</span>
      </div>
    );
  }

  const delta = price - value;
  const pct = value > 0 ? (delta / value) * 100 : 0;

  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: `1px solid ${palette.border}`, ...mono, fontSize: "15px" }}>
      <span style={{ color: palette.muted }}>{label}</span>
      <span style={{ color: palette.text }}>{fmtPrice(value)}</span>
      <span style={{ color: tone(delta) }}>{fmtPct(pct)}</span>
    </div>
  );
}

export function StrategyWorkbench() {
  const snapshot = useMarketStore((state) => state.snapshot);
  const sessionCache = useMarketStore((state) => state.sessionCache);
  const sessionLoading = useMarketStore((state) => state.sessionLoadingSymbol);
  const setSessionLoading = useMarketStore((state) => state.setSessionLoadingSymbol);
  const selectedSymbol = useSelectedSymbol();
  const setSelectedSymbol = useMarketStore((state) => state.setSelectedSymbol);
  const connectionState = useConnectionState();
  const portfolio = usePortfolio();
  const liveTick = useTickDelta(selectedSymbol);

  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const volumeHostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const volumeChartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lastTimeRef = useRef<number | null>(null);

  const allSymbols = snapshot?.symbols ?? [];
  const riskStatus = portfolio?.riskStatus;
  const riskTradeUsage =
    riskStatus && riskStatus.maxPositions > 0
      ? riskStatus.dailyTradeCount / riskStatus.maxPositions
      : 0;

  const rankedCandidates = useMemo(
    () =>
      buildStrategyCandidates(
        allSymbols,
        Boolean(riskStatus?.isHalted || riskStatus?.isWeeklyHalted),
        riskTradeUsage,
        portfolio?.positions.length ?? 0,
      ),
    [
      allSymbols,
      riskStatus?.isHalted,
      riskStatus?.isWeeklyHalted,
      riskTradeUsage,
      portfolio?.positions.length,
    ],
  );

  const heldCandidateSymbol = portfolio?.positions.find((position) =>
    rankedCandidates.some((candidate) => candidate.symbol === position.symbol),
  )?.symbol;
  const effectiveSymbol =
    (selectedSymbol &&
      rankedCandidates.some((candidate) => candidate.symbol === selectedSymbol) &&
      selectedSymbol) ||
    heldCandidateSymbol ||
    rankedCandidates[0]?.symbol ||
    "";

  const selectedSnap =
    allSymbols.find((row) => row.symbol === effectiveSymbol) ?? null;
  const selectedCandidate =
    rankedCandidates.find((candidate) => candidate.symbol === effectiveSymbol) ?? null;
  const sessionEntry = effectiveSymbol ? sessionCache.get(effectiveSymbol) : undefined;
  const liveCandles = fallbackCandles(selectedSnap);
  const displayCandles =
    sessionEntry?.candles.length ? sessionEntry.candles : liveCandles;
  const normalizedCandles = processCandles(displayCandles);
  const lastPrice = liveTick?.price ?? selectedSnap?.quote.last ?? 0;
  const changePct = liveTick?.changePct ?? selectedSnap?.quote.changePct ?? 0;
  const averageVolume =
    normalizedCandles.length > 0
      ? normalizedCandles.reduce((sum, candle) => sum + candle.volume, 0) /
        normalizedCandles.length
      : selectedSnap?.quote.volume ?? 0;

  const signalData = useMemo(
    () =>
      buildSignalScores({
        selectedSymbol: effectiveSymbol,
        selectedSnap,
        allSymbols,
        displayCandles,
        averageVolume,
        riskHalted: Boolean(riskStatus?.isHalted || riskStatus?.isWeeklyHalted),
        riskTradeUsage,
        positionCount: portfolio?.positions.length ?? 0,
      }),
    [
      effectiveSymbol,
      selectedSnap,
      allSymbols,
      displayCandles,
      averageVolume,
      riskStatus?.isHalted,
      riskStatus?.isWeeklyHalted,
      riskTradeUsage,
      portfolio?.positions.length,
    ],
  );

  const positionForSymbol =
    portfolio?.positions.find((position) => position.symbol === effectiveSymbol) ?? null;
  const latestBar = normalizedCandles.at(-1);

  useEffect(() => {
    if (effectiveSymbol && selectedSymbol !== effectiveSymbol) {
      setSelectedSymbol(effectiveSymbol);
    }
  }, [effectiveSymbol, selectedSymbol, setSelectedSymbol]);

  useEffect(() => {
    if (connectionState !== "open" || !effectiveSymbol) {
      return;
    }
    if (sessionEntry && !sessionEntry.error) {
      return;
    }
    setSessionLoading(effectiveSymbol);
    postWorkerMessage({
      type: "LOAD_SESSION",
      symbol: effectiveSymbol,
      limit: 240,
    } satisfies WorkerInboundMessage);
  }, [connectionState, effectiveSymbol, sessionEntry, setSessionLoading]);

  useEffect(() => {
    const chartHost = chartHostRef.current;
    const volumeHost = volumeHostRef.current;
    if (!chartHost || !volumeHost) {
      return;
    }

    const chart = createChart(chartHost, {
      autoSize: true,
      layout: {
        background: { color: "rgba(0,0,0,0)" },
        textColor: palette.muted,
        fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
      },
      grid: {
        vertLines: { color: palette.border },
        horzLines: { color: palette.border },
      },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border, visible: false },
    });

    const volumeChart = createChart(volumeHost, {
      autoSize: true,
      layout: {
        background: { color: "rgba(0,0,0,0)" },
        textColor: palette.muted,
        fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
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

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#00e676",
      downColor: "transparent",
      borderVisible: false,
      wickUpColor: "#00e676",
      wickDownColor: "#ff3366",
    });
    const volumeSeries = volumeChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        volumeChart.timeScale().setVisibleLogicalRange(range);
      }
    });
    volumeChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) {
        chart.timeScale().setVisibleLogicalRange(range);
      }
    });

    chartRef.current = chart;
    volumeChartRef.current = volumeChart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    return () => {
      candleRef.current = null;
      volumeRef.current = null;
      chartRef.current = null;
      volumeChartRef.current = null;
      volumeChart.remove();
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!candleRef.current || !volumeRef.current || normalizedCandles.length === 0) {
      return;
    }

    const candleData: CandlestickData<UTCTimestamp>[] = normalizedCandles.map((candle) => ({
      time: Math.floor(candle.time / 1000) as UTCTimestamp,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));

    const volumeData: HistogramData<UTCTimestamp>[] = normalizedCandles.map((candle, index) => {
      const previous = normalizedCandles[index - 1]?.close ?? candle.open;
      return {
        time: Math.floor(candle.time / 1000) as UTCTimestamp,
        value: candle.volume,
        color: candle.close >= previous ? "#ff6b6b55" : "#22c55e55",
      };
    });

    candleRef.current.setData(candleData);
    volumeRef.current.setData(volumeData);
    lastTimeRef.current = normalizedCandles.at(-1)
      ? Math.floor(normalizedCandles.at(-1)!.time / 1000)
      : null;
    chartRef.current?.timeScale().fitContent();
    volumeChartRef.current?.timeScale().fitContent();
  }, [normalizedCandles, effectiveSymbol]);

  useEffect(() => {
    if (!liveTick?.activeCandle) {
      return;
    }
    const bar = liveTick.activeCandle;
    const time = Math.floor(bar.time / 1000) as UTCTimestamp;
    if (lastTimeRef.current !== null && Number(time) < lastTimeRef.current) {
      return;
    }
    const previous = normalizedCandles.at(-2)?.close ?? bar.open;

    candleRef.current?.update({
      time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    });
    volumeRef.current?.update({
      time,
      value: bar.volume,
      color: bar.close >= previous ? "#ff6b6b55" : "#22c55e55",
    });
    lastTimeRef.current = Number(time);
  }, [liveTick, normalizedCandles]);

  const candidateRows = [
    {
      label: "搶快進場",
      status:
        signalData.overallPct >= 72 &&
        !(riskStatus?.isHalted || riskStatus?.isWeeklyHalted)
          ? "可執行"
          : "先觀察",
      color: signalData.overallPct >= 72 ? palette.success : palette.muted,
      detail: signalData.scores[0]?.detail ?? "尚未形成有效事件優勢",
    },
    {
      label: "技術加碼",
      status: signalData.scores[1]?.score >= 68 ? "可加碼" : "待確認",
      color: signalData.scores[1]?.score >= 68 ? palette.warning : palette.muted,
      detail: `MA5 ${signalData.ma5 ? fmtPrice(signalData.ma5) : "--"} / MA20 ${signalData.ma20 ? fmtPrice(signalData.ma20) : "--"}`,
    },
    {
      label: "放空反手",
      status: changePct <= -2 && signalData.scores[1]?.score <= 45 ? "可留意" : "不啟動",
      color:
        changePct <= -2 && signalData.scores[1]?.score <= 45
          ? palette.danger
          : palette.muted,
      detail: "依跌幅、技術轉弱與風控是否放行決定是否建立空方模擬單",
    },
  ];

  return (
    <div
      style={{
        height: "calc(100vh - 176px)",
        minHeight: "760px",
        background: palette.bg,
        color: palette.text,
        padding: "18px 24px",
        fontFamily: "var(--font-sans)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        gap: "16px",
        boxSizing: "border-box",
      }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "18px", minHeight: 0, height: "100%", flex: 1 }}>
        <section
          style={{
            background: palette.panel,
            border: `1px solid ${palette.border}`,
            padding: "16px",
            display: "grid",
            gridTemplateRows: "auto auto minmax(0, 1fr)",
            gap: "14px",
            minHeight: 0,
            height: "100%",
            overflow: "hidden",
            boxSizing: "border-box",
          }}
        >
          <div>
            <div style={{ fontSize: "14px", color: palette.muted, letterSpacing: "0.14em", textTransform: "uppercase" }}>策略作戰台</div>
            <div style={{ marginTop: "8px", fontSize: "24px", fontWeight: 700 }}>候選排行</div>
            <div style={{ marginTop: "6px", fontSize: "13px", color: palette.muted, lineHeight: 1.5 }}>
              依事件、技術、類股共振與風控分數綜合排序，保留前 20 檔作戰標的。
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "10px" }}>
            <div style={{ border: `1px solid ${palette.border}`, padding: "10px 12px" }}>
              <div style={{ fontSize: "12px", color: palette.muted }}>候選檔數</div>
              <div style={{ marginTop: "6px", fontSize: "24px", fontWeight: 700, ...mono }}>{rankedCandidates.length}</div>
            </div>
            <div style={{ border: `1px solid ${palette.border}`, padding: "10px 12px" }}>
              <div style={{ fontSize: "12px", color: palette.muted }}>優先標的</div>
              <div style={{ marginTop: "6px", fontSize: "18px", fontWeight: 700, ...mono }}>{effectiveSymbol || "--"}</div>
            </div>
          </div>

          <div
            style={{
              overflowY: "auto",
              overflowX: "hidden",
              minHeight: 0,
              height: "100%",
              display: "grid",
              gap: "10px",
              paddingRight: "4px",
              alignContent: "start",
            }}
          >
            {rankedCandidates.map((candidate, index) => {
              const active = candidate.symbol === effectiveSymbol;
              return (
                <button
                  key={candidate.symbol}
                  type="button"
                  data-testid="strategy-candidate-row"
                  onClick={() => setSelectedSymbol(candidate.symbol)}
                  aria-label={`${candidate.symbol} ${candidate.name}`}
                  style={{
                    textAlign: "left",
                    padding: "14px",
                    border: `1px solid ${active ? palette.accent : palette.border}`,
                    background: active ? "rgba(0,245,255,0.08)" : "transparent",
                    color: palette.text,
                    cursor: "pointer",
                    display: "grid",
                    gap: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "12px" }}>
                    <div>
                      <div style={{ fontSize: "18px", fontWeight: 700, ...mono }}>
                        {candidate.symbol} {candidate.name}
                      </div>
                      <div style={{ marginTop: "4px", fontSize: "13px", color: palette.muted }}>
                        第 {index + 1} 名 · 類股 {candidate.sector} · {candidate.signalLabel || "等待行情"}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", ...mono }}>
                      <div style={{ fontSize: "18px", fontWeight: 700 }}>{fmtPrice(candidate.last)}</div>
                      <div style={{ marginTop: "4px", color: tone(candidate.changePct) }}>{fmtPct(candidate.changePct)}</div>
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "8px", ...mono, fontSize: "13px" }}>
                    <span>總分 {candidate.candidateScore}</span>
                    <span>事件 {candidate.eventScore}</span>
                    <span>技術 {candidate.technicalScore}</span>
                    <span>共振 {candidate.sectorScore}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateRows: "auto minmax(0, 1fr)", gap: "18px", minHeight: 0, height: "100%" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "16px", padding: "16px 20px", background: palette.panel, border: `1px solid ${palette.border}`, boxShadow: `4px 4px 0 ${palette.warning}` }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: "14px", color: palette.muted, letterSpacing: "0.14em", textTransform: "uppercase" }}>單一標的盤面</div>
              <h2 style={{ margin: "8px 0 0", fontSize: "30px", fontWeight: 700, ...mono }}>
                {selectedSnap?.quote.name ? `${effectiveSymbol} ${selectedSnap.quote.name}` : effectiveSymbol || "請選擇標的"}
              </h2>
            </div>

            <select
              value={effectiveSymbol}
              onChange={(event) => setSelectedSymbol(event.target.value)}
              style={{ padding: "8px 12px", background: "rgba(255,255,255,0.05)", border: `1px solid ${palette.border}`, color: palette.text, borderRadius: "0", ...mono }}
            >
              {rankedCandidates.map((candidate) => (
                <option key={candidate.symbol} value={candidate.symbol}>
                  {candidate.symbol} {candidate.name}
                </option>
              ))}
            </select>

            <div style={{ textAlign: "right", ...mono }}>
              <div style={{ fontSize: "42px", fontWeight: 700, color: tone(changePct) }}>{lastPrice ? fmtPrice(lastPrice) : "--"}</div>
              <div style={{ fontSize: "22px", color: tone(changePct) }}>{fmtPct(changePct)}</div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: "18px", minHeight: 0 }}>
            <div style={{ display: "grid", gap: "18px", minHeight: 0 }}>
              <div style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "14px" }}>
                <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "10px" }}>
                  盤中 1 分 K
                  {sessionLoading === effectiveSymbol && <span style={{ marginLeft: "10px", color: palette.warning }}>載入中</span>}
                  {sessionEntry?.source === "sinopac" && <span style={{ marginLeft: "10px", color: palette.success }}>永豐盤中</span>}
                </div>
                <div style={{ display: "grid", gridTemplateRows: "340px 90px" }}>
                  <div ref={chartHostRef} style={{ height: "340px", width: "100%" }} />
                  <div ref={volumeHostRef} style={{ height: "90px", width: "100%" }} />
                </div>
              </div>

              <div style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px" }}>
                <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>技術位階</div>
                <TechRow label="MA5" value={signalData.ma5} price={lastPrice} />
                <TechRow label="MA20" value={signalData.ma20} price={lastPrice} />
                <TechRow label="昨收" value={selectedSnap?.quote.previousClose ?? null} price={lastPrice} />
                <TechRow label="今開" value={selectedSnap?.quote.open ?? null} price={lastPrice} />
              </div>
            </div>

            <div style={{ display: "grid", gap: "18px", alignContent: "start", minHeight: 0 }}>
              <div style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px" }}>
                <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>策略總分</div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                  <span style={{ fontSize: "42px", fontWeight: 700, color: (selectedCandidate?.candidateScore ?? signalData.overallPct) >= 70 ? palette.success : (selectedCandidate?.candidateScore ?? signalData.overallPct) >= 40 ? palette.warning : palette.danger, ...mono }}>
                    {selectedCandidate?.candidateScore ?? signalData.overallPct}
                  </span>
                  <span style={{ fontSize: "16px", color: palette.muted }}>滿分 100</span>
                </div>
                <div style={{ height: "6px", background: "#333", borderRadius: "3px", overflow: "hidden", marginBottom: "16px" }}>
                  <div style={{ height: "100%", width: `${selectedCandidate?.candidateScore ?? signalData.overallPct}%`, background: (selectedCandidate?.candidateScore ?? signalData.overallPct) >= 70 ? palette.success : (selectedCandidate?.candidateScore ?? signalData.overallPct) >= 40 ? palette.warning : palette.danger, transition: "width 0.4s" }} />
                </div>
                {signalData.scores.map((score) => (
                  <div key={score.label} style={{ marginBottom: "10px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                      <span style={{ fontSize: "15px", color: palette.muted }}>{score.label}</span>
                      <span style={{ fontSize: "15px", color: score.color, ...mono }}>
                        {score.score} / {score.max}
                      </span>
                    </div>
                    <div style={{ height: "3px", background: "#333", borderRadius: "2px", overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${(score.score / score.max) * 100}%`, background: score.color }} />
                    </div>
                    <div style={{ fontSize: "13px", color: palette.muted, marginTop: "4px", lineHeight: 1.5 }}>{score.detail}</div>
                  </div>
                ))}
              </div>

              <div style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px" }}>
                <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>持倉摘要</div>
                {positionForSymbol ? (
                  <div style={{ display: "grid", gap: "8px", ...mono, fontSize: "18px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: palette.muted }}>進場價</span>
                      <span>{fmtPrice(positionForSymbol.entryPrice)}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: palette.muted }}>現價</span>
                      <span style={{ color: tone(positionForSymbol.pct) }}>{fmtPrice(positionForSymbol.currentPrice)}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: palette.muted }}>報酬率</span>
                      <span style={{ color: tone(positionForSymbol.pct), fontWeight: 700 }}>{fmtPct(positionForSymbol.pct)}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: palette.muted }}>股數</span>
                      <span>{positionForSymbol.shares.toLocaleString()}</span>
                    </div>
                  </div>
                ) : (
                  <div style={{ color: palette.muted, fontSize: "16px", padding: "14px 0", textAlign: "center" }}>目前沒有這檔標的的持倉。</div>
                )}
              </div>

              <div style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px" }}>
                <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>候選執行狀態</div>
                {candidateRows.map((row) => (
                  <div key={row.label} style={{ display: "grid", gap: "4px", padding: "8px 0", borderBottom: `1px solid ${palette.border}` }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "15px" }}>
                      <span style={{ color: palette.muted }}>{row.label}</span>
                      <span style={{ color: row.color, fontWeight: 700 }}>{row.status}</span>
                    </div>
                    <div style={{ color: palette.muted, fontSize: "13px", lineHeight: 1.5 }}>{row.detail}</div>
                  </div>
                ))}
                <div style={{ marginTop: "12px", fontSize: "13px", color: palette.muted }}>
                  最新訊號：{selectedSnap?.signalLabel ?? "尚未形成事件訊號"}
                  {latestBar ? `，最新 K 棒 ${fmtPrice(latestBar.open)} → ${fmtPrice(latestBar.close)}` : ""}
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

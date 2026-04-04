/// <reference lib="webworker" />

import type {
  AggregatedSnapshot,
  Candle,
  ConnectionState,
  InstrumentDefinition,
  QuoteSnapshot,
  SymbolSnapshot,
  Tick,
  WorkerInboundMessage,
  WorkerOutboundMessage,
} from "../types/market";

declare const self: DedicatedWorkerGlobalScope;

const textDecoder = new TextDecoder();

class RingBuffer<T> {
  private readonly capacity: number;
  private readonly values: T[];
  private head = 0;
  private length = 0;

  constructor(capacity: number) {
    this.capacity = Math.max(1, capacity);
    this.values = new Array<T>(this.capacity);
  }

  push(value: T): void {
    this.values[this.head] = value;
    this.head = (this.head + 1) % this.capacity;
    this.length = Math.min(this.length + 1, this.capacity);
  }

  toArray(): T[] {
    const output = new Array<T>(this.length);
    for (let index = 0; index < this.length; index += 1) {
      const bufferIndex = (this.head - this.length + index + this.capacity) % this.capacity;
      output[index] = this.values[bufferIndex]!;
    }
    return output;
  }
}

interface SymbolStore {
  symbol: string;
  quote: QuoteSnapshot;
  candles: RingBuffer<Candle>;
  activeCandle: Candle | null;
  signalLabel: string;
}

interface SimulationState {
  last: number;
  open: number;
  high: number;
  low: number;
  phase: number;
}

interface WorkerConfig {
  url: string;
  symbols: string[];
  instruments: InstrumentDefinition[];
  candleLimit: number;
  flushIntervalMs: number;
  reconnectBaseMs: number;
  reconnectMaxMs: number;
  candleResolutionMs: number;
}

const defaultConfig: WorkerConfig = {
  url: "",
  symbols: [],
  instruments: [],
  candleLimit: 240,
  flushIntervalMs: 250,
  reconnectBaseMs: 500,
  reconnectMaxMs: 8_000,
  candleResolutionMs: 60_000,
};

let config: WorkerConfig = defaultConfig;
let socket: WebSocket | null = null;
let reconnectTimer: number | null = null;
let flushTimer: number | null = null;
let mockTimer: number | null = null;
let reconnectDelayMs = defaultConfig.reconnectBaseMs;
let connectionState: ConnectionState = "idle";
let isStopping = false;
let snapshotSequence = 0;
let unackedSnapshots = 0;
let lastAckAt = Date.now();
let dirtyWhileBackpressured = false;
let droppedTicks = 0;
let mockSymbolCursor = 0;
const historyLoadTokenBySymbol = new Map<string, number>();
const sessionLoadTokenBySymbol = new Map<string, number>();

const symbolStores = new Map<string, SymbolStore>();
const trackedSymbols = new Set<string>();
const instrumentMap = new Map<string, InstrumentDefinition>();
const simulationStates = new Map<string, SimulationState>();

function priceStep(value: number): number {
  if (value < 10) {
    return 0.01;
  }
  if (value < 50) {
    return 0.05;
  }
  if (value < 100) {
    return 0.1;
  }
  if (value < 500) {
    return 0.5;
  }
  if (value < 1_000) {
    return 1;
  }
  return 5;
}

function roundToTick(value: number): number {
  const step = priceStep(value);
  return Math.max(step, Math.round(value / step) * step);
}

function getInstrument(symbol: string): InstrumentDefinition {
  return (
    instrumentMap.get(symbol) ?? {
      symbol,
      name: symbol,
      sector: "Market",
      previousClose: 100,
      averageVolume: 8_000_000,
    }
  );
}

function postStatus(reason?: string): void {
  const message: WorkerOutboundMessage = { type: "STATUS", connectionState, reason };
  self.postMessage(message);
}

function postTickDelta(store: SymbolStore): void {
  const { quote, activeCandle } = store;
  const message: WorkerOutboundMessage = {
    type: "TICK_DELTA",
    symbol: quote.symbol,
    price: quote.last,
    changePct: quote.changePct,
    volume: quote.volume,
    turnover: quote.turnover,
    high: quote.high,
    low: quote.low,
    ts: quote.ts,
    activeCandle: activeCandle ? { ...activeCandle } : null,
  };
  self.postMessage(message);
}

function postHistory(symbol: string, candles: Candle[], source: "sinopac" | "fallback", error?: string): void {
  const message: WorkerOutboundMessage = { type: "HISTORY", symbol, candles, source, error };
  self.postMessage(message);
}

function postSession(symbol: string, candles: Candle[], source: "sinopac" | "fallback", error?: string): void {
  const message: WorkerOutboundMessage = { type: "SESSION", symbol, candles, source, error };
  self.postMessage(message);
}

function updateConnectionState(next: ConnectionState, reason?: string): void {
  connectionState = next;
  postStatus(reason);
}

function currentDropMode(): boolean {
  const ackLagMs = Date.now() - lastAckAt;
  return unackedSnapshots > 0 || ackLagMs > config.flushIntervalMs * 4;
}

function bucketTime(ts: number): number {
  return Math.floor(ts / config.candleResolutionMs) * config.candleResolutionMs;
}

function deriveSignal(quote: QuoteSnapshot): string {
  if (quote.changePct >= 3) {
    return "強勢突破";
  }
  if (quote.changePct <= -3) {
    return "弱勢回落";
  }
  if (Math.abs(quote.changePct) >= 1.2) {
    return "波動擴大";
  }
  if (quote.turnover >= 1_500_000_000) {
    return "量能放大";
  }
  return "盤整觀察";
}

function createQuote(symbol: string, tick: Tick): QuoteSnapshot {
  const instrument = getInstrument(symbol);
  const previousClose = tick.previousClose ?? instrument.previousClose;
  const open = tick.open ?? previousClose;
  const high = tick.high ?? Math.max(open, tick.price);
  const low = tick.low ?? Math.min(open, tick.price);

  return {
    symbol,
    name: tick.name ?? instrument.name,
    sector: tick.sector ?? instrument.sector,
    last: tick.price,
    open,
    high,
    low,
    previousClose,
    change: tick.price - previousClose,
    changePct: previousClose === 0 ? 0 : ((tick.price - previousClose) / previousClose) * 100,
    volume: tick.totalVolume ?? tick.volume,
    turnover: tick.turnover ?? tick.price * tick.volume,
    ts: tick.ts,
    droppedTicks: 0,
  };
}

function seedInstrumentStore(instrument: InstrumentDefinition): void {
  if (symbolStores.has(instrument.symbol)) {
    return;
  }

  const seedTick: Tick = {
    symbol: instrument.symbol,
    name: instrument.name,
    sector: instrument.sector,
    price: instrument.previousClose,
    volume: 0,
    totalVolume: 0,
    ts: Date.now(),
    previousClose: instrument.previousClose,
    open: instrument.previousClose,
    high: instrument.previousClose,
    low: instrument.previousClose,
    turnover: 0,
  };

  symbolStores.set(instrument.symbol, {
    symbol: instrument.symbol,
    quote: createQuote(instrument.symbol, seedTick),
    candles: new RingBuffer<Candle>(config.candleLimit),
    activeCandle: null,
    signalLabel: "等待行情",
  });
}

function getOrCreateStore(tick: Tick): SymbolStore {
  const existing = symbolStores.get(tick.symbol);
  if (existing) {
    return existing;
  }

  const created: SymbolStore = {
    symbol: tick.symbol,
    quote: createQuote(tick.symbol, tick),
    candles: new RingBuffer<Candle>(config.candleLimit),
    activeCandle: null,
    signalLabel: "載入中",
  };
  symbolStores.set(tick.symbol, created);
  return created;
}

function updateStoreFromTick(tick: Tick): void {
  if (trackedSymbols.size > 0 && !trackedSymbols.has(tick.symbol)) {
    return;
  }

  const store = getOrCreateStore(tick);
  const quote = store.quote;
  const isBootstrapTick = quote.ts === tick.ts && quote.last === tick.price && quote.volume === (tick.totalVolume ?? tick.volume);
  const previousClose = tick.previousClose ?? quote.previousClose;
  const turnoverDelta = tick.turnover ?? tick.price * tick.volume;
  const nextVolume =
    tick.totalVolume !== undefined
      ? Math.max(quote.volume, tick.totalVolume)
      : isBootstrapTick
        ? tick.volume
        : quote.volume + tick.volume;

  quote.name = tick.name ?? quote.name;
  quote.sector = tick.sector ?? quote.sector;
  quote.previousClose = previousClose;
  quote.last = tick.price;
  quote.open = tick.open ?? quote.open;
  quote.high = Math.max(quote.high, tick.high ?? tick.price);
  quote.low = Math.min(quote.low, tick.low ?? tick.price);
  quote.volume = nextVolume;
  quote.turnover = isBootstrapTick ? turnoverDelta : quote.turnover + turnoverDelta;
  quote.ts = tick.ts;
  quote.change = tick.price - previousClose;
  quote.changePct = previousClose === 0 ? 0 : (quote.change / previousClose) * 100;
  quote.droppedTicks = droppedTicks;
  store.signalLabel = deriveSignal(quote);

  if (currentDropMode()) {
    droppedTicks += 1;
    quote.droppedTicks = droppedTicks;
    return;
  }

  const candleTs = bucketTime(tick.ts);
  const active = store.activeCandle;
  if (!active || active.time !== candleTs) {
    if (active) {
      store.candles.push(active);
    }
    store.activeCandle = {
      time: candleTs,
      open: tick.price,
      high: tick.price,
      low: tick.price,
      close: tick.price,
      volume: tick.volume,
    };
    postTickDelta(store);
    return;
  }

  active.high = Math.max(active.high, tick.price);
  active.low = Math.min(active.low, tick.price);
  active.close = tick.price;
  active.volume += tick.volume;

  // 高頻指令式更新：每筆 tick 立刻通知主執行緒（脫離 flush 250ms 節拍）
  postTickDelta(store);
}

function toSnapshotSymbol(store: SymbolStore): SymbolSnapshot {
  const candles = store.candles.toArray();
  if (store.activeCandle) {
    candles.push({ ...store.activeCandle });
  }
  return {
    symbol: store.symbol,
    quote: { ...store.quote },
    candles,
    signalLabel: store.signalLabel,
  };
}

function buildSnapshot(): AggregatedSnapshot {
  const symbols = Array.from(symbolStores.values())
    .sort((left, right) => Math.abs(right.quote.turnover) - Math.abs(left.quote.turnover))
    .map(toSnapshotSymbol);

  return {
    snapshotId: ++snapshotSequence,
    emittedAt: Date.now(),
    backlog: unackedSnapshots,
    dropMode: currentDropMode(),
    droppedTicks,
    connectionState,
    symbols,
  };
}

function emitSnapshot(force = false): void {
  if (symbolStores.size === 0) {
    return;
  }

  if (!force && unackedSnapshots > 0) {
    dirtyWhileBackpressured = true;
    return;
  }

  const snapshot = buildSnapshot();
  const message: WorkerOutboundMessage = { type: "SNAPSHOT", snapshot };
  self.postMessage(message);
  unackedSnapshots += 1;
  dirtyWhileBackpressured = false;
}

function buildFallbackHistory(symbol: string): Candle[] {
  const store = symbolStores.get(symbol);
  if (!store) {
    return [];
  }
  const candles = store.candles.toArray();
  if (store.activeCandle) {
    candles.push({ ...store.activeCandle });
  }
  return candles;
}

function readPayloadText(data: string | ArrayBuffer | Blob): Promise<string> {
  if (typeof data === "string") {
    return Promise.resolve(data);
  }
  if (data instanceof ArrayBuffer) {
    return Promise.resolve(textDecoder.decode(data));
  }
  return data.text();
}

function resetTransportTimers(): void {
  if (reconnectTimer !== null) {
    self.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (mockTimer !== null) {
    self.clearInterval(mockTimer);
    mockTimer = null;
  }
}

function scheduleReconnect(): void {
  if (isStopping || reconnectTimer !== null) {
    return;
  }

  updateConnectionState("reconnecting", "socket_closed");
  reconnectTimer = self.setTimeout(() => {
    reconnectTimer = null;
    connectFeed();
  }, reconnectDelayMs);
  reconnectDelayMs = Math.min(reconnectDelayMs * 2, config.reconnectMaxMs);
}

function cleanupSocket(): void {
  if (!socket) {
    return;
  }

  socket.onopen = null;
  socket.onclose = null;
  socket.onmessage = null;
  socket.onerror = null;
  try {
    socket.close();
  } catch {
    // No-op.
  }
  socket = null;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))
      ? Number(value)
      : undefined;
}

function asText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : undefined;
}

function normalizeTickCandidate(candidate: unknown): Tick | null {
  if (!candidate || typeof candidate !== "object") {
    return null;
  }

  const raw = candidate as Record<string, unknown>;
  const symbol = asText(raw.symbol) ?? asText(raw.code) ?? asText(raw.ticker) ?? asText(raw.stock_no);
  const price =
    asNumber(raw.price) ??
    asNumber(raw.last) ??
    asNumber(raw.close) ??
    asNumber(raw.trade_price) ??
    asNumber(raw.deal_price) ??
    asNumber(raw.matchPrice);
  const ts =
    asNumber(raw.ts) ??
    asNumber(raw.timestamp) ??
    asNumber(raw.time) ??
    asNumber(raw.datetime) ??
    asNumber(raw.trade_ts) ??
    Date.now();

  if (!symbol || price === undefined) {
    return null;
  }

  const totalVolume =
    asNumber(raw.totalVolume) ??
    asNumber(raw.total_volume) ??
    asNumber(raw.accVolume) ??
    asNumber(raw.acc_volume) ??
    asNumber(raw.cumulativeVolume) ??
    asNumber(raw.cumulative_volume);

  const volume =
    asNumber(raw.volumeDelta) ??
    asNumber(raw.volume_delta) ??
    asNumber(raw.size) ??
    asNumber(raw.qty) ??
    asNumber(raw.quantity) ??
    asNumber(raw.volume) ??
    totalVolume ??
    0;

  return {
    symbol,
    price,
    volume,
    ts,
    totalVolume,
    previousClose: asNumber(raw.previousClose) ?? asNumber(raw.previous_close) ?? asNumber(raw.referencePrice) ?? asNumber(raw.reference_price),
    open: asNumber(raw.open),
    high: asNumber(raw.high),
    low: asNumber(raw.low),
    turnover: asNumber(raw.turnover) ?? asNumber(raw.amount) ?? asNumber(raw.trade_value),
    name: asText(raw.name),
    sector: asText(raw.sector),
  };
}

function normalizeParsedPayload(parsed: unknown): Tick[] {
  if (Array.isArray(parsed)) {
    return parsed.map(normalizeTickCandidate).filter((tick): tick is Tick => tick !== null);
  }

  if (!parsed || typeof parsed !== "object") {
    return [];
  }

  const raw = parsed as Record<string, unknown>;
  const nestedCollections = [raw.data, raw.payload, raw.quote, raw.quotes, raw.tick, raw.ticks, raw.snapshot, raw.snapshots];
  for (const nested of nestedCollections) {
    if (Array.isArray(nested)) {
      return nested.map(normalizeTickCandidate).filter((tick): tick is Tick => tick !== null);
    }
    const single = normalizeTickCandidate(nested);
    if (single) {
      return [single];
    }
  }

  const direct = normalizeTickCandidate(raw);
  return direct ? [direct] : [];
}

function parsePayload(rawText: string): Tick[] {
  try {
    const parsed = JSON.parse(rawText) as unknown;
    return normalizeParsedPayload(parsed);
  } catch {
    return [];
  }
}

async function handleSocketPayload(data: string | ArrayBuffer | Blob): Promise<void> {
  const rawText = await readPayloadText(data);
  try {
    const parsed = JSON.parse(rawText) as {
      type?: string;
      symbol?: string;
      candles?: Candle[];
      source?: "sinopac" | "fallback";
      error?: string;
    };
    if (parsed && typeof parsed === "object" && parsed.type === "PAPER_PORTFOLIO") {
      self.postMessage(parsed as WorkerOutboundMessage);
      return;
    }
    if (parsed && typeof parsed === "object" && (parsed.type === "SESSION_BARS" || parsed.type === "HISTORY_BARS") && typeof parsed.symbol === "string" && Array.isArray(parsed.candles)) {
      const candles = parsed.candles
        .map((candle) => {
          if (!candle || typeof candle !== "object") {
            return null;
          }
          const rawCandle = candle as unknown as Record<string, unknown>;
          const time = asNumber(rawCandle.time);
          const open = asNumber(rawCandle.open);
          const high = asNumber(rawCandle.high);
          const low = asNumber(rawCandle.low);
          const close = asNumber(rawCandle.close);
          const volume = asNumber(rawCandle.volume) ?? 0;
          if (time === undefined || open === undefined || high === undefined || low === undefined || close === undefined) {
            return null;
          }
          return { time, open, high, low, close, volume } satisfies Candle;
        })
        .filter((candle): candle is Candle => candle !== null);
      if (parsed.type === "SESSION_BARS") {
        postSession(parsed.symbol, candles, parsed.source === "sinopac" ? "sinopac" : "fallback", parsed.error);
      } else {
        postHistory(parsed.symbol, candles, parsed.source ?? "fallback", parsed.error);
      }
      return;
    }
  } catch {
    // Fall through to tick parsing.
  }

  const ticks = parsePayload(rawText);
  for (const tick of ticks) {
    updateStoreFromTick({
      symbol: tick.symbol,
      price: tick.price,
      volume: typeof tick.volume === "number" ? tick.volume : 0,
      ts: tick.ts,
      totalVolume: typeof tick.totalVolume === "number" ? tick.totalVolume : undefined,
      previousClose: typeof tick.previousClose === "number" ? tick.previousClose : undefined,
      open: typeof tick.open === "number" ? tick.open : undefined,
      high: typeof tick.high === "number" ? tick.high : undefined,
      low: typeof tick.low === "number" ? tick.low : undefined,
      turnover: typeof tick.turnover === "number" ? tick.turnover : undefined,
      name: typeof tick.name === "string" ? tick.name : undefined,
      sector: typeof tick.sector === "string" ? tick.sector : undefined,
    });
  }
}

function loadSession(symbol: string, limit = 240): void {
  const token = (sessionLoadTokenBySymbol.get(symbol) ?? 0) + 1;
  sessionLoadTokenBySymbol.set(symbol, token);

  if (config.url.startsWith("mock://")) {
    postSession(symbol, buildFallbackHistory(symbol), "fallback");
    return;
  }

  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "session_bars", symbol, limit }));
    return;
  }

  postSession(symbol, buildFallbackHistory(symbol), "fallback", "session_socket_unavailable");
}

async function loadHistory(symbol: string, months = 6): Promise<void> {
  const token = (historyLoadTokenBySymbol.get(symbol) ?? 0) + 1;
  historyLoadTokenBySymbol.set(symbol, token);

  if (config.url.startsWith("mock://")) {
    postHistory(symbol, buildFallbackHistory(symbol), "fallback");
    return;
  }

  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "history_bars", symbol, months }));
    return;
  }

  if (historyLoadTokenBySymbol.get(symbol) !== token) {
    return;
  }

  const fallback = buildFallbackHistory(symbol);
  postHistory(symbol, fallback, "fallback", "history_socket_unavailable");
}

function getSimulationState(instrument: InstrumentDefinition): SimulationState {
  const existing = simulationStates.get(instrument.symbol);
  if (existing) {
    return existing;
  }

  const created: SimulationState = {
    last: instrument.previousClose,
    open: instrument.previousClose,
    high: instrument.previousClose,
    low: instrument.previousClose,
    phase: (Number(instrument.symbol) % 17) / 17,
  };
  simulationStates.set(instrument.symbol, created);
  return created;
}

function buildSimulatedTick(symbol: string, now: number): Tick {
  const instrument = getInstrument(symbol);
  const state = getSimulationState(instrument);
  const cycle = Math.sin(now / 42_000 + state.phase * Math.PI * 2) * 0.0022;
  const noise = (Math.random() - 0.5) * 0.0038;
  const drift = cycle + noise;
  const floor = instrument.previousClose * 0.91;
  const ceiling = instrument.previousClose * 1.09;
  const nextPrice = roundToTick(Math.min(ceiling, Math.max(floor, state.last * (1 + drift))));
  const volume = Math.max(1, Math.round((instrument.averageVolume / 4_800) * (0.45 + Math.random() * 1.35)));
  const turnover = nextPrice * volume;

  state.last = nextPrice;
  state.high = Math.max(state.high, nextPrice);
  state.low = Math.min(state.low, nextPrice);

  return {
    symbol: instrument.symbol,
    name: instrument.name,
    sector: instrument.sector,
    price: nextPrice,
    volume,
    ts: now,
    previousClose: instrument.previousClose,
    open: state.open,
    high: state.high,
    low: state.low,
    turnover,
  };
}

function startMockFeed(): void {
  resetTransportTimers();
  updateConnectionState("open", "mock_feed");

  const activeSymbols = Array.from(trackedSymbols);
  if (activeSymbols.length === 0) {
    return;
  }

  mockTimer = self.setInterval(() => {
    const burst = Math.min(activeSymbols.length, 12);
    const now = Date.now();

    for (let index = 0; index < burst; index += 1) {
      const symbol = activeSymbols[(mockSymbolCursor + index) % activeSymbols.length];
      updateStoreFromTick(buildSimulatedTick(symbol, now + index * 15));
    }

    mockSymbolCursor = (mockSymbolCursor + burst) % activeSymbols.length;
  }, 160);
}

function connectFeed(): void {
  if (isStopping || !config.url) {
    return;
  }

  if (config.url.startsWith("mock://")) {
    startMockFeed();
    return;
  }

  resetTransportTimers();
  cleanupSocket();
  updateConnectionState("connecting");
  socket = new WebSocket(config.url);
  socket.binaryType = "arraybuffer";

  socket.onopen = () => {
    reconnectDelayMs = config.reconnectBaseMs;
    updateConnectionState("open");
    if (trackedSymbols.size > 0) {
      socket?.send(JSON.stringify({ type: "subscribe", symbols: Array.from(trackedSymbols) }));
    }
  };

  socket.onmessage = (event) => {
    void handleSocketPayload(event.data);
  };

  socket.onerror = () => {
    updateConnectionState("error", "socket_error");
  };

  socket.onclose = () => {
    cleanupSocket();
    if (!isStopping) {
      scheduleReconnect();
    }
  };
}

function startFlushLoop(): void {
  if (flushTimer !== null) {
    self.clearInterval(flushTimer);
  }

  flushTimer = self.setInterval(() => {
    emitSnapshot();
  }, config.flushIntervalMs);
}

function stopWorker(): void {
  isStopping = true;
  if (flushTimer !== null) {
    self.clearInterval(flushTimer);
    flushTimer = null;
  }
  resetTransportTimers();
  cleanupSocket();
  updateConnectionState("closed");
  self.close();
}

function applyConfig(message: Extract<WorkerInboundMessage, { type: "INIT" }>): void {
  config = {
    url: message.url,
    symbols: message.symbols,
    instruments: message.instruments ?? [],
    candleLimit: message.candleLimit ?? defaultConfig.candleLimit,
    flushIntervalMs: message.flushIntervalMs ?? defaultConfig.flushIntervalMs,
    reconnectBaseMs: message.reconnectBaseMs ?? defaultConfig.reconnectBaseMs,
    reconnectMaxMs: message.reconnectMaxMs ?? defaultConfig.reconnectMaxMs,
    candleResolutionMs: message.candleResolutionMs ?? defaultConfig.candleResolutionMs,
  };

  trackedSymbols.clear();
  instrumentMap.clear();
  symbolStores.clear();
  simulationStates.clear();

  for (const symbol of config.symbols) {
    trackedSymbols.add(symbol);
  }
  for (const instrument of config.instruments) {
    instrumentMap.set(instrument.symbol, instrument);
    if (trackedSymbols.has(instrument.symbol)) {
      seedInstrumentStore(instrument);
    }
  }

  isStopping = false;
  snapshotSequence = 0;
  unackedSnapshots = 0;
  dirtyWhileBackpressured = false;
  droppedTicks = 0;
  mockSymbolCursor = 0;
  lastAckAt = Date.now();
  reconnectDelayMs = config.reconnectBaseMs;

  connectFeed();
  startFlushLoop();
}

// ── Worker 全域錯誤捕捉 ───────────────────────────────────────────────────────
// 當 Worker 內部發生未處理的同步例外或 Promise rejection 時，
// 通知主執行緒將連線狀態切換為 "error" 並顯示錯誤訊息。

self.addEventListener("error", (event: ErrorEvent) => {
  const reason = event.message ?? "worker_uncaught_error";
  console.error("[data.worker] 未處理的同步錯誤：", event.message, event.error);
  updateConnectionState("error", reason);
});

self.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
  const reason =
    event.reason instanceof Error
      ? event.reason.message
      : String(event.reason ?? "worker_unhandled_rejection");
  console.error("[data.worker] 未處理的 Promise rejection：", event.reason);
  updateConnectionState("error", reason);
  // 避免瀏覽器在 DevTools console 再次印出
  event.preventDefault();
});

self.onmessage = (event: MessageEvent<WorkerInboundMessage>) => {
  const message = event.data;
  switch (message.type) {
    case "INIT":
      applyConfig(message);
      break;
    case "ACK":
      unackedSnapshots = Math.max(0, unackedSnapshots - 1);
      lastAckAt = Date.now();
      if (dirtyWhileBackpressured) {
        emitSnapshot(true);
      }
      break;
    case "SUBSCRIBE":
      trackedSymbols.clear();
      for (const symbol of message.symbols) {
        trackedSymbols.add(symbol);
      }
      if (config.url.startsWith("mock://")) {
        startMockFeed();
      } else if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "subscribe", symbols: message.symbols }));
      }
      break;
    case "STOP":
      stopWorker();
      break;
    case "LOAD_HISTORY":
      void loadHistory(message.symbol, message.months);
      break;
    case "LOAD_SESSION":
      loadSession(message.symbol, message.limit);
      break;
    default:
      break;
  }
};

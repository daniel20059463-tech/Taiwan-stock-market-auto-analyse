export type ConnectionState = "idle" | "connecting" | "open" | "reconnecting" | "closed" | "error";

export interface InstrumentDefinition {
  symbol: string;
  name: string;
  sector: string;
  previousClose: number;
  averageVolume: number;
}

export interface Tick {
  symbol: string;
  price: number;
  volume: number;
  ts: number;
  totalVolume?: number;
  previousClose?: number;
  open?: number;
  high?: number;
  low?: number;
  turnover?: number;
  name?: string;
  sector?: string;
  changePct?: number;
  inTradingHours?: boolean;
  nearLimitUp?: boolean;
  nearLimitDown?: boolean;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface QuoteSnapshot {
  symbol: string;
  name: string;
  sector: string;
  last: number;
  open: number;
  high: number;
  low: number;
  previousClose: number;
  change: number;
  changePct: number;
  volume: number;
  turnover: number;
  ts: number;
  droppedTicks: number;
}

export interface SymbolSnapshot {
  symbol: string;
  quote: QuoteSnapshot;
  candles: Candle[];
  signalLabel: string;
}

export interface AggregatedSnapshot {
  snapshotId: number;
  emittedAt: number;
  backlog: number;
  dropMode: boolean;
  droppedTicks: number;
  connectionState: ConnectionState;
  symbols: SymbolSnapshot[];
}

export interface WorkerInitMessage {
  type: "INIT";
  url: string;
  symbols: string[];
  instruments?: InstrumentDefinition[];
  candleLimit?: number;
  flushIntervalMs?: number;
  reconnectBaseMs?: number;
  reconnectMaxMs?: number;
  candleResolutionMs?: number;
}

export interface WorkerAckMessage {
  type: "ACK";
  snapshotId: number;
}

export interface WorkerStopMessage {
  type: "STOP";
}

export interface WorkerSubscribeMessage {
  type: "SUBSCRIBE";
  symbols: string[];
}

export interface WorkerLoadHistoryMessage {
  type: "LOAD_HISTORY";
  symbol: string;
  months?: number;
}

export interface WorkerLoadSessionMessage {
  type: "LOAD_SESSION";
  symbol: string;
  limit?: number;
}

export type WorkerInboundMessage =
  | WorkerInitMessage
  | WorkerAckMessage
  | WorkerStopMessage
  | WorkerSubscribeMessage
  | WorkerLoadHistoryMessage
  | WorkerLoadSessionMessage;

export interface WorkerSnapshotMessage {
  type: "SNAPSHOT";
  snapshot: AggregatedSnapshot;
}

export interface WorkerStatusMessage {
  type: "STATUS";
  connectionState: ConnectionState;
  reason?: string;
}

export interface WorkerHistoryMessage {
  type: "HISTORY";
  symbol: string;
  candles: Candle[];
  source: "sinopac" | "fallback";
  error?: string;
}

export interface WorkerSessionMessage {
  type: "SESSION";
  symbol: string;
  candles: Candle[];
  source: "sinopac" | "fallback";
  error?: string;
}

export interface RiskStatus {
  date: string;
  dailyPnl: number;
  dailyLossLimit: number;
  isHalted: boolean;
  rolling5DayPnl: number;
  rolling5DayLimit: number;
  isWeeklyHalted: boolean;
  dailyTradeCount: number;
  maxPositions: number;
  maxSinglePosition: number;
  txCostRoundtripPct: number;
}

export interface DecisionFactor {
  kind: "support" | "oppose";
  label: string;
  detail: string;
}

export interface DecisionSourceEvent {
  source: string;
  score?: number;
  price?: number;
  changePct?: number;
  articleId?: string;
  entryPrice?: number;
  currentPrice?: number;
}

export interface DecisionOrderResult {
  status: "executed" | "skipped" | "rejected";
  action?: string;
  price?: number;
  shares?: number;
  pnl?: number;
}

export interface DecisionReport {
  reportId: string;
  symbol: string;
  ts: number;
  decisionType: "buy" | "sell" | "short" | "cover" | "skip";
  triggerType: "news" | "sentiment" | "technical" | "mixed" | "risk";
  confidence: number;
  finalReason: string;
  summary: string;
  supportingFactors: DecisionFactor[];
  opposingFactors: DecisionFactor[];
  riskFlags: string[];
  sourceEvents: DecisionSourceEvent[];
  orderResult: DecisionOrderResult;
  bullCase?: string;
  bearCase?: string;
  riskCase?: string;
  bullArgument?: string;
  bearArgument?: string;
  refereeVerdict?: string;
  debateWinner?: "bull" | "bear" | "tie";
}

export interface PaperPosition {
  symbol: string;
  entryPrice: number;
  currentPrice: number;
  shares: number;
  pnl: number;
  pct: number;
  entryTs: number;
  stopPrice?: number;
  targetPrice?: number;
  trailStopPrice?: number;
}

export interface PaperTrade {
  symbol: string;
  action: "BUY" | "SELL";
  price: number;
  shares: number;
  reason: string;
  netPnl: number;
  grossPnl: number;
  ts: number;
  decisionReport?: DecisionReport | null;
}

export interface PaperPortfolio {
  type: "PAPER_PORTFOLIO";
  positions: PaperPosition[];
  recentTrades: PaperTrade[];
  recentDecisions?: DecisionReport[];
  realizedPnl: number;
  unrealizedPnl: number;
  totalPnl: number;
  tradeCount: number;
  winRate: number;
  marketChangePct: number;
  riskStatus?: RiskStatus;
  sessionId?: string;
}

export interface WorkerPortfolioMessage {
  type: "PAPER_PORTFOLIO";
  positions: PaperPosition[];
  recentTrades: PaperTrade[];
  recentDecisions?: DecisionReport[];
  realizedPnl: number;
  unrealizedPnl: number;
  totalPnl: number;
  tradeCount: number;
  winRate: number;
  marketChangePct: number;
  riskStatus?: RiskStatus;
  sessionId?: string;
}

export interface WorkerTickDeltaMessage {
  type: "TICK_DELTA";
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

export type WorkerOutboundMessage =
  | WorkerSnapshotMessage
  | WorkerStatusMessage
  | WorkerHistoryMessage
  | WorkerSessionMessage
  | WorkerPortfolioMessage
  | WorkerTickDeltaMessage;

/** K 棒快取條目（歷史日K 或盤中分K） */
export interface HistoryCacheEntry {
  candles: Candle[];
  source: "sinopac" | "fallback";
  error?: string;
}

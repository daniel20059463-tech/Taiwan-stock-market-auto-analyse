import type { InstrumentDefinition, PaperTrade } from "../types/market";

export type TradeMonitorRange = "today" | "sevenDays";
export type TradeMonitorFilter = "all" | "entries" | "exits";

export interface TradeMonitorRow extends PaperTrade {
  symbolLabel: string;
  instrumentName: string;
  actionLabel: string;
  direction: "entry" | "exit";
}

interface BuildTradeMonitorRowsParams {
  replayTrades: PaperTrade[];
  recentTrades: PaperTrade[];
  instruments: InstrumentDefinition[];
  range: TradeMonitorRange;
  filter: TradeMonitorFilter;
  query: string;
  nowTs: number;
}

function toTaipeiParts(ts: number): { year: number; month: number; day: number } {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = formatter.formatToParts(new Date(ts));
  return {
    year: Number(parts.find((part) => part.type === "year")?.value ?? 0),
    month: Number(parts.find((part) => part.type === "month")?.value ?? 0),
    day: Number(parts.find((part) => part.type === "day")?.value ?? 0),
  };
}

function isSameTaipeiDay(leftTs: number, rightTs: number): boolean {
  const left = toTaipeiParts(leftTs);
  const right = toTaipeiParts(rightTs);
  return left.year === right.year && left.month === right.month && left.day === right.day;
}

function startOfTaipeiDay(ts: number): number {
  const parts = toTaipeiParts(ts);
  return new Date(`${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}T00:00:00+08:00`).getTime();
}

function tradeKey(trade: PaperTrade): string {
  return [
    trade.symbol,
    trade.action,
    trade.price,
    trade.shares,
    trade.reason,
    trade.netPnl,
    trade.grossPnl,
    trade.ts,
  ].join("|");
}

function getActionLabel(action: PaperTrade["action"]): string {
  switch (action) {
    case "BUY":
      return "買進";
    case "SELL":
      return "賣出";
    case "SHORT":
      return "放空";
    case "COVER":
      return "回補";
    default:
      return action;
  }
}

function includesQuery(trade: PaperTrade, name: string, query: string): boolean {
  if (!query) {
    return true;
  }
  const normalized = query.trim().toLowerCase();
  return trade.symbol.toLowerCase().includes(normalized) || name.toLowerCase().includes(normalized);
}

export function buildTradeMonitorRows(params: BuildTradeMonitorRowsParams): TradeMonitorRow[] {
  const byKey = new Map<string, PaperTrade>();
  for (const trade of [...params.replayTrades, ...params.recentTrades]) {
    byKey.set(tradeKey(trade), trade);
  }

  const earliestTs = startOfTaipeiDay(params.nowTs) - 6 * 24 * 60 * 60 * 1000;

  return Array.from(byKey.values())
    .filter((trade) => {
      if (params.range === "today" && !isSameTaipeiDay(trade.ts, params.nowTs)) {
        return false;
      }
      if (params.range === "sevenDays" && trade.ts < earliestTs) {
        return false;
      }
      if (params.filter === "entries" && !["BUY", "SHORT"].includes(trade.action)) {
        return false;
      }
      if (params.filter === "exits" && !["SELL", "COVER"].includes(trade.action)) {
        return false;
      }
      const instrument = params.instruments.find((item) => item.symbol === trade.symbol);
      const name = instrument?.name ?? "未知標的";
      return includesQuery(trade, name, params.query);
    })
    .sort((left, right) => right.ts - left.ts)
    .map((trade) => {
      const instrument = params.instruments.find((item) => item.symbol === trade.symbol);
      const instrumentName = instrument?.name ?? "未知標的";
      const direction = trade.action === "BUY" || trade.action === "SHORT" ? "entry" : "exit";
      return {
        ...trade,
        instrumentName,
        symbolLabel: `${trade.symbol} ${instrumentName}`,
        actionLabel: getActionLabel(trade.action),
        direction,
      };
    });
}

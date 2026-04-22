export interface BacktestTradeRecord {
  symbol: string;
  action: string;
  price: number;
  shares: number;
  pnl: number;
  reason: string;
}

export interface BacktestLeaderboardItem {
  symbol: string;
  name: string;
  start_date: string;
  end_date: string;
  mode: string;
  total_trades: number;
  win_trades: number;
  loss_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl_per_trade: number;
  max_drawdown_pct: number;
  trade_records: BacktestTradeRecord[];
}

export interface BacktestLeaderboardPayload {
  generated_at: string;
  period: string;
  mode: string;
  results: BacktestLeaderboardItem[];
}

export type BacktestRankingMode = "overall" | "pnl" | "winRate" | "drawdown" | "activity" | "inactive";

export interface BacktestLeaderboardSummary {
  totalSymbols: number;
  profitableSymbols: number;
  inactiveSymbols: number;
  totalTrades: number;
  averageWinRate: number;
  bestSymbol: string | null;
}

export function buildBacktestSummary(payload: BacktestLeaderboardPayload): BacktestLeaderboardSummary {
  const totalSymbols = payload.results.length;
  const profitableSymbols = payload.results.filter((item) => item.total_pnl > 0).length;
  const inactiveSymbols = payload.results.filter((item) => item.total_trades === 0).length;
  const totalTrades = payload.results.reduce((sum, item) => sum + item.total_trades, 0);
  const activeRows = payload.results.filter((item) => item.total_trades > 0);
  const averageWinRate =
    activeRows.length > 0
      ? activeRows.reduce((sum, item) => sum + item.win_rate, 0) / activeRows.length
      : 0;
  const best = [...payload.results].sort((left, right) => right.total_pnl - left.total_pnl)[0] ?? null;

  return {
    totalSymbols,
    profitableSymbols,
    inactiveSymbols,
    totalTrades,
    averageWinRate: Number(averageWinRate.toFixed(1)),
    bestSymbol: best ? `${best.symbol} ${best.name}` : null,
  };
}

export function rankBacktestResults(
  results: BacktestLeaderboardItem[],
  mode: BacktestRankingMode,
  query = "",
): BacktestLeaderboardItem[] {
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = results.filter((item) => {
    if (!normalizedQuery) {
      return true;
    }
    return (
      item.symbol.toLowerCase().includes(normalizedQuery) ||
      item.name.toLowerCase().includes(normalizedQuery)
    );
  });

  const sorted = [...filtered];
  switch (mode) {
    case "overall":
    case "pnl":
      sorted.sort((left, right) => {
        if (right.total_pnl !== left.total_pnl) {
          return right.total_pnl - left.total_pnl;
        }
        return right.win_rate - left.win_rate;
      });
      return sorted;
    case "winRate":
      sorted.sort((left, right) => {
        if ((right.total_trades > 0 ? right.win_rate : -1) !== (left.total_trades > 0 ? left.win_rate : -1)) {
          return (right.total_trades > 0 ? right.win_rate : -1) - (left.total_trades > 0 ? left.win_rate : -1);
        }
        return right.total_pnl - left.total_pnl;
      });
      return sorted.filter((item) => item.total_trades > 0);
    case "drawdown":
      sorted.sort((left, right) => {
        if (left.max_drawdown_pct !== right.max_drawdown_pct) {
          return left.max_drawdown_pct - right.max_drawdown_pct;
        }
        return right.total_pnl - left.total_pnl;
      });
      return sorted.filter((item) => item.total_trades > 0);
    case "activity":
      sorted.sort((left, right) => {
        if (right.total_trades !== left.total_trades) {
          return right.total_trades - left.total_trades;
        }
        return right.total_pnl - left.total_pnl;
      });
      return sorted.filter((item) => item.total_trades > 0);
    case "inactive":
      return sorted.filter((item) => item.total_trades === 0);
    default:
      return sorted;
  }
}

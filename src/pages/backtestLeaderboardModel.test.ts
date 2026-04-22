import { describe, expect, it } from "vitest";
import leaderboard from "../../backtest_results/strong_stocks_intraday.json";
import { buildBacktestSummary, rankBacktestResults } from "./backtestLeaderboardModel";

describe("backtestLeaderboardModel", () => {
  it("builds a summary from the aggregate results", () => {
    const summary = buildBacktestSummary(leaderboard);

    expect(summary.totalSymbols).toBe(11);
    expect(summary.profitableSymbols).toBeGreaterThan(0);
    expect(summary.totalTrades).toBeGreaterThan(0);
    expect(summary.bestSymbol).toBe("4960 誠美材");
  });

  it("sorts pnl ranking descending", () => {
    const ranked = rankBacktestResults(leaderboard.results, "pnl");

    expect(ranked[0]?.symbol).toBe("4960");
    expect(ranked[1]?.symbol).toBe("1802");
  });

  it("filters inactive symbols only", () => {
    const ranked = rankBacktestResults(leaderboard.results, "inactive");

    expect(ranked.every((item) => item.total_trades === 0)).toBe(true);
    expect(ranked.map((item) => item.symbol)).toContain("3231");
  });
});

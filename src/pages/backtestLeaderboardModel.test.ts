import { describe, expect, it } from "vitest";
import leaderboard from "./backtestLeaderboardFixture";
import { buildBacktestSummary, rankBacktestResults } from "./backtestLeaderboardModel";

describe("backtestLeaderboardModel", () => {
  it("builds a summary from the aggregate results", () => {
    const summary = buildBacktestSummary(leaderboard);

    expect(summary.totalSymbols).toBe(3);
    expect(summary.profitableSymbols).toBe(2);
    expect(summary.totalTrades).toBe(7);
    expect(summary.bestSymbol).toBe("4960 誠美材");
  });

  it("sorts pnl ranking descending", () => {
    const ranked = rankBacktestResults(leaderboard.results, "pnl");

    expect(ranked[0]?.symbol).toBe("4960");
    expect(ranked[1]?.symbol).toBe("1802");
  });

  it("filters inactive symbols only", () => {
    const ranked = rankBacktestResults(leaderboard.results, "inactive");

    expect(ranked).toHaveLength(1);
    expect(ranked[0]?.symbol).toBe("3231");
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { useMarketStore } from "../store";
import { TradeMonitor } from "./TradeMonitor";
import { buildTradeMonitorRows } from "./tradeMonitorModel";

const NOW = new Date("2026-04-09T10:30:00+08:00").getTime();

describe("TradeMonitor model", () => {
  it("merges replay trades first and deduplicates duplicate recent trades", () => {
    const rows = buildTradeMonitorRows({
      replayTrades: [
        {
          symbol: "2330",
          action: "BUY",
          price: 100,
          shares: 1000,
          reason: "SIGNAL",
          netPnl: 0,
          grossPnl: 0,
          ts: NOW,
        },
      ],
      recentTrades: [
        {
          symbol: "2330",
          action: "BUY",
          price: 100,
          shares: 1000,
          reason: "SIGNAL",
          netPnl: 0,
          grossPnl: 0,
          ts: NOW,
        },
      ],
      instruments: [{ symbol: "2330", name: "台積電", sector: "24", previousClose: 0, averageVolume: 0 }],
      range: "today",
      filter: "all",
      query: "",
      nowTs: NOW,
    });

    expect(rows).toHaveLength(1);
    expect(rows[0].symbolLabel).toBe("2330 台積電");
    expect(rows[0].actionLabel).toBe("買進");
  });
});

describe("TradeMonitor page", () => {
  beforeEach(() => {
    vi.setSystemTime(NOW);
    useMarketStore.setState((state) => ({
      ...state,
      replayTrades: [
        {
          symbol: "2330",
          action: "BUY",
          price: 1765,
          shares: 1000,
          reason: "SIGNAL",
          netPnl: 0,
          grossPnl: 0,
          ts: NOW - 60_000,
          decisionReport: {
            reportId: "r1",
            symbol: "2330",
            ts: NOW - 60_000,
            decisionType: "buy",
            triggerType: "mixed",
            confidence: 80,
            finalReason: "signal_confirmed",
            summary: "買進訊號成立",
            supportingFactors: [],
            opposingFactors: [],
            riskFlags: [],
            sourceEvents: [],
            orderResult: { status: "executed" },
            bullCase: "多方條件成立",
            bearCase: "空方條件不足",
            riskCase: "風險可控",
            bullArgument: "多方論點",
            bearArgument: "空方論點",
            refereeVerdict: "裁決結論",
            debateWinner: "bull",
          },
        },
        {
          symbol: "2454",
          action: "SELL",
          price: 1778,
          shares: 1000,
          reason: "TAKE_PROFIT",
          netPnl: 11350,
          grossPnl: 11600,
          ts: NOW - 10_000,
        },
      ],
      portfolio: {
        type: "PAPER_PORTFOLIO",
        positions: [],
        recentTrades: [],
        recentDecisions: [],
        realizedPnl: 11350,
        unrealizedPnl: 0,
        totalPnl: 11350,
        tradeCount: 1,
        winRate: 100,
        marketChangePct: 0.6,
      },
    }));
  });

  it("shows trade monitor in navigation", () => {
    render(
      <MemoryRouter>
        <AppShell>
          <div>content</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getAllByText("交易監控").length).toBeGreaterThan(0);
  });

  it("renders timeline rows and shows selected trade detail", () => {
    render(
      <MemoryRouter>
        <TradeMonitor />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("交易監控").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /2454 聯發科/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /2330 台積電/ })).toBeInTheDocument();
    expect(screen.getAllByText("無決策報告").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /2330 台積電/ }));

    expect(screen.getAllByText("多方論點").length).toBeGreaterThan(0);
    expect(screen.getAllByText("裁決結論").length).toBeGreaterThan(0);
  });

  it("filters exit trades only", () => {
    render(
      <MemoryRouter>
        <TradeMonitor />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "只看平倉" }));

    expect(screen.queryByRole("button", { name: /2330 台積電/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /2454 聯發科/ })).toBeInTheDocument();
    expect(screen.getAllByText("賣出").length).toBeGreaterThan(0);
  });
});

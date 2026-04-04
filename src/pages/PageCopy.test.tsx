import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMarketStore } from "../store";
import { Performance } from "./Performance";
import { StrategyConfig } from "./StrategyConfig";
import { TradeReplay } from "./TradeReplay";

const NOW = new Date("2026-04-03T10:30:00+08:00").getTime();

describe("page copy quality", () => {
  beforeEach(() => {
    vi.setSystemTime(NOW);
    useMarketStore.setState({
      connectionState: "open",
      snapshot: null,
      ticks: new Map(),
      portfolio: {
        type: "PAPER_PORTFOLIO",
        positions: [],
        recentTrades: [
          { symbol: "2330", action: "BUY", price: 1765, shares: 1000, reason: "SIGNAL", netPnl: 0, grossPnl: 0, ts: NOW - 60_000 },
          { symbol: "2330", action: "SELL", price: 1778, shares: 1000, reason: "TAKE_PROFIT", netPnl: 11350, grossPnl: 11600, ts: NOW - 10_000 },
        ],
        realizedPnl: 11350,
        unrealizedPnl: 0,
        totalPnl: 11350,
        tradeCount: 1,
        winRate: 100,
        marketChangePct: 0.6,
      },
      replayTrades: [
        { symbol: "2330", action: "BUY", price: 1765, shares: 1000, reason: "SIGNAL", netPnl: 0, grossPnl: 0, ts: NOW - 60_000 },
        { symbol: "2330", action: "SELL", price: 1778, shares: 1000, reason: "TAKE_PROFIT", netPnl: 11350, grossPnl: 11600, ts: NOW - 10_000 },
      ],
      selectedSymbol: "2330",
      historyCache: new Map(),
      sessionCache: new Map(),
      historyLoadingSymbol: null,
      sessionLoadingSymbol: null,
    });
  });

  it("shows clean Chinese copy on the trade replay page", () => {
    render(<TradeReplay />);
    expect(screen.getByText("交易回放")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "播放" })).toBeInTheDocument();
    expect(screen.queryByText(/TODO/i)).not.toBeInTheDocument();
  });

  it("shows an empty replay state for dates without trades", () => {
    render(<TradeReplay />);
    fireEvent.change(screen.getByDisplayValue("2026-04-03"), { target: { value: "2026-03-01" } });
    expect(screen.getAllByText("這一天沒有可回放的交易或事件。")[0]).toBeInTheDocument();
  });

  it("shows an empty replay state when there is no real replay data at all", () => {
    useMarketStore.setState((state) => ({
      ...state,
      portfolio: {
        type: "PAPER_PORTFOLIO",
        positions: [],
        recentTrades: [],
        realizedPnl: 0,
        unrealizedPnl: 0,
        totalPnl: 0,
        tradeCount: 0,
        winRate: 0,
        marketChangePct: 0,
      },
      replayTrades: [],
    }));

    render(<TradeReplay />);
    expect(screen.getAllByText("這一天沒有可回放的交易或事件。")[0]).toBeInTheDocument();
  });

  it("uses persisted replay trades even when the live portfolio is currently empty", () => {
    useMarketStore.setState((state) => ({
      ...state,
      portfolio: {
        type: "PAPER_PORTFOLIO",
        positions: [],
        recentTrades: [],
        realizedPnl: 0,
        unrealizedPnl: 0,
        totalPnl: 0,
        tradeCount: 0,
        winRate: 0,
        marketChangePct: 0,
      },
      replayTrades: [{ symbol: "2330", action: "BUY", price: 1765, shares: 1000, reason: "SIGNAL", netPnl: 0, grossPnl: 0, ts: NOW - 60_000 }],
    }));

    render(<TradeReplay />);
    expect(screen.getByText(/事件清單/)).toBeInTheDocument();
    expect(screen.getByText(/2330 @ 1765.00/)).toBeInTheDocument();
  });

  it("shows real performance metrics without sample placeholders", () => {
    render(<Performance />);
    expect(screen.getByText("績效分析")).toBeInTheDocument();
    expect(screen.getByText("累積損益")).toBeInTheDocument();
    expect(screen.getAllByText("+11,350 元").length).toBeGreaterThan(0);
    expect(screen.queryByText(/樣本/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/TODO/i)).not.toBeInTheDocument();
  });

  it("shows clean Chinese copy on the strategy config page", () => {
    render(<StrategyConfig />);
    expect(screen.getByText("策略設定")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "儲存設定" })).toBeInTheDocument();
    expect(screen.queryByText(/TODO/i)).not.toBeInTheDocument();
  });
});

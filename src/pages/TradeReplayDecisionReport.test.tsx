import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMarketStore } from "../store";
import { TradeReplay } from "./TradeReplay";

const NOW = new Date("2026-04-04T09:35:00+08:00").getTime();

describe("交易回放決策報告", () => {
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
          {
            symbol: "2330",
            action: "BUY",
            price: 101,
            shares: 1000,
            reason: "SIGNAL",
            netPnl: 0,
            grossPnl: 0,
            ts: NOW - 5 * 60_000,
            decisionReport: {
              reportId: "buy-1",
              symbol: "2330",
              ts: NOW - 5 * 60_000,
              decisionType: "buy",
              triggerType: "mixed",
              confidence: 78,
              finalReason: "fast_entry_confirmed",
              summary: "新聞與技術面同向，先以小部位搶快進場。",
              supportingFactors: [
                { kind: "support", label: "價格動能", detail: "盤中漲幅延續，短線買盤仍在推升。" },
                { kind: "support", label: "技術確認", detail: "價格站上 MA5，最新一根 K 棒維持強勢。" },
              ],
              opposingFactors: [
                { kind: "oppose", label: "追價風險", detail: "離日內高點不遠，追價空間開始收斂。" },
              ],
              riskFlags: ["tight_stop"],
              bullCase: "多方觀點：新聞催化仍在延續，量能與價格同步放大，適合先用小部位進場。",
              bearCase: "空方觀點：追價位置偏高，如果量能沒有續強，容易回落洗盤。",
              riskCase: "風控觀點：可進場，但必須維持緊停損與單筆部位限制。",
              bullArgument: "多方論點：事件催化仍在有效時間內，量價配合完整，先搶小部位的勝率較高。",
              bearArgument: "空方論點：目前位置偏高，一旦量縮就可能快速回吐。",
              refereeVerdict: "裁決結論：多方證據略強，但只能採小部位快進快出。",
              debateWinner: "bull",
              sourceEvents: [],
              orderResult: { status: "executed", action: "BUY", price: 101, shares: 1000 },
            },
          },
        ],
        recentDecisions: [],
        realizedPnl: 0,
        unrealizedPnl: 0,
        totalPnl: 0,
        tradeCount: 0,
        winRate: 0,
        marketChangePct: 0.4,
      } as any,
      replayTrades: [
        {
          symbol: "2330",
          action: "BUY",
          price: 101,
          shares: 1000,
          reason: "SIGNAL",
          netPnl: 0,
          grossPnl: 0,
          ts: NOW - 5 * 60_000,
          decisionReport: {
            reportId: "buy-1",
            symbol: "2330",
            ts: NOW - 5 * 60_000,
            decisionType: "buy",
            triggerType: "mixed",
            confidence: 78,
            finalReason: "fast_entry_confirmed",
            summary: "新聞與技術面同向，先以小部位搶快進場。",
            supportingFactors: [
              { kind: "support", label: "價格動能", detail: "盤中漲幅延續，短線買盤仍在推升。" },
              { kind: "support", label: "技術確認", detail: "價格站上 MA5，最新一根 K 棒維持強勢。" },
            ],
            opposingFactors: [
              { kind: "oppose", label: "追價風險", detail: "離日內高點不遠，追價空間開始收斂。" },
            ],
            riskFlags: ["tight_stop"],
            bullCase: "多方觀點：新聞催化仍在延續，量能與價格同步放大，適合先用小部位進場。",
            bearCase: "空方觀點：追價位置偏高，如果量能沒有續強，容易回落洗盤。",
            riskCase: "風控觀點：可進場，但必須維持緊停損與單筆部位限制。",
            bullArgument: "多方論點：事件催化仍在有效時間內，量價配合完整，先搶小部位的勝率較高。",
            bearArgument: "空方論點：目前位置偏高，一旦量縮就可能快速回吐。",
            refereeVerdict: "裁決結論：多方證據略強，但只能採小部位快進快出。",
            debateWinner: "bull",
            sourceEvents: [],
            orderResult: { status: "executed", action: "BUY", price: 101, shares: 1000 },
          },
        } as any,
      ],
      replayDecisions: [
        {
          reportId: "buy-1",
          symbol: "2330",
          ts: NOW - 5 * 60_000,
          decisionType: "buy",
          triggerType: "mixed",
          confidence: 78,
          finalReason: "fast_entry_confirmed",
          summary: "新聞與技術面同向，先以小部位搶快進場。",
          supportingFactors: [
            { kind: "support", label: "價格動能", detail: "盤中漲幅延續，短線買盤仍在推升。" },
            { kind: "support", label: "技術確認", detail: "價格站上 MA5，最新一根 K 棒維持強勢。" },
          ],
          opposingFactors: [
            { kind: "oppose", label: "追價風險", detail: "離日內高點不遠，追價空間開始收斂。" },
          ],
          riskFlags: ["tight_stop"],
          bullCase: "多方觀點：新聞催化仍在延續，量能與價格同步放大，適合先用小部位進場。",
          bearCase: "空方觀點：追價位置偏高，如果量能沒有續強，容易回落洗盤。",
          riskCase: "風控觀點：可進場，但必須維持緊停損與單筆部位限制。",
          bullArgument: "多方論點：事件催化仍在有效時間內，量價配合完整，先搶小部位的勝率較高。",
          bearArgument: "空方論點：目前位置偏高，一旦量縮就可能快速回吐。",
          refereeVerdict: "裁決結論：多方證據略強，但只能採小部位快進快出。",
          debateWinner: "bull",
          sourceEvents: [],
          orderResult: { status: "executed", action: "BUY", price: 101, shares: 1000 },
        },
      ] as any,
      selectedSymbol: "2330",
      historyCache: new Map(),
      sessionCache: new Map(),
      historyLoadingSymbol: null,
      sessionLoadingSymbol: null,
    });
  });

  it("在交易回放頁顯示多角色決策觀點", () => {
    render(<TradeReplay />);

    expect(screen.getByText("決策摘要")).toBeInTheDocument();
    expect(screen.getByText("支持理由")).toBeInTheDocument();
    expect(screen.getByText("反對理由")).toBeInTheDocument();
    expect(screen.getByText("多方觀點")).toBeInTheDocument();
    expect(screen.getByText("空方觀點")).toBeInTheDocument();
    expect(screen.getByText("風控觀點")).toBeInTheDocument();
    expect(screen.getByText("多方論點")).toBeInTheDocument();
    expect(screen.getByText("空方論點")).toBeInTheDocument();
    expect(screen.getByText("裁決結論")).toBeInTheDocument();
    expect(screen.getAllByText("新聞與技術面同向，先以小部位搶快進場。").length).toBeGreaterThan(0);
    expect(screen.getByText("價格動能")).toBeInTheDocument();
    expect(screen.getByText("追價風險")).toBeInTheDocument();
  });
});

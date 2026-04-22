import { useMemo, useState, type CSSProperties } from "react";
import leaderboard from "../../backtest_results/strong_stocks_intraday.json";
import {
  buildBacktestSummary,
  rankBacktestResults,
  type BacktestLeaderboardItem,
  type BacktestRankingMode,
} from "./backtestLeaderboardModel";

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

const rankOptions: Array<{ key: BacktestRankingMode; label: string }> = [
  { key: "overall", label: "總排名" },
  { key: "pnl", label: "獲利排名" },
  { key: "winRate", label: "勝率排名" },
  { key: "drawdown", label: "低回撤排名" },
  { key: "activity", label: "高活躍排名" },
  { key: "inactive", label: "零成交清單" },
];

function formatSigned(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toLocaleString()}`;
}

function SummaryCard({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ border: `1px solid ${palette.border}`, background: "rgba(255,255,255,0.02)", padding: "14px 16px" }}>
      <div style={{ color: palette.muted, fontSize: "12px", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "8px" }}>
        {label}
      </div>
      <div style={{ color: tone ?? palette.text, fontSize: "28px", fontWeight: 800 }}>{value}</div>
    </div>
  );
}

function DetailPanel({ row }: { row: BacktestLeaderboardItem | null }) {
  if (!row) {
    return (
      <aside style={{ border: `1px solid ${palette.border}`, background: palette.panel, padding: "16px" }}>
        <div style={{ color: palette.muted }}>選取一檔股票後，這裡會顯示回測摘要與最近出場原因。</div>
      </aside>
    );
  }

  const reasons = Array.from(
    row.trade_records.reduce((map, trade) => {
      map.set(trade.reason, (map.get(trade.reason) ?? 0) + 1);
      return map;
    }, new Map<string, number>()),
  ).sort((left, right) => right[1] - left[1]);

  return (
    <aside style={{ border: `1px solid ${palette.border}`, background: palette.panel, padding: "16px", display: "grid", gap: "14px" }}>
      <div>
        <div style={{ color: palette.muted, fontSize: "12px", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "8px" }}>
          單檔摘要
        </div>
        <div style={{ fontSize: "30px", fontWeight: 800, color: palette.text }}>
          {row.symbol} {row.name}
        </div>
        <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginTop: "10px", ...mono, color: palette.muted }}>
          <span>
            {row.start_date} {"->"} {row.end_date}
          </span>
          <span>{row.mode}</span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "10px" }}>
        <SummaryCard label="總損益" value={formatSigned(row.total_pnl)} tone={row.total_pnl >= 0 ? palette.success : palette.danger} />
        <SummaryCard label="最大回撤" value={`${row.max_drawdown_pct.toFixed(2)}%`} tone={palette.warning} />
        <SummaryCard label="交易數" value={String(row.total_trades)} />
        <SummaryCard label="勝率" value={`${row.win_rate.toFixed(1)}%`} tone={row.win_rate >= 50 ? palette.success : palette.danger} />
      </div>

      <div style={{ border: `1px solid ${palette.border}`, background: "rgba(255,255,255,0.02)", padding: "14px 16px" }}>
        <div style={{ color: palette.muted, marginBottom: "10px" }}>最近出場原因</div>
        {reasons.length === 0 ? (
          <div style={{ color: palette.muted }}>目前這批回測中沒有出手，這檔沒有可分析的出場原因。</div>
        ) : (
          <div style={{ display: "grid", gap: "8px" }}>
            {reasons.slice(0, 5).map(([reason, count]) => (
              <div key={reason} style={{ display: "flex", justifyContent: "space-between", gap: "12px" }}>
                <span style={{ color: palette.text }}>{reason}</span>
                <span style={{ ...mono, color: palette.muted }}>{count}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

export function BacktestLeaderboard() {
  const [mode, setMode] = useState<BacktestRankingMode>("overall");
  const [query, setQuery] = useState("");
  const summary = useMemo(() => buildBacktestSummary(leaderboard), []);
  const ranked = useMemo(() => rankBacktestResults(leaderboard.results, mode, query), [mode, query]);
  const selected = ranked[0] ?? null;

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, color: palette.text, padding: "24px", fontFamily: "var(--font-sans)" }}>
      <section style={{ padding: "16px 18px", background: palette.panel, border: `1px solid ${palette.border}`, marginBottom: "18px" }}>
        <div style={{ color: palette.muted, fontSize: "12px", letterSpacing: "0.14em", textTransform: "uppercase" }}>Backtest Rankings</div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", alignItems: "end", flexWrap: "wrap", marginTop: "6px" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "34px", fontWeight: 800 }}>回測排行榜</h1>
            <div style={{ marginTop: "8px", color: palette.muted, lineHeight: 1.7 }}>
              直接讀取目前這批回測總表，快速看出哪幾檔最能賺、哪幾檔勝率高、哪幾檔風險最低。
            </div>
          </div>
          <div style={{ display: "grid", gap: "6px", color: palette.muted, ...mono }}>
            <span>期間：{leaderboard.period}</span>
            <span>模式：{leaderboard.mode}</span>
            <span>更新：{new Date(leaderboard.generated_at).toLocaleString("zh-TW", { hour12: false })}</span>
          </div>
        </div>
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: "12px", marginBottom: "18px" }}>
        <SummaryCard label="回測標的" value={String(summary.totalSymbols)} />
        <SummaryCard label="有獲利標的" value={String(summary.profitableSymbols)} tone={palette.success} />
        <SummaryCard label="零成交標的" value={String(summary.inactiveSymbols)} tone={palette.warning} />
        <SummaryCard label="總交易數" value={String(summary.totalTrades)} />
        <SummaryCard label="最佳標的" value={summary.bestSymbol ?? "-"} tone={palette.accent} />
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.7fr) minmax(320px, 0.9fr)", gap: "18px", alignItems: "start" }}>
        <section style={{ background: palette.panel, border: `1px solid ${palette.border}`, minWidth: 0 }}>
          <div style={{ padding: "14px 16px", borderBottom: `1px solid ${palette.border}`, display: "grid", gap: "12px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ fontSize: "24px", fontWeight: 700 }}>{rankOptions.find((item) => item.key === mode)?.label}</div>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜尋代號 / 名稱"
                style={{
                  minWidth: "220px",
                  border: `1px solid ${palette.border}`,
                  background: "rgba(255,255,255,0.04)",
                  color: palette.text,
                  padding: "8px 12px",
                  fontSize: "14px",
                }}
              />
            </div>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {rankOptions.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setMode(item.key)}
                  style={{
                    border: `1px solid ${mode === item.key ? palette.accent : palette.border}`,
                    background: mode === item.key ? "rgba(0,245,255,0.08)" : "rgba(255,255,255,0.04)",
                    color: mode === item.key ? palette.accent : palette.text,
                    cursor: "pointer",
                    padding: "8px 12px",
                    fontSize: "14px",
                    fontWeight: 700,
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div style={{ maxHeight: "calc(100vh - 280px)", overflowY: "auto" }}>
            {ranked.length === 0 ? (
              <div style={{ padding: "16px", color: palette.muted }}>目前這批回測中沒有符合條件的標的。</div>
            ) : (
              ranked.map((row, index) => (
                <div
                  key={row.symbol}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "68px minmax(0, 1.4fr) repeat(4, minmax(88px, 1fr))",
                    gap: "12px",
                    alignItems: "center",
                    padding: "14px 16px",
                    borderBottom: `1px solid ${palette.border}`,
                  }}
                >
                  <div style={{ color: palette.accent, fontWeight: 800, ...mono }}>#{index + 1}</div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: "22px", fontWeight: 800 }}>
                      {row.symbol} {row.name}
                    </div>
                    <div style={{ marginTop: "4px", color: palette.muted }}>
                      {row.total_trades === 0 ? "本期未出手" : `${row.total_trades} 筆交易，${row.win_trades} 勝 ${row.loss_trades} 敗`}
                    </div>
                  </div>
                  <div style={{ ...mono, color: row.total_pnl >= 0 ? palette.success : palette.danger }}>{formatSigned(row.total_pnl)}</div>
                  <div style={{ ...mono }}>{row.win_rate.toFixed(1)}%</div>
                  <div style={{ ...mono, color: palette.warning }}>{row.max_drawdown_pct.toFixed(2)}%</div>
                  <div style={{ ...mono }}>{formatSigned(row.avg_pnl_per_trade)}</div>
                </div>
              ))
            )}
          </div>
        </section>

        <DetailPanel row={selected} />
      </div>
    </div>
  );
}

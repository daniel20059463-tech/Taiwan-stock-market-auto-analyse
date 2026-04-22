import { useMemo, useState, type CSSProperties } from "react";
import { DEFAULT_TW_STOCKS } from "../data/twStocks";
import { usePortfolio, useReplayTrades } from "../store";
import type { DecisionFactor, DecisionReport } from "../types/market";
import { buildTradeMonitorRows, type TradeMonitorFilter, type TradeMonitorRange } from "./tradeMonitorModel";

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

const buttonBaseStyle: CSSProperties = {
  border: `1px solid ${palette.border}`,
  background: "rgba(255,255,255,0.04)",
  color: palette.text,
  cursor: "pointer",
  padding: "8px 12px",
  fontSize: "14px",
};

function formatTimestamp(ts: number): string {
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: "Asia/Taipei",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(ts));
}

function renderFactors(factors: DecisionFactor[] | undefined): string {
  if (!factors || factors.length === 0) {
    return "無決策報告";
  }
  return factors.map((factor) => factor.detail).join("、");
}

function DetailField({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ border: `1px solid ${palette.border}`, padding: "12px 14px", background: "rgba(255,255,255,0.02)" }}>
      <div style={{ color: tone ?? palette.muted, fontSize: "12px", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "8px" }}>
        {label}
      </div>
      <div style={{ color: palette.text, lineHeight: 1.7 }}>{value}</div>
    </div>
  );
}

function DecisionDetails({ report }: { report?: DecisionReport | null }) {
  return (
    <div style={{ display: "grid", gap: "12px" }}>
      <DetailField label="決策摘要" value={report?.finalReason ?? "無決策報告"} tone={palette.accent} />
      <DetailField label="支持理由" value={renderFactors(report?.supportingFactors)} tone={palette.success} />
      <DetailField label="反對理由" value={renderFactors(report?.opposingFactors)} tone={palette.danger} />
      <DetailField label="多方論點" value={report?.bullArgument ?? "無決策報告"} tone={palette.success} />
      <DetailField label="空方論點" value={report?.bearArgument ?? "無決策報告"} tone={palette.danger} />
      <DetailField label="裁決結論" value={report?.refereeVerdict ?? "無決策報告"} tone={palette.warning} />
    </div>
  );
}

export function TradeMonitor() {
  const replayTrades = useReplayTrades();
  const portfolio = usePortfolio();
  const [range, setRange] = useState<TradeMonitorRange>("today");
  const [filter, setFilter] = useState<TradeMonitorFilter>("all");
  const [query, setQuery] = useState("");

  const rows = useMemo(
    () =>
      buildTradeMonitorRows({
        replayTrades,
        recentTrades: portfolio?.recentTrades ?? [],
        instruments: DEFAULT_TW_STOCKS,
        range,
        filter,
        query,
        nowTs: Date.now(),
      }),
    [filter, portfolio?.recentTrades, query, range, replayTrades],
  );

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selected =
    rows.find((row) => `${row.symbol}-${row.action}-${row.ts}` === selectedKey) ?? rows[0] ?? null;

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, color: palette.text, padding: "24px", fontFamily: "var(--font-sans)" }}>
      <section style={{ padding: "16px 18px", background: palette.panel, border: `1px solid ${palette.border}`, marginBottom: "18px" }}>
        <div style={{ color: palette.muted, fontSize: "12px", letterSpacing: "0.14em", textTransform: "uppercase" }}>交易監控</div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", alignItems: "end", flexWrap: "wrap", marginTop: "6px" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: "34px", fontWeight: 800 }}>交易監控</h1>
            <div style={{ marginTop: "8px", color: palette.muted, lineHeight: 1.7 }}>
              只顯示成交與平倉事件，優先使用回放交易紀錄，並在右側顯示單筆決策細節。
            </div>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <button type="button" style={{ ...buttonBaseStyle, background: range === "today" ? palette.accent : buttonBaseStyle.background, color: range === "today" ? "#000" : palette.text }} onClick={() => setRange("today")}>
              今天
            </button>
            <button type="button" style={{ ...buttonBaseStyle, background: range === "sevenDays" ? palette.accent : buttonBaseStyle.background, color: range === "sevenDays" ? "#000" : palette.text }} onClick={() => setRange("sevenDays")}>
              最近 7 天
            </button>
            <button type="button" style={{ ...buttonBaseStyle, background: filter === "all" ? palette.accent : buttonBaseStyle.background, color: filter === "all" ? "#000" : palette.text }} onClick={() => setFilter("all")}>
              全部
            </button>
            <button type="button" style={{ ...buttonBaseStyle, background: filter === "entries" ? palette.accent : buttonBaseStyle.background, color: filter === "entries" ? "#000" : palette.text }} onClick={() => setFilter("entries")}>
              只看成交
            </button>
            <button type="button" style={{ ...buttonBaseStyle, background: filter === "exits" ? palette.accent : buttonBaseStyle.background, color: filter === "exits" ? "#000" : palette.text }} onClick={() => setFilter("exits")}>
              只看平倉
            </button>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜尋代碼或名稱"
              style={{ ...buttonBaseStyle, minWidth: "220px", cursor: "text" }}
            />
          </div>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(320px, 1fr)", gap: "18px", alignItems: "start" }}>
        <section style={{ background: palette.panel, border: `1px solid ${palette.border}`, minWidth: 0 }}>
          <div style={{ padding: "14px 16px", borderBottom: `1px solid ${palette.border}`, display: "flex", justifyContent: "space-between", gap: "12px" }}>
            <div style={{ fontSize: "24px", fontWeight: 700 }}>交易時間線</div>
            <div style={{ color: palette.muted, ...mono }}>{rows.length} 筆</div>
          </div>
          <div style={{ maxHeight: "calc(100vh - 230px)", overflowY: "auto" }}>
            {rows.length === 0 ? (
              <div style={{ padding: "16px", color: palette.muted }}>目前沒有符合條件的成交或平倉事件。</div>
            ) : (
              rows.map((row) => {
                const key = `${row.symbol}-${row.action}-${row.ts}`;
                const active = selected != null && selected.symbol === row.symbol && selected.action === row.action && selected.ts === row.ts;
                const tone = row.direction === "entry" ? palette.success : palette.danger;
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSelectedKey(key)}
                    style={{
                      display: "grid",
                      width: "100%",
                      textAlign: "left",
                      border: 0,
                      borderBottom: `1px solid ${palette.border}`,
                      padding: "14px 16px",
                      background: active ? "rgba(255,255,255,0.05)" : "transparent",
                      color: palette.text,
                      cursor: "pointer",
                      gap: "6px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "baseline" }}>
                      <div style={{ fontSize: "22px", fontWeight: 700 }}>{row.symbolLabel}</div>
                      <div style={{ color: tone, fontWeight: 700 }}>{row.actionLabel}</div>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", color: palette.muted }}>
                      <div>{row.reason}</div>
                      <div style={mono}>{formatTimestamp(row.ts)}</div>
                    </div>
                    <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", ...mono }}>
                      <span>價格 {row.price.toFixed(2)}</span>
                      <span>股數 {row.shares.toLocaleString()}</span>
                      <span style={{ color: row.netPnl >= 0 ? palette.success : palette.danger }}>
                        損益 {row.netPnl >= 0 ? "+" : ""}
                        {row.netPnl.toLocaleString()}
                      </span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        <aside style={{ background: palette.panel, border: `1px solid ${palette.border}`, padding: "16px", display: "grid", gap: "14px" }}>
          <div>
            <div style={{ color: palette.muted, fontSize: "12px", letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: "8px" }}>交易詳情</div>
            {selected ? (
              <>
                <div style={{ fontSize: "28px", fontWeight: 800 }}>{selected.symbolLabel}</div>
                <div style={{ display: "flex", gap: "10px", alignItems: "center", marginTop: "8px", flexWrap: "wrap" }}>
                  <span style={{ color: selected.direction === "entry" ? palette.success : palette.danger, fontWeight: 700 }}>{selected.actionLabel}</span>
                  <span style={{ color: palette.muted, ...mono }}>{formatTimestamp(selected.ts)}</span>
                </div>
                <div style={{ color: palette.text, marginTop: "10px" }}>{selected.reason}</div>
              </>
            ) : (
              <div style={{ color: palette.muted }}>請先從左側時間線選取一筆交易。</div>
            )}
          </div>

          {selected ? <DecisionDetails report={selected.decisionReport} /> : null}
        </aside>
      </div>
    </div>
  );
}

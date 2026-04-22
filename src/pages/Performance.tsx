import { useMemo, type CSSProperties } from "react";
import { usePortfolio, useReplayTrades } from "../store";
import type { PaperTrade } from "../types/market";

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

interface DailyPoint {
  dateKey: string;
  label: string;
  pnl: number;
  trades: number;
  wins: number;
}

function tone(value: number): string {
  if (value > 0) return palette.success;
  if (value < 0) return palette.danger;
  return palette.muted;
}

function formatSigned(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toLocaleString()} 元`;
}

function toDateKey(ts: number): string {
  const date = new Date(ts);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function toDateLabel(ts: number): string {
  return new Date(ts).toLocaleDateString("zh-TW", {
    month: "2-digit",
    day: "2-digit",
  });
}

function buildDailySeries(trades: PaperTrade[]): DailyPoint[] {
  const sellTrades = trades.filter((trade) => trade.action === "SELL");
  const grouped = new Map<string, DailyPoint>();

  for (const trade of sellTrades) {
    const key = toDateKey(trade.ts);
    const current =
      grouped.get(key) ?? {
        dateKey: key,
        label: toDateLabel(trade.ts),
        pnl: 0,
        trades: 0,
        wins: 0,
      };
    current.pnl += trade.netPnl;
    current.trades += 1;
    current.wins += trade.netPnl > 0 ? 1 : 0;
    grouped.set(key, current);
  }

  return Array.from(grouped.values()).sort((left, right) => left.dateKey.localeCompare(right.dateKey));
}

function buildEquityCurve(daily: DailyPoint[]) {
  let equity = 0;
  return daily.map((point) => {
    equity += point.pnl;
    return { label: point.label, equity };
  });
}

function calculateMaxDrawdown(daily: DailyPoint[]): number {
  const curve = buildEquityCurve(daily);
  let peak = 0;
  let worst = 0;

  for (const point of curve) {
    peak = Math.max(peak, point.equity);
    worst = Math.min(worst, point.equity - peak);
  }

  return worst;
}

function KpiCard({
  color,
  label,
  sublabel,
  value,
}: {
  color: string;
  label: string;
  sublabel?: string;
  value: string;
}) {
  return (
    <div style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}` }}>
      <div style={{ fontSize: "14px", color: palette.muted, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
      <div style={{ marginTop: "10px", fontSize: "30px", fontWeight: 700, color, ...mono }}>{value}</div>
      {sublabel && <div style={{ marginTop: "6px", fontSize: "14px", color: palette.muted }}>{sublabel}</div>}
    </div>
  );
}

function DailyBarChart({ daily }: { daily: DailyPoint[] }) {
  if (daily.length === 0) {
    return <div style={{ color: palette.muted, padding: "28px 0" }}>目前還沒有已完成平倉的真實交易，暫時無法生成日別損益柱狀圖。</div>;
  }

  const max = Math.max(1, ...daily.map((point) => Math.abs(point.pnl)));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: "4px", height: "140px" }}>
      {daily.map((point) => (
        <div
          key={point.dateKey}
          title={`${point.label} ${formatSigned(point.pnl)}`}
          style={{
            flex: 1,
            height: `${Math.max(0.05, Math.abs(point.pnl) / max) * 100}%`,
            minWidth: "10px",
            background: point.pnl >= 0 ? palette.success : palette.danger,
            opacity: 0.82,
          }}
        />
      ))}
    </div>
  );
}

function EquityCurveChart({ daily }: { daily: DailyPoint[] }) {
  const points = buildEquityCurve(daily);
  const width = 640;
  const height = 100;

  if (points.length === 0) {
    return <div style={{ color: palette.muted, padding: "28px 0" }}>尚未累積到可計算的權益變化曲線，等有平倉交易後就會自動出現。</div>;
  }

  const min = Math.min(...points.map((point) => point.equity), 0);
  const max = Math.max(...points.map((point) => point.equity), 0);
  const range = max - min || 1;

  const path = points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y = height - ((point.equity - min) / range) * (height - 8) - 4;
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");

  const last = points.at(-1)?.equity ?? 0;

  return (
    <div style={{ position: "relative" }}>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <line
          x1="0"
          x2={width}
          y1={height - ((0 - min) / range) * (height - 8) - 4}
          y2={height - ((0 - min) / range) * (height - 8) - 4}
          stroke={palette.border}
          strokeDasharray="4 4"
        />
        <path d={path} fill="none" stroke={last >= 0 ? palette.success : palette.danger} strokeWidth="2" />
      </svg>
      <div style={{ position: "absolute", top: "8px", right: "12px", color: tone(last), ...mono }}>{formatSigned(last)}</div>
    </div>
  );
}

function TradeTable({ trades }: { trades: PaperTrade[] }) {
  if (trades.length === 0) {
    return <div style={{ color: palette.muted, padding: "12px 0" }}>目前沒有真實回放交易，因此這裡不顯示任何示意資料。</div>;
  }

  return (
    <div style={{ maxHeight: "320px", overflowY: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", ...mono, fontSize: "14px" }}>
        <thead>
          <tr style={{ color: palette.muted, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            {["日期", "標的", "方向", "成交價", "張數", "原因", "淨損益"].map((header) => (
              <th key={header} style={{ padding: "6px 8px", textAlign: "left", borderBottom: `1px solid ${palette.border}`, fontWeight: 400 }}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...trades].reverse().map((trade, index) => (
            <tr key={`${trade.symbol}-${trade.action}-${trade.ts}-${index}`} style={{ borderBottom: `1px solid rgba(255,255,255,0.05)` }}>
              <td style={{ padding: "6px 8px", color: palette.muted }}>{toDateLabel(trade.ts)}</td>
              <td style={{ padding: "6px 8px", color: palette.accent }}>{trade.symbol}</td>
              <td style={{ padding: "6px 8px", color: trade.action === "BUY" ? palette.success : palette.danger }}>
                {trade.action === "BUY" ? "買進" : "賣出"}
              </td>
              <td style={{ padding: "6px 8px" }}>{trade.price.toFixed(2)}</td>
              <td style={{ padding: "6px 8px" }}>{trade.shares / 1000}</td>
              <td style={{ padding: "6px 8px", color: palette.muted }}>{trade.reason}</td>
              <td style={{ padding: "6px 8px", color: tone(trade.netPnl) }}>
                {trade.action === "SELL" ? formatSigned(trade.netPnl) : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Performance() {
  const portfolio = usePortfolio();
  const replayTrades = useReplayTrades();

  const dailySeries = useMemo(() => buildDailySeries(replayTrades), [replayTrades]);
  const sellTrades = useMemo(() => replayTrades.filter((trade) => trade.action === "SELL"), [replayTrades]);
  const cumulativePnl = sellTrades.reduce((sum, trade) => sum + trade.netPnl, 0);
  const winTrades = sellTrades.filter((trade) => trade.netPnl > 0);
  const winRate = sellTrades.length ? (winTrades.length / sellTrades.length) * 100 : 0;
  const maxDrawdown = useMemo(() => calculateMaxDrawdown(dailySeries), [dailySeries]);
  const tradeDates = dailySeries.length ? `${dailySeries[0].label} - ${dailySeries.at(-1)?.label}` : "尚未累積有效平倉資料";

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, color: palette.text, padding: "24px", fontFamily: "var(--font-sans)" }}>
      <section style={{ padding: "18px 22px", background: palette.panel, border: `1px solid ${palette.border}`, marginBottom: "20px" }}>
        <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.14em", textTransform: "uppercase" }}>績效分析</div>
        <div style={{ marginTop: "6px", display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "32px", fontWeight: 700 }}>真實交易績效總覽</div>
            <div style={{ marginTop: "6px", color: palette.muted, fontSize: "16px", lineHeight: 1.6 }}>
              這裡只會使用真實的 replayTrades 與目前帳本資料，不再用假資料占位。若今天還沒有完成交易，畫面會直接顯示空狀態。
            </div>
          </div>
          <div style={{ display: "grid", gap: "6px", ...mono }}>
            <span style={{ color: palette.muted }}>統計期間</span>
            <span style={{ color: palette.accent, fontWeight: 700 }}>{tradeDates}</span>
          </div>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: "14px", marginBottom: "18px" }}>
        <KpiCard label="累積損益" value={formatSigned(cumulativePnl)} color={tone(cumulativePnl)} sublabel={`${sellTrades.length} 筆已完成平倉`} />
        <KpiCard label="勝率" value={`${winRate.toFixed(1)}%`} color={winRate >= 50 ? palette.success : palette.warning} sublabel={`${winTrades.length} 筆獲利交易`} />
        <KpiCard label="最大回撤" value={formatSigned(maxDrawdown)} color={palette.danger} sublabel="依每日累積淨損益估算" />
        <KpiCard label="即時已實現" value={formatSigned(portfolio?.realizedPnl ?? 0)} color={tone(portfolio?.realizedPnl ?? 0)} sublabel="來自目前模擬帳本" />
        <KpiCard label="即時總損益" value={formatSigned(portfolio?.totalPnl ?? 0)} color={tone(portfolio?.totalPnl ?? 0)} sublabel={`帳本勝率 ${(portfolio?.winRate ?? 0).toFixed(1)}%`} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px", marginBottom: "18px" }}>
        <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}` }}>
          <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>每日損益分布</div>
          <DailyBarChart daily={dailySeries} />
          {dailySeries.length > 0 && (
            <div style={{ marginTop: "8px", display: "flex", justifyContent: "space-between", color: palette.muted, fontSize: "13px" }}>
              <span>{dailySeries[0]?.label}</span>
              <span>{dailySeries.at(-1)?.label}</span>
            </div>
          )}
        </section>

        <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}` }}>
          <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>權益變化曲線</div>
          <EquityCurveChart daily={dailySeries} />
        </section>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 320px", gap: "18px" }}>
        <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}` }}>
          <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>交易明細</div>
          <TradeTable trades={replayTrades} />
        </section>

        <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}`, display: "grid", gap: "12px" }}>
          <div style={{ color: palette.muted, fontSize: "14px", letterSpacing: "0.1em", textTransform: "uppercase" }}>帳本狀態摘要</div>
          <div style={{ display: "grid", gap: "8px", ...mono }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: palette.muted }}>已實現損益</span>
              <span style={{ color: tone(portfolio?.realizedPnl ?? 0) }}>{formatSigned(portfolio?.realizedPnl ?? 0)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: palette.muted }}>未實現損益</span>
              <span style={{ color: tone(portfolio?.unrealizedPnl ?? 0) }}>{formatSigned(portfolio?.unrealizedPnl ?? 0)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: palette.muted }}>總損益</span>
              <span style={{ color: tone(portfolio?.totalPnl ?? 0) }}>{formatSigned(portfolio?.totalPnl ?? 0)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: palette.muted }}>交易次數</span>
              <span>{portfolio?.tradeCount ?? 0}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: palette.muted }}>大盤變化</span>
              <span style={{ color: tone(portfolio?.marketChangePct ?? 0) }}>
                {(portfolio?.marketChangePct ?? 0) >= 0 ? "+" : ""}
                {(portfolio?.marketChangePct ?? 0).toFixed(2)}%
              </span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { usePortfolio, useReplayDecisions, useReplayTrades } from "../store";
import type { DecisionReport } from "../types/market";

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

type ReplayEventType = "BUY" | "SELL" | "SIGNAL" | "HALT";

interface ReplayEvent {
  id: number;
  ts: number;
  type: ReplayEventType;
  symbol: string;
  price?: number;
  pnl?: number;
  reason: string;
  score?: number;
  report?: DecisionReport;
}

const SESSION_START_HOUR = 8;
const SESSION_DURATION_MS = 9 * 60 * 60 * 1000;

function formatClock(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hour = Math.floor(totalSeconds / 3600) + SESSION_START_HOUR;
  const minute = Math.floor((totalSeconds % 3600) / 60);
  const second = totalSeconds % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:${String(second).padStart(2, "0")}`;
}

function toDateKey(ts: number): string {
  const date = new Date(ts);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function buildPortfolioEvents(
  dateStr: string,
  recentTrades: {
    symbol: string;
    action: "BUY" | "SELL" | "SHORT" | "COVER";
    price: number;
    netPnl: number;
    ts: number;
    reason: string;
  }[],
): ReplayEvent[] {
  if (recentTrades.length === 0) {
    return [];
  }

  const startOfDay = new Date(`${dateStr}T08:00:00`);
  const sessionStart = startOfDay.getTime();
  const reasonMap: Record<string, string> = {
    SIGNAL: "事件觸發進場",
    TAKE_PROFIT: "目標停利出場",
    STOP_LOSS: "保護停損出場",
    TRAIL_STOP: "追蹤停損出場",
    EOD: "收盤平倉",
  };

  return recentTrades
    .map((trade, index) => ({
      id: index + 1,
      ts: Math.max(0, Math.min(SESSION_DURATION_MS, trade.ts - sessionStart)),
      type: trade.action === "SHORT" ? "BUY" : trade.action === "COVER" ? "SELL" : trade.action,
      symbol: trade.symbol,
      price: trade.price,
      pnl: trade.action === "SELL" || trade.action === "COVER" ? trade.netPnl : undefined,
      reason: reasonMap[trade.reason] ?? trade.reason,
    }))
    .sort((left, right) => left.ts - right.ts);
}

function buildDecisionEvents(dateStr: string, decisions: DecisionReport[]): ReplayEvent[] {
  if (decisions.length === 0) {
    return [];
  }

  const startOfDay = new Date(`${dateStr}T08:00:00`);
  const sessionStart = startOfDay.getTime();

  return decisions
    .map((decision, index): ReplayEvent => ({
      id: index + 1,
      ts: Math.max(0, Math.min(SESSION_DURATION_MS, decision.ts - sessionStart)),
      type:
        decision.decisionType === "buy"
          ? "BUY"
          : decision.decisionType === "sell" || decision.decisionType === "cover"
            ? "SELL"
            : decision.decisionType === "skip"
              ? "SIGNAL"
              : "HALT",
      symbol: decision.symbol,
      price: decision.orderResult.price,
      pnl: decision.orderResult.pnl,
      reason: decision.summary,
      score: decision.confidence,
      report: decision,
    }))
    .sort((left, right) => left.ts - right.ts);
}

function buildEquityCurve(events: ReplayEvent[]): { ts: number; pnl: number }[] {
  let cumulative = 0;
  const curve = [{ ts: 0, pnl: 0 }];

  for (const event of events) {
    if (event.type === "SELL" && typeof event.pnl === "number") {
      cumulative += event.pnl;
    }
    curve.push({ ts: event.ts, pnl: cumulative });
  }

  curve.push({ ts: SESSION_DURATION_MS, pnl: cumulative });
  return curve;
}

function Timeline({
  currentMs,
  events,
  onSeek,
}: {
  currentMs: number;
  events: ReplayEvent[];
  onSeek: (ms: number) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const colorMap: Record<ReplayEventType, string> = {
    BUY: palette.success,
    SELL: palette.danger,
    SIGNAL: palette.warning,
    HALT: "#ff8c00",
  };

  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const host = hostRef.current;
    if (!host) {
      return;
    }
    const rect = host.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    onSeek(Math.floor(ratio * SESSION_DURATION_MS));
  };

  return (
    <div style={{ display: "grid", gap: "8px" }}>
      <div
        ref={hostRef}
        onClick={handleClick}
        style={{
          height: "10px",
          borderRadius: "999px",
          background: "#2a2a2e",
          position: "relative",
          cursor: "pointer",
        }}
      >
        <div
          style={{
            width: `${(currentMs / SESSION_DURATION_MS) * 100}%`,
            height: "100%",
            borderRadius: "999px",
            background: palette.accent,
            transition: "width 120ms linear",
          }}
        />
        {events.map((event) => (
          <span
            key={event.id}
            title={`${event.symbol} ${event.reason}`}
            style={{
              position: "absolute",
              top: "-4px",
              left: `${(event.ts / SESSION_DURATION_MS) * 100}%`,
              width: "4px",
              height: "18px",
              borderRadius: "999px",
              background: colorMap[event.type],
              transform: "translateX(-50%)",
            }}
          />
        ))}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(10, 1fr)",
          fontSize: "18px",
          color: palette.muted,
          ...mono,
        }}
      >
        {["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"].map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
    </div>
  );
}

function EquityCurve({
  currentMs,
  points,
}: {
  currentMs: number;
  points: { ts: number; pnl: number }[];
}) {
  const width = 640;
  const height = 96;
  const visible = points.filter((point) => point.ts <= currentMs);
  const maxAbs = Math.max(1, ...points.map((point) => Math.abs(point.pnl)));
  const latest = visible.at(-1)?.pnl ?? 0;

  if (visible.length < 2) {
    return <div style={{ height, border: `1px solid ${palette.border}`, background: "rgba(255,255,255,0.02)" }} />;
  }

  const path = visible
    .map((point, index) => {
      const x = (point.ts / SESSION_DURATION_MS) * width;
      const y = height / 2 - (point.pnl / maxAbs) * (height / 2 - 8);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");

  return (
    <div style={{ position: "relative" }}>
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke={palette.border} strokeDasharray="4 4" />
        <path d={path} fill="none" stroke={latest >= 0 ? palette.success : palette.danger} strokeWidth="2" />
      </svg>
      <div style={{ position: "absolute", top: "8px", right: "12px", ...mono, color: latest >= 0 ? palette.success : palette.danger }}>
        {latest >= 0 ? "+" : ""}
        {latest.toLocaleString()} 元
      </div>
    </div>
  );
}

function EventCard({ active, event }: { active: boolean; event: ReplayEvent }) {
  const tone =
    event.type === "BUY" ? palette.success : event.type === "SELL" ? palette.danger : event.type === "SIGNAL" ? palette.warning : palette.accent;

  return (
    <div
      style={{
        border: `1px solid ${active ? tone : palette.border}`,
        background: active ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.02)",
        padding: "12px 14px",
        display: "grid",
        gap: "6px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "baseline" }}>
        <div style={{ fontWeight: 700, color: tone }}>
          {formatClock(event.ts)} {event.symbol}
        </div>
        <div style={{ color: palette.muted, ...mono }}>{event.type}</div>
      </div>
      <div style={{ color: palette.text, lineHeight: 1.6 }}>{event.reason}</div>
      {typeof event.price === "number" && (
        <div style={{ color: palette.text, ...mono }}>
          {event.symbol} @ {event.price.toFixed(2)}
        </div>
      )}
      <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", ...mono, color: palette.muted }}>
        {typeof event.price === "number" && <span>價格 {event.price.toFixed(2)}</span>}
        {typeof event.pnl === "number" && (
          <span style={{ color: event.pnl >= 0 ? palette.success : palette.danger }}>
            損益 {event.pnl >= 0 ? "+" : ""}
            {event.pnl.toLocaleString()}
          </span>
        )}
        {typeof event.score === "number" && <span>信心 {event.score}</span>}
      </div>
    </div>
  );
}

function DetailCard({ title, tone, content }: { title: string; tone: string; content: string }) {
  return (
    <div style={{ border: `1px solid ${palette.border}`, padding: "14px", background: "rgba(255,255,255,0.02)" }}>
      <div style={{ color: tone, fontSize: "18px", fontWeight: 700, marginBottom: "10px" }}>{title}</div>
      <div style={{ color: palette.text, lineHeight: 1.7 }}>{content}</div>
    </div>
  );
}

function DecisionReportPanel({ report }: { report: DecisionReport | null }) {
  if (!report) {
    return (
      <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}` }}>
        <div style={{ color: palette.muted, fontSize: "18px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>決策摘要</div>
        <div style={{ color: palette.muted, lineHeight: 1.7 }}>將時間軸移到有決策的節點後，這裡會顯示支持理由、反對理由、多空觀點與風控判讀。</div>
      </section>
    );
  }

  const reportTone =
    report.decisionType === "buy" ? palette.success : report.decisionType === "sell" ? palette.danger : palette.warning;

  return (
    <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}`, display: "grid", gap: "16px" }}>
      <div>
        <div style={{ color: palette.muted, fontSize: "18px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>決策摘要</div>
        <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", marginBottom: "8px", flexWrap: "wrap" }}>
          <div style={{ fontSize: "26px", fontWeight: 700, color: reportTone }}>
            {report.symbol} {report.decisionType === "buy" ? "買進" : report.decisionType === "sell" ? "賣出" : "略過"}
          </div>
          <div style={{ ...mono, color: palette.accent, fontSize: "24px" }}>{report.confidence} 分</div>
        </div>
        <div style={{ color: palette.text, lineHeight: 1.7 }}>{report.summary}</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "14px" }}>
        <div style={{ border: `1px solid ${palette.border}`, padding: "14px", background: "rgba(255,255,255,0.02)" }}>
          <div style={{ color: palette.success, fontSize: "18px", fontWeight: 700, marginBottom: "10px" }}>支持理由</div>
          <div style={{ display: "grid", gap: "10px" }}>
            {report.supportingFactors.length > 0 ? report.supportingFactors.map((factor) => (
              <div key={`${factor.kind}-${factor.label}`}>
                <div style={{ color: palette.text, fontWeight: 700 }}>{factor.label}</div>
                <div style={{ color: palette.muted, lineHeight: 1.6 }}>{factor.detail}</div>
              </div>
            )) : <div style={{ color: palette.muted }}>這次決策沒有額外的支持因子。</div>}
          </div>
        </div>

        <div style={{ border: `1px solid ${palette.border}`, padding: "14px", background: "rgba(255,255,255,0.02)" }}>
          <div style={{ color: palette.danger, fontSize: "18px", fontWeight: 700, marginBottom: "10px" }}>反對理由</div>
          <div style={{ display: "grid", gap: "10px" }}>
            {report.opposingFactors.length > 0 ? report.opposingFactors.map((factor) => (
              <div key={`${factor.kind}-${factor.label}`}>
                <div style={{ color: palette.text, fontWeight: 700 }}>{factor.label}</div>
                <div style={{ color: palette.muted, lineHeight: 1.6 }}>{factor.detail}</div>
              </div>
            )) : <div style={{ color: palette.muted }}>這次決策沒有明顯的反對因子。</div>}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "14px" }}>
        <DetailCard title="多方觀點" tone={palette.success} content={report.bullCase ?? "目前沒有額外的多方觀點。"} />
        <DetailCard title="空方觀點" tone={palette.danger} content={report.bearCase ?? "目前沒有額外的空方觀點。"} />
        <DetailCard title="風控觀點" tone={palette.warning} content={report.riskCase ?? "目前沒有額外的風控觀點。"} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "14px" }}>
        <DetailCard title="多方論點" tone={palette.success} content={report.bullArgument ?? "目前沒有額外的多方辯論內容。"} />
        <DetailCard title="空方論點" tone={palette.danger} content={report.bearArgument ?? "目前沒有額外的空方辯論內容。"} />
        <DetailCard
          title="裁決結論"
          tone={report.debateWinner === "bear" ? palette.danger : report.debateWinner === "bull" ? palette.success : palette.accent}
          content={report.refereeVerdict ?? "目前沒有辯論裁決結果。"}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "14px" }}>
        <div style={{ border: `1px solid ${palette.border}`, padding: "14px", background: "rgba(255,255,255,0.02)" }}>
          <div style={{ color: palette.warning, fontSize: "18px", fontWeight: 700, marginBottom: "10px" }}>風險旗標</div>
          {report.riskFlags.length > 0 ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {report.riskFlags.map((flag) => (
                <span key={flag} style={{ padding: "4px 8px", border: `1px solid ${palette.border}`, color: palette.warning, ...mono }}>
                  {flag}
                </span>
              ))}
            </div>
          ) : (
            <div style={{ color: palette.muted }}>本次決策沒有額外風險旗標。</div>
          )}
        </div>

        <div style={{ border: `1px solid ${palette.border}`, padding: "14px", background: "rgba(255,255,255,0.02)" }}>
          <div style={{ color: palette.accent, fontSize: "18px", fontWeight: 700, marginBottom: "10px" }}>執行結果</div>
          <div style={{ display: "grid", gap: "6px", ...mono }}>
            <div>狀態：{report.orderResult.status}</div>
            {report.orderResult.action && <div>動作：{report.orderResult.action}</div>}
            {typeof report.orderResult.price === "number" && <div>價格：{report.orderResult.price.toFixed(2)}</div>}
            {typeof report.orderResult.shares === "number" && <div>股數：{report.orderResult.shares.toLocaleString()}</div>}
            {typeof report.orderResult.pnl === "number" && (
              <div style={{ color: report.orderResult.pnl >= 0 ? palette.success : palette.danger }}>
                損益：{report.orderResult.pnl >= 0 ? "+" : ""}
                {report.orderResult.pnl.toLocaleString()} 元
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

const controlButtonStyle: CSSProperties = {
  padding: "8px 14px",
  border: `1px solid ${palette.border}`,
  background: "rgba(255,255,255,0.05)",
  color: palette.text,
  cursor: "pointer",
  fontSize: "24px",
};

export function TradeReplay() {
  const portfolio = usePortfolio();
  const replayTrades = useReplayTrades();
  const replayDecisions = useReplayDecisions();
  const today = toDateKey(Date.now());
  const [dateStr, setDateStr] = useState(today);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 5 | 10>(1);
  const [currentMs, setCurrentMs] = useState(0);
  const timerRef = useRef<number | null>(null);

  const tradesForDate = useMemo(
    () => replayTrades.filter((trade) => toDateKey(trade.ts) === dateStr),
    [dateStr, replayTrades],
  );
  const decisionsForDate = useMemo(
    () => replayDecisions.filter((decision) => toDateKey(decision.ts) === dateStr),
    [dateStr, replayDecisions],
  );

  const events = useMemo(() => {
    if (decisionsForDate.length > 0) {
      return buildDecisionEvents(dateStr, decisionsForDate);
    }
    if (tradesForDate.length > 0) {
      return buildPortfolioEvents(
        dateStr,
        tradesForDate.map((trade) => ({
          symbol: trade.symbol,
          action: trade.action,
          price: trade.price,
          netPnl: trade.netPnl,
          ts: trade.ts,
          reason: trade.reason,
        })),
      );
    }
    return [];
  }, [dateStr, decisionsForDate, tradesForDate]);

  const sourceLabel = decisionsForDate.length > 0 ? "決策報告回放" : events.length > 0 ? "交易回放資料" : "尚無回放資料";
  const equityCurve = useMemo(() => buildEquityCurve(events), [events]);
  const activeEvents = events.filter((event) => event.ts <= currentMs);
  const nextEvent = events.find((event) => event.ts > currentMs) ?? null;
  const activeDecisionReport = activeEvents.at(-1)?.report ?? nextEvent?.report ?? null;

  useEffect(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (!isPlaying) {
      return;
    }
    timerRef.current = window.setInterval(() => {
      setCurrentMs((previous) => {
        const next = previous + speed * 1_000;
        if (next >= SESSION_DURATION_MS) {
          setIsPlaying(false);
          return SESSION_DURATION_MS;
        }
        return next;
      });
    }, 100);
    return () => {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
      }
    };
  }, [isPlaying, speed]);

  useEffect(() => {
    setCurrentMs(0);
    setIsPlaying(false);
  }, [dateStr]);

  const handleSeek = (nextMs: number) => {
    setCurrentMs(nextMs);
    setIsPlaying(false);
  };

  const summaryLabel = portfolio?.recentTrades?.length ? `已累積 ${portfolio.recentTrades.length} 筆近期模擬交易。` : "只顯示真實模擬帳本資料；若所選日期沒有交易或事件，會直接顯示空狀態。";

  return (
    <div style={{ minHeight: "100vh", background: palette.bg, color: palette.text, padding: "24px", fontFamily: "var(--font-sans)" }}>
      <section style={{ padding: "18px 22px", background: palette.panel, border: `1px solid ${palette.border}`, marginBottom: "20px" }}>
        <div style={{ color: palette.muted, fontSize: "18px", letterSpacing: "0.14em", textTransform: "uppercase" }}>交易回放</div>
        <div style={{ marginTop: "6px", display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: "36px", fontWeight: 700 }}>時間軸回放</div>
            <div style={{ marginTop: "6px", color: palette.muted, fontSize: "24px" }}>
              {summaryLabel} 已累積的回放資料會跨重新整理保留。
            </div>
          </div>
          <div style={{ display: "grid", gap: "6px", ...mono }}>
            <span style={{ color: palette.muted }}>資料來源</span>
            <span style={{ color: decisionsForDate.length > 0 ? palette.success : palette.accent }}>{sourceLabel}</span>
          </div>
        </div>
      </section>

      <section style={{ padding: "14px 16px", background: palette.panel, border: `1px solid ${palette.border}`, marginBottom: "18px", display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
        <input
          type="date"
          value={dateStr}
          onChange={(event) => setDateStr(event.target.value)}
          style={{ padding: "8px 10px", background: "rgba(255,255,255,0.05)", border: `1px solid ${palette.border}`, color: palette.text, ...mono }}
        />
        <div style={{ minWidth: "96px", fontSize: "32px", fontWeight: 700, color: palette.accent, ...mono }}>{formatClock(currentMs)}</div>
        <button type="button" style={controlButtonStyle} onClick={() => handleSeek(0)}>回到開盤</button>
        <button
          type="button"
          style={{ ...controlButtonStyle, background: isPlaying ? palette.warning : palette.success, color: "#000", fontWeight: 700, minWidth: "88px" }}
          onClick={() => setIsPlaying((value) => !value)}
        >
          {isPlaying ? "暫停" : "播放"}
        </button>
        <button type="button" style={controlButtonStyle} onClick={() => handleSeek(SESSION_DURATION_MS)}>跳到收盤</button>
        {[1, 5, 10].map((option) => (
          <button
            key={option}
            type="button"
            style={{
              ...controlButtonStyle,
              background: speed === option ? palette.accent : "rgba(255,255,255,0.05)",
              color: speed === option ? "#000" : palette.text,
            }}
            onClick={() => setSpeed(option as 1 | 5 | 10)}
          >
            {option}x
          </button>
        ))}
        <span style={{ marginLeft: "auto", color: palette.muted, fontSize: "18px" }}>
          下一事件: {nextEvent ? `${nextEvent.symbol} ${nextEvent.reason}` : "今天已經回放完畢"}
        </span>
      </section>

      <section style={{ padding: "14px 16px", background: palette.panel, border: `1px solid ${palette.border}`, marginBottom: "18px" }}>
        <Timeline currentMs={currentMs} events={events} onSeek={handleSeek} />
      </section>

      {events.length === 0 ? (
        <section style={{ padding: "20px", background: palette.panel, border: `1px solid ${palette.border}` }}>
          <div style={{ fontSize: "28px", fontWeight: 700, marginBottom: "10px" }}>這一天沒有可回放的交易或事件。</div>
          <div style={{ color: palette.muted, lineHeight: 1.7 }}>如果這一天尚未產生模擬成交或決策報告，回放頁會維持空狀態，不會再顯示範例事件。</div>
        </section>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(360px, 0.9fr)", gap: "18px" }}>
          <div style={{ display: "grid", gap: "18px" }}>
            <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}` }}>
              <div style={{ color: palette.muted, fontSize: "18px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>權益曲線</div>
              <EquityCurve currentMs={currentMs} points={equityCurve} />
            </section>
            <DecisionReportPanel report={activeDecisionReport} />
          </div>

          <section style={{ padding: "16px", background: palette.panel, border: `1px solid ${palette.border}` }}>
            <div style={{ color: palette.muted, fontSize: "18px", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "12px" }}>
              事件清單 ({activeEvents.length}/{events.length})
            </div>
            <div style={{ display: "grid", gap: "10px", maxHeight: "920px", overflowY: "auto" }}>
              {events.map((event) => (
                <EventCard key={event.id} active={event.ts <= currentMs} event={event} />
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

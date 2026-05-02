import { useMarketStore } from "../store";

const palette = {
  bg: "#0d1117",
  panel: "#161b22",
  border: "#21262d",
  text: "#e6edf3",
  muted: "#8b949e",
  accent: "#4d8dff",
  up: "#3fb950",
  down: "#f85149",
  tag: "#1f2937",
};

function sourceColor(source: string): string {
  if (source.includes("Yahoo")) return "#7c3aed";
  if (source.includes("MarketWatch")) return "#0284c7";
  if (source.includes("Investopedia")) return "#059669";
  return "#6b7280";
}

function formatTime(isoStr: string): string {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

export function NewsPanel() {
  const newsFeed = useMarketStore((state) => state.newsFeed);

  if (!newsFeed) {
    return (
      <div
        style={{
          padding: "10px 14px",
          background: palette.panel,
          border: `1px solid ${palette.border}`,
          color: palette.muted,
          fontSize: "12px",
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
      >
        <span style={{ opacity: 0.5 }}>●</span>
        國際市場消息載入中...（後端連線後自動推送）
      </div>
    );
  }

  const { items, updatedAt } = newsFeed;

  return (
    <div
      style={{
        background: palette.panel,
        border: `1px solid ${palette.border}`,
        display: "grid",
        gridTemplateRows: "auto minmax(0, 1fr)",
        overflow: "hidden",
        minHeight: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "6px 14px",
          borderBottom: `1px solid ${palette.border}`,
          display: "flex",
          alignItems: "center",
          gap: "10px",
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: "11px", color: palette.muted, letterSpacing: "0.1em" }}>
          🌐 國際市場消息
        </span>
        <span style={{ fontSize: "10px", color: palette.muted, marginLeft: "auto" }}>
          更新：{formatTime(updatedAt)} · 每 10 分鐘刷新
        </span>
      </div>

      {/* News ticker / scroll area */}
      <div
        style={{
          display: "flex",
          gap: "0",
          overflowX: "auto",
          overflowY: "hidden",
          alignItems: "stretch",
          scrollbarWidth: "none",
        }}
      >
        {items.map((item, idx) => (
          <a
            key={idx}
            href={item.url || undefined}
            target="_blank"
            rel="noopener noreferrer"
            title={item.title}
            style={{
              display: "grid",
              gridTemplateRows: "auto minmax(0, 1fr)",
              gap: "4px",
              padding: "8px 12px",
              borderRight: `1px solid ${palette.border}`,
              minWidth: "260px",
              maxWidth: "300px",
              textDecoration: "none",
              color: palette.text,
              flexShrink: 0,
              background: idx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span
                style={{
                  fontSize: "9px",
                  padding: "1px 5px",
                  borderRadius: "3px",
                  background: sourceColor(item.source),
                  color: "#fff",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  flexShrink: 0,
                }}
              >
                {item.source.split(" ")[0].toUpperCase()}
              </span>
              <span style={{ fontSize: "10px", color: palette.muted, flexShrink: 0 }}>
                {formatTime(item.published_at)}
              </span>
            </div>
            <div
              style={{
                fontSize: "11px",
                lineHeight: "1.45",
                color: palette.text,
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 3,
                WebkitBoxOrient: "vertical",
              }}
            >
              {item.summary || item.title}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

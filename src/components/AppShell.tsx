import { type CSSProperties, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useConnectionState, usePortfolio } from "../store";

const NAV_ITEMS = [
  { path: "/", label: "盤中總控台" },
  { path: "/strategy", label: "策略作戰台" },
  { path: "/replay", label: "交易回放" },
  { path: "/performance", label: "績效分析" },
  { path: "/config", label: "策略設定" },
] as const;

const palette = {
  shell: "#0e0e10",
  panel: "#141416",
  border: "#242428",
  text: "#f0f0f0",
  muted: "#6b6b72",
  accent: "#00f5ff",
  success: "#00e676",
  warning: "#d4af37",
  danger: "#ff3366",
};

const sidebarStyle: CSSProperties = {
  width: "208px",
  minWidth: "208px",
  background: palette.panel,
  borderRight: `1px solid ${palette.border}`,
  display: "flex",
  flexDirection: "column",
  position: "sticky",
  top: 0,
  height: "100vh",
  zIndex: 40,
};

function connectionColor(state: ReturnType<typeof useConnectionState>): string {
  switch (state) {
    case "open":
      return palette.success;
    case "reconnecting":
      return palette.warning;
    case "connecting":
      return palette.accent;
    case "closed":
    case "error":
      return palette.danger;
    default:
      return palette.muted;
  }
}

function connectionLabel(state: ReturnType<typeof useConnectionState>): string {
  switch (state) {
    case "open":
      return "已連線";
    case "reconnecting":
      return "重連中";
    case "connecting":
      return "連線中";
    case "closed":
      return "已中斷";
    case "error":
      return "異常";
    default:
      return "待命";
  }
}

function NavItem({ path, label }: { path: string; label: string }) {
  const location = useLocation();
  const isActive = path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  return (
    <NavLink
      to={path}
      end={path === "/"}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "10px 20px",
        textDecoration: "none",
        color: isActive ? palette.text : palette.muted,
        fontSize: "16px",
        fontWeight: isActive ? 700 : 500,
        letterSpacing: "0.02em",
        position: "relative",
        transition: "color 0.15s ease",
      }}
    >
      {isActive ? (
        <span
          style={{
            position: "absolute",
            left: 0,
            top: "50%",
            transform: "translateY(-50%)",
            width: "2px",
            height: "18px",
            background: palette.accent,
            boxShadow: `0 0 8px ${palette.accent}`,
          }}
        />
      ) : null}
      <span style={{ color: isActive ? palette.accent : "inherit" }}>{label}</span>
    </NavLink>
  );
}

export function AppShell({ children, topBanner }: { children: ReactNode; topBanner?: ReactNode }) {
  const state = useConnectionState();
  const dotColor = connectionColor(state);
  const portfolio = usePortfolio();
  const pnl = portfolio?.totalPnl ?? 0;
  const pnlColor = pnl > 0 ? palette.success : pnl < 0 ? palette.danger : palette.muted;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: palette.shell }}>
      <aside style={sidebarStyle}>
        <div style={{ padding: "24px 20px 18px", borderBottom: `1px solid ${palette.border}` }}>
          <div
            style={{
              fontSize: "12px",
              letterSpacing: "0.18em",
              color: palette.accent,
              fontWeight: 800,
              textTransform: "uppercase",
              marginBottom: "8px",
            }}
          >
            Taiwan Market
          </div>
          <div style={{ fontSize: "21px", fontWeight: 800, color: palette.text, lineHeight: 1.35 }}>
            台股模擬交易雷達
          </div>
        </div>

        <div
          style={{
            padding: "14px 20px",
            borderBottom: `1px solid ${palette.border}`,
            display: "flex",
            flexDirection: "column",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
            <span style={{ fontSize: "13px", color: palette.muted, letterSpacing: "0.06em" }}>連線狀態</span>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span
                style={{
                  width: "7px",
                  height: "7px",
                  borderRadius: "50%",
                  background: dotColor,
                  boxShadow: `0 0 6px ${dotColor}`,
                  display: "inline-block",
                }}
              />
              <span style={{ fontSize: "14px", color: dotColor, fontWeight: 700 }}>{connectionLabel(state)}</span>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
            <span style={{ fontSize: "13px", color: palette.muted, letterSpacing: "0.06em" }}>帳本損益</span>
            <span style={{ fontSize: "16px", color: pnlColor, fontWeight: 800, fontFamily: "var(--font-mono)" }}>
              {pnl >= 0 ? "+" : ""}
              {pnl.toLocaleString()}
            </span>
          </div>
        </div>

        <nav style={{ flex: 1, padding: "12px 0", display: "flex", flexDirection: "column", gap: "2px" }}>
          {NAV_ITEMS.map((item) => (
            <NavItem key={item.path} path={item.path} label={item.label} />
          ))}
        </nav>

        <div style={{ padding: "12px 20px", borderTop: `1px solid ${palette.border}` }}>
          <div style={{ fontSize: "12px", color: palette.muted }}>單人策略交易平台 v0.2.0</div>
        </div>
      </aside>

      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        {topBanner}
        {children}
      </main>
    </div>
  );
}

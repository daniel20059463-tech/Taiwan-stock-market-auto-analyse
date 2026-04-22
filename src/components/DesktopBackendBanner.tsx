import type { CSSProperties } from "react";
import type { DesktopBackendStatus } from "../types/desktop";

interface DesktopBackendBannerProps {
  status: DesktopBackendStatus;
  isRetrying: boolean;
  onRetry: () => void;
}

const phaseCopy: Record<DesktopBackendStatus["phase"], string> = {
  idle: "桌面後端未啟動",
  starting: "桌面後端啟動中",
  running: "桌面後端執行中",
  error: "桌面後端異常",
};

const phaseColor: Record<DesktopBackendStatus["phase"], string> = {
  idle: "#6b7280",
  starting: "#d4af37",
  running: "#00e676",
  error: "#ff5c7a",
};

const bannerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "12px",
  padding: "8px 16px",
  minHeight: "40px",
  borderBottom: "1px solid rgba(255,255,255,0.08)",
  background: "rgba(20,20,22,0.92)",
  color: "#d8dbe2",
  fontSize: "13px",
  lineHeight: 1.4,
};

const actionButtonStyle: CSSProperties = {
  border: "1px solid rgba(255,255,255,0.16)",
  borderRadius: "999px",
  background: "rgba(255,255,255,0.04)",
  color: "#f5f7fb",
  padding: "5px 10px",
  fontSize: "12px",
  fontWeight: 700,
  cursor: "pointer",
};

export function DesktopBackendBanner({
  status,
  isRetrying,
  onRetry,
}: DesktopBackendBannerProps) {
  if (status.phase === "running") {
    return null;
  }

  return (
    <div role="status" aria-live="polite" style={bannerStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px", minWidth: 0 }}>
        <span
          aria-hidden="true"
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            flexShrink: 0,
            background: phaseColor[status.phase],
            boxShadow: `0 0 10px ${phaseColor[status.phase]}`,
          }}
        />
        <span style={{ whiteSpace: "nowrap", fontWeight: 700 }}>{phaseCopy[status.phase]}</span>
        {status.detail ? (
          <span style={{ color: "#aeb5c2", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {status.detail}
          </span>
        ) : null}
      </div>

      {status.phase === "error" ? (
        <button type="button" onClick={onRetry} disabled={isRetrying} style={actionButtonStyle}>
          {isRetrying ? "重試中..." : "重試"}
        </button>
      ) : null}
    </div>
  );
}

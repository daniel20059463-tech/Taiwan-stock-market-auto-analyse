import type { CSSProperties } from "react";
import type { DesktopUpdateState } from "../types/desktop";

interface DesktopUpdateBannerProps {
  state: DesktopUpdateState;
  isUpdating: boolean;
  onUpdateNow: () => void;
  onDismiss: () => void;
}

const visibleStatuses = new Set<DesktopUpdateState["status"]>([
  "available",
  "downloading",
  "installing",
  "error",
]);

const bannerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "12px",
  padding: "10px 16px",
  minHeight: "48px",
  borderBottom: "1px solid rgba(255,255,255,0.08)",
  background: "rgba(28, 20, 12, 0.96)",
  color: "#f5efe6",
  fontSize: "13px",
  lineHeight: 1.5,
};

const actionsStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
  flexShrink: 0,
};

const primaryButtonStyle: CSSProperties = {
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: "999px",
  background: "#f59e0b",
  color: "#1f1304",
  padding: "6px 12px",
  fontSize: "12px",
  fontWeight: 700,
  cursor: "pointer",
};

const secondaryButtonStyle: CSSProperties = {
  ...primaryButtonStyle,
  background: "rgba(255,255,255,0.06)",
  color: "#f5efe6",
};

function buildDefaultMessage(state: DesktopUpdateState): string {
  const currentVersion = state.currentVersion ?? "目前版本";
  const availableVersion = state.availableVersion ?? "新版";
  return `目前版本 ${currentVersion}，可更新為 ${availableVersion}。你可以現在更新，或稍後再說。`;
}

export function DesktopUpdateBanner({
  state,
  isUpdating,
  onUpdateNow,
  onDismiss,
}: DesktopUpdateBannerProps) {
  if (!visibleStatuses.has(state.status)) {
    return null;
  }

  const title = state.status === "error" ? "更新失敗" : "發現新版本";
  const body = state.message ?? buildDefaultMessage(state);
  const actionsDisabled =
    isUpdating || state.status === "downloading" || state.status === "installing";

  return (
    <div role="status" aria-live="polite" style={bannerStyle}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 700 }}>{title}</div>
        <div style={{ color: "rgba(245, 239, 230, 0.82)" }}>{body}</div>
      </div>
      <div style={actionsStyle}>
        <button
          type="button"
          onClick={onUpdateNow}
          disabled={actionsDisabled}
          style={primaryButtonStyle}
        >
          立即更新
        </button>
        <button
          type="button"
          onClick={onDismiss}
          disabled={actionsDisabled}
          style={secondaryButtonStyle}
        >
          稍後再說
        </button>
      </div>
    </div>
  );
}

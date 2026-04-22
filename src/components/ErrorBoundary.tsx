import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  label?: string;
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  resetKey: number;
}

const palette = {
  bg: "#1a1a1c",
  border: "#333333",
  text: "#f0f0f0",
  muted: "#8c8c8c",
  danger: "#ff3366",
  warning: "#d4af37",
  accent: "#00f5ff",
};

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null, resetKey: 0 };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ errorInfo: info });
    this.props.onError?.(error, info);

    console.error(
      `[ErrorBoundary]${this.props.label ? ` (${this.props.label})` : ""} 捕捉到前端例外`,
      error,
      info.componentStack,
    );
  }

  private handleReset = (): void => {
    this.setState((prev) => ({
      hasError: false,
      error: null,
      errorInfo: null,
      resetKey: prev.resetKey + 1,
    }));
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return (
        <div key={this.state.resetKey} style={{ display: "contents" }}>
          {this.props.children}
        </div>
      );
    }

    const { error, errorInfo } = this.state;
    const label = this.props.label ?? "未命名區塊";

    return (
      <div
        style={{
          border: `1px solid ${palette.danger}`,
          background: palette.bg,
          padding: "20px 24px",
          color: palette.text,
          fontFamily: "var(--font-sans, sans-serif)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "14px",
            gap: "12px",
            flexWrap: "wrap",
          }}
        >
          <div>
            <div
              style={{
                color: palette.danger,
                fontSize: "14px",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                marginBottom: "4px",
              }}
            >
              前端錯誤邊界 | {label}
            </div>
            <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: "18px", color: palette.warning }}>
              {error?.name ?? "Error"}: {error?.message ?? "發生未預期錯誤"}
            </div>
          </div>

          <button
            type="button"
            onClick={this.handleReset}
            style={{
              padding: "10px 20px",
              border: `1px solid ${palette.accent}`,
              background: "transparent",
              color: palette.accent,
              fontFamily: "var(--font-mono, monospace)",
              fontSize: "17px",
              cursor: "pointer",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              flexShrink: 0,
            }}
          >
            重新載入區塊
          </button>
        </div>

        {errorInfo?.componentStack && (
          <details style={{ marginTop: "8px" }}>
            <summary
              style={{
                color: palette.muted,
                fontSize: "14px",
                cursor: "pointer",
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                userSelect: "none",
              }}
            >
              查看元件堆疊
            </summary>
            <pre
              style={{
                marginTop: "10px",
                padding: "12px",
                background: "rgba(255,255,255,0.03)",
                border: `1px solid ${palette.border}`,
                color: palette.muted,
                fontSize: "14px",
                lineHeight: 1.6,
                overflowX: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {errorInfo.componentStack}
            </pre>
          </details>
        )}
      </div>
    );
  }
}

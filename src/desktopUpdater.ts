import { isDesktopRuntime } from "./desktopBridge";
import type { DesktopUpdateState } from "./types/desktop";

type UpdateCommand = "check_for_update" | "install_update";

function normalizeUpdateStatus(value: unknown): DesktopUpdateState["status"] {
  return value === "checking" ||
    value === "available" ||
    value === "downloading" ||
    value === "installing" ||
    value === "upToDate" ||
    value === "error" ||
    value === "dismissed"
    ? value
    : "idle";
}

function normalizeUpdateState(value: unknown): DesktopUpdateState {
  if (!value || typeof value !== "object") {
    return { status: "idle" };
  }

  const candidate = value as Record<string, unknown>;
  return {
    status: normalizeUpdateStatus(candidate.status),
    currentVersion:
      typeof candidate.currentVersion === "string" ? candidate.currentVersion : undefined,
    availableVersion:
      typeof candidate.availableVersion === "string" ? candidate.availableVersion : undefined,
    notes: typeof candidate.notes === "string" ? candidate.notes : undefined,
    message: typeof candidate.message === "string" ? candidate.message : undefined,
  };
}

async function invokeDesktopUpdate(command: UpdateCommand): Promise<DesktopUpdateState> {
  if (!isDesktopRuntime()) {
    return { status: "idle" };
  }

  const tauriCore = await import("@tauri-apps/api/core");
  const result = await tauriCore.invoke<unknown>(command);
  return normalizeUpdateState(result);
}

export async function checkForDesktopUpdate(): Promise<DesktopUpdateState> {
  try {
    return await invokeDesktopUpdate("check_for_update");
  } catch (error) {
    return {
      status: "idle",
      message: error instanceof Error ? error.message : "檢查更新失敗。",
    };
  }
}

export async function installDesktopUpdate(): Promise<DesktopUpdateState> {
  try {
    return await invokeDesktopUpdate("install_update");
  } catch (error) {
    return {
      status: "error",
      message: error instanceof Error ? error.message : "安裝更新失敗。",
    };
  }
}

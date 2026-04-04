import type { DesktopBackendPhase, DesktopBackendStatus } from "./types/desktop";

type DesktopCommand = "backend_status" | "restart_backend";

declare global {
  interface Window {
    __TAURI__?: unknown;
    __TAURI_INTERNALS__?: unknown;
  }
}

function normalizePhase(value: unknown): DesktopBackendPhase {
  return value === "starting" || value === "running" || value === "error" ? value : "idle";
}

function normalizeStatus(value: unknown): DesktopBackendStatus {
  if (typeof value === "string") {
    return {
      phase: normalizePhase(value),
      updatedAt: Date.now(),
    };
  }

  if (value && typeof value === "object") {
    const candidate = value as Record<string, unknown>;
    if (candidate.phase === undefined) {
      return {
        phase: "error",
        detail: "Invalid desktop backend status payload",
        updatedAt: Date.now(),
      };
    }

    return {
      phase: normalizePhase(candidate.phase),
      detail:
        typeof candidate.detail === "string"
          ? candidate.detail
          : typeof candidate.message === "string"
            ? candidate.message
            : undefined,
      updatedAt: typeof candidate.updatedAt === "number" ? candidate.updatedAt : Date.now(),
    };
  }

  return {
    phase: "error",
    detail: "Missing desktop backend status payload",
    updatedAt: Date.now(),
  };
}

export function isDesktopRuntime(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  const tauriInternals = window.__TAURI_INTERNALS__;
  return typeof tauriInternals === "object" && tauriInternals !== null;
}

async function invokeDesktop<T>(command: DesktopCommand): Promise<T | null> {
  if (!isDesktopRuntime()) {
    return null;
  }

  try {
    const tauriCore = await import("@tauri-apps/api/core");
    return await tauriCore.invoke<T>(command);
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : `Failed to invoke ${command}`);
  }
}

export async function getBackendStatus(): Promise<DesktopBackendStatus> {
  if (!isDesktopRuntime()) {
    return { phase: "idle", updatedAt: Date.now() };
  }

  try {
    const result = await invokeDesktop<unknown>("backend_status");
    return normalizeStatus(result);
  } catch (error) {
    return {
      phase: "error",
      detail: error instanceof Error ? error.message : "Failed to query desktop backend",
      updatedAt: Date.now(),
    };
  }
}

export async function restartBackend(): Promise<DesktopBackendStatus> {
  if (!isDesktopRuntime()) {
    return { phase: "idle", updatedAt: Date.now() };
  }

  try {
    const result = await invokeDesktop<unknown>("restart_backend");
    return normalizeStatus(result);
  } catch (error) {
    return {
      phase: "error",
      detail: error instanceof Error ? error.message : "Failed to restart desktop backend",
      updatedAt: Date.now(),
    };
  }
}

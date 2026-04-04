export type DesktopBackendPhase = "idle" | "starting" | "running" | "error";

export interface DesktopBackendStatus {
  phase: DesktopBackendPhase;
  detail?: string;
  updatedAt?: number;
}

export type DesktopUpdateStatus =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "installing"
  | "upToDate"
  | "error"
  | "dismissed";

export interface DesktopUpdateState {
  status: DesktopUpdateStatus;
  currentVersion?: string;
  availableVersion?: string;
  notes?: string;
  message?: string;
}

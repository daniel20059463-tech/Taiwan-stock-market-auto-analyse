# Optional Desktop Update Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional desktop update reminder for the Windows Tauri app that checks GitHub Releases on startup, shows a Chinese prompt when a newer version is available, and lets the user choose whether to update now or later.

**Architecture:** The Tauri shell will add the v2 updater plugin and expose startup-safe updater behavior through the frontend. React will add a desktop-only updater bridge plus a dismissible update banner so the main UI always opens first, while updater state changes remain non-blocking. Release packaging will be prepared so packaged builds can later read real GitHub Releases metadata without changing the UI contract.

**Tech Stack:** Tauri v2, Rust, React 18, TypeScript, Vite, Vitest, PowerShell packaging scripts.

---

## File map

- Modify: `E:\claude code test\src-tauri\Cargo.toml`
  - Add Tauri updater plugin dependency.
- Modify: `E:\claude code test\src-tauri\tauri.conf.json`
  - Add updater plugin config, Windows installer mode, endpoints placeholder, and updater public key placeholder handling comments where supported.
- Modify: `E:\claude code test\src-tauri\src\main.rs`
  - Register updater plugin at app startup.
- Create: `E:\claude code test\src\desktopUpdater.ts`
  - Frontend bridge for desktop-only updater calls and state normalization.
- Create: `E:\claude code test\src\components\DesktopUpdateBanner.tsx`
  - Chinese update prompt banner with `立即更新` and `稍後再說`.
- Modify: `E:\claude code test\src\components\MarketDataProvider.tsx`
  - Trigger a single startup update check in desktop runtime and push status into store.
- Modify: `E:\claude code test\src\store.ts`
  - Add updater state and actions, including one-launch dismissal.
- Modify: `E:\claude code test\src\App.tsx`
  - Render update banner near existing desktop backend banner without blocking routes.
- Modify: `E:\claude code test\src\types\desktop.ts`
  - Add desktop updater types shared by store and UI.
- Create: `E:\claude code test\src\components\DesktopUpdateBanner.test.tsx`
  - UI tests for available/dismissed/updating flows.
- Modify: `E:\claude code test\src\components\MarketDataProvider.test.tsx`
  - Verify startup update check behavior in desktop runtime.
- Modify: `E:\claude code test\package.json`
  - Ensure any required updater-related frontend package is available if needed.
- Modify: `E:\claude code test\scripts\package_desktop.ps1`
  - Add release-artifact sanity checks or comments to support updater packaging flow.
- Modify: `E:\claude code test\docs\superpowers\specs\2026-04-04-optional-desktop-update-design.md`
  - Optional tiny note if implementation needs one explicit assumption update.

## Assumptions

- The current workspace is not a git repository, so commit steps are intentionally omitted.
- The first implementation will wire the updater end-to-end in code, but production auto-update still depends on real GitHub Releases metadata and signing values being supplied later.
- The app should not show updater UI in browser/dev-only runtime.

### Task 1: Add failing frontend tests for updater banner behavior

**Files:**
- Create: `E:\claude code test\src\components\DesktopUpdateBanner.test.tsx`
- Modify: `E:\claude code test\src\types\desktop.ts`
- Modify: `E:\claude code test\src\store.ts`

- [ ] **Step 1: Write the failing test for visible update prompt**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DesktopUpdateBanner } from "./DesktopUpdateBanner";

describe("DesktopUpdateBanner", () => {
  it("shows update copy and actions when a newer version is available", () => {
    render(
      <DesktopUpdateBanner
        state={{
          status: "available",
          currentVersion: "0.1.0",
          availableVersion: "0.1.1",
          message: "發現新版本 0.1.1",
        }}
        isUpdating={false}
        onUpdateNow={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByText("發現新版本")).toBeInTheDocument();
    expect(screen.getByText("立即更新")).toBeInTheDocument();
    expect(screen.getByText("稍後再說")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
npm test -- src/components/DesktopUpdateBanner.test.tsx
```
Expected: FAIL because `DesktopUpdateBanner` and/or updater state types do not exist yet.

- [ ] **Step 3: Add minimal shared types for updater state**

```ts
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
```

- [ ] **Step 4: Add minimal store shape to support updater UI**

```ts
interface MarketState {
  desktopUpdate: DesktopUpdateState;
  setDesktopUpdate: (state: DesktopUpdateState) => void;
  dismissDesktopUpdate: () => void;
}
```

- [ ] **Step 5: Run test to confirm it still fails for missing component only**

Run:
```powershell
npm test -- src/components/DesktopUpdateBanner.test.tsx
```
Expected: FAIL referencing missing component export or render behavior.

### Task 2: Implement updater banner UI in Chinese

**Files:**
- Create: `E:\claude code test\src\components\DesktopUpdateBanner.tsx`
- Create: `E:\claude code test\src\components\DesktopUpdateBanner.test.tsx`

- [ ] **Step 1: Add second failing test for dismiss/update callbacks**

```tsx
it("calls the correct handlers for update now and dismiss", () => {
  const onUpdateNow = vi.fn();
  const onDismiss = vi.fn();

  render(
    <DesktopUpdateBanner
      state={{ status: "available", currentVersion: "0.1.0", availableVersion: "0.1.1" }}
      isUpdating={false}
      onUpdateNow={onUpdateNow}
      onDismiss={onDismiss}
    />,
  );

  fireEvent.click(screen.getByText("立即更新"));
  fireEvent.click(screen.getByText("稍後再說"));

  expect(onUpdateNow).toHaveBeenCalledTimes(1);
  expect(onDismiss).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
npm test -- src/components/DesktopUpdateBanner.test.tsx
```
Expected: FAIL because component behavior is not implemented yet.

- [ ] **Step 3: Write minimal banner component**

```tsx
import type { CSSProperties } from "react";
import type { DesktopUpdateState } from "../types/desktop";

interface DesktopUpdateBannerProps {
  state: DesktopUpdateState;
  isUpdating: boolean;
  onUpdateNow: () => void;
  onDismiss: () => void;
}

export function DesktopUpdateBanner({ state, isUpdating, onUpdateNow, onDismiss }: DesktopUpdateBannerProps) {
  if (state.status !== "available" && state.status !== "downloading" && state.status !== "installing" && state.status !== "error") {
    return null;
  }

  const busy = state.status === "downloading" || state.status === "installing" || isUpdating;
  const title = state.status === "error" ? "更新失敗" : "發現新版本";
  const body =
    state.message ??
    `目前版本 ${state.currentVersion ?? "--"}，可更新為 ${state.availableVersion ?? "--"}。你可以現在更新，或稍後再說。`;

  return (
    <div role="status" aria-live="polite">
      <strong>{title}</strong>
      <span>{body}</span>
      <button type="button" onClick={onUpdateNow} disabled={busy}>立即更新</button>
      <button type="button" onClick={onDismiss} disabled={busy}>稍後再說</button>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```powershell
npm test -- src/components/DesktopUpdateBanner.test.tsx
```
Expected: PASS

### Task 3: Add desktop updater bridge and startup check contract

**Files:**
- Create: `E:\claude code test\src\desktopUpdater.ts`
- Modify: `E:\claude code test\src\components\MarketDataProvider.test.tsx`
- Modify: `E:\claude code test\src\components\MarketDataProvider.tsx`
- Modify: `E:\claude code test\src\store.ts`

- [ ] **Step 1: Add failing MarketDataProvider test for desktop startup update check**

```tsx
it("checks desktop updates once on startup in desktop runtime", async () => {
  const checkForDesktopUpdate = vi.fn().mockResolvedValue({
    status: "available",
    currentVersion: "0.1.0",
    availableVersion: "0.1.1",
  });

  vi.doMock("../desktopUpdater", () => ({
    checkForDesktopUpdate,
    installDesktopUpdate: vi.fn(),
  }));

  renderProviderInDesktopRuntime();

  await waitFor(() => expect(checkForDesktopUpdate).toHaveBeenCalledTimes(1));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
npm test -- src/components/MarketDataProvider.test.tsx
```
Expected: FAIL because updater check is not wired.

- [ ] **Step 3: Implement minimal desktop updater bridge**

```ts
import { relaunch } from "@tauri-apps/plugin-process";
import { check } from "@tauri-apps/plugin-updater";
import { isDesktopRuntime } from "./desktopBridge";
import type { DesktopUpdateState } from "./types/desktop";

export async function checkForDesktopUpdate(): Promise<DesktopUpdateState> {
  if (!isDesktopRuntime()) {
    return { status: "idle" };
  }

  const update = await check();
  if (!update?.available) {
    return { status: "upToDate", currentVersion: update?.currentVersion };
  }

  return {
    status: "available",
    currentVersion: update.currentVersion,
    availableVersion: update.version,
    notes: update.body,
    message: `目前版本 ${update.currentVersion}，可更新為 ${update.version}。你可以現在更新，或稍後再說。`,
  };
}

export async function installDesktopUpdate(onProgress?: (state: DesktopUpdateState) => void): Promise<DesktopUpdateState> {
  const update = await check();
  if (!update?.available) {
    return { status: "upToDate", currentVersion: update?.currentVersion };
  }

  onProgress?.({ status: "downloading", currentVersion: update.currentVersion, availableVersion: update.version, message: "正在下載更新…" });
  await update.downloadAndInstall();
  onProgress?.({ status: "installing", currentVersion: update.currentVersion, availableVersion: update.version, message: "下載完成，準備安裝…" });
  await relaunch();
  return { status: "installing", currentVersion: update.currentVersion, availableVersion: update.version };
}
```

- [ ] **Step 4: Wire startup check into MarketDataProvider**

```tsx
useEffect(() => {
  if (!isDesktopRuntime()) {
    return;
  }

  let active = true;
  useMarketStore.getState().setDesktopUpdate({ status: "checking" });

  void checkForDesktopUpdate()
    .then((state) => {
      if (active) {
        useMarketStore.getState().setDesktopUpdate(state);
      }
    })
    .catch((error) => {
      if (active) {
        useMarketStore.getState().setDesktopUpdate({
          status: "error",
          message: error instanceof Error ? error.message : "更新檢查失敗",
        });
      }
    });

  return () => {
    active = false;
  };
}, []);
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```powershell
npm test -- src/components/MarketDataProvider.test.tsx
```
Expected: PASS

### Task 4: Render the update prompt in the app shell flow

**Files:**
- Modify: `E:\claude code test\src\App.tsx`
- Modify: `E:\claude code test\src\store.ts`
- Modify: `E:\claude code test\src\components\DesktopUpdateBanner.test.tsx`

- [ ] **Step 1: Add failing test for dismiss-once behavior**

```tsx
it("hides the banner after choosing 稍後再說", () => {
  const Wrapper = () => {
    const [dismissed, setDismissed] = useState(false);
    return dismissed ? null : (
      <DesktopUpdateBanner
        state={{ status: "available", currentVersion: "0.1.0", availableVersion: "0.1.1" }}
        isUpdating={false}
        onUpdateNow={vi.fn()}
        onDismiss={() => setDismissed(true)}
      />
    );
  };

  render(<Wrapper />);
  fireEvent.click(screen.getByText("稍後再說"));
  expect(screen.queryByText("發現新版本")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails if store/app wiring is missing**

Run:
```powershell
npm test -- src/components/DesktopUpdateBanner.test.tsx
```
Expected: FAIL or incomplete coverage until app/store wiring is added.

- [ ] **Step 3: Add app slot and store actions for update banner**

```tsx
function DesktopUpdateBannerSlot() {
  const updateState = useMarketStore((state) => state.desktopUpdate);
  const setDesktopUpdate = useMarketStore((state) => state.setDesktopUpdate);
  const dismissDesktopUpdate = useMarketStore((state) => state.dismissDesktopUpdate);
  const [isUpdating, setIsUpdating] = useState(false);

  const handleUpdateNow = async () => {
    setIsUpdating(true);
    try {
      await installDesktopUpdate((nextState) => setDesktopUpdate(nextState));
    } catch (error) {
      setDesktopUpdate({
        status: "error",
        currentVersion: updateState.currentVersion,
        availableVersion: updateState.availableVersion,
        message: error instanceof Error ? error.message : "更新安裝失敗",
      });
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <DesktopUpdateBanner
      state={updateState}
      isUpdating={isUpdating}
      onUpdateNow={() => void handleUpdateNow()}
      onDismiss={dismissDesktopUpdate}
    />
  );
}
```

- [ ] **Step 4: Run banner tests to verify they pass**

Run:
```powershell
npm test -- src/components/DesktopUpdateBanner.test.tsx
```
Expected: PASS

### Task 5: Enable Tauri updater plugin in desktop shell

**Files:**
- Modify: `E:\claude code test\src-tauri\Cargo.toml`
- Modify: `E:\claude code test\src-tauri\src\main.rs`
- Modify: `E:\claude code test\src-tauri\tauri.conf.json`

- [ ] **Step 1: Add a failing desktop build check expectation**

Run:
```powershell
npm run desktop:build
```
Expected: FAIL because updater plugin dependencies/config are not yet present or invalid.

- [ ] **Step 2: Add updater plugin dependency and register it**

```toml
[dependencies]
tauri = { version = "2.0", features = [] }
tauri-plugin-updater = "2"
tauri-plugin-process = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

```rust
fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(backend::BackendState::default())
        // existing setup omitted
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // existing run handler
}
```

- [ ] **Step 3: Add updater config skeleton**

```json
{
  "plugins": {
    "updater": {
      "active": true,
      "windows": {
        "installMode": "basicUi"
      },
      "endpoints": [
        "https://github.com/<owner>/<repo>/releases/latest/download/latest.json"
      ],
      "pubkey": "REPLACE_WITH_TAURI_UPDATER_PUBLIC_KEY"
    }
  }
}
```

- [ ] **Step 4: Run desktop build to verify config compiles**

Run:
```powershell
npm run desktop:build
```
Expected: PASS if updater config and dependencies are valid; if release endpoint/pubkey placeholders are not acceptable for build, adjust to environment-driven placeholders before re-running.

### Task 6: Prepare packaging and verify full app behavior

**Files:**
- Modify: `E:\claude code test\scripts\package_desktop.ps1`
- Modify: `E:\claude code test\package.json`
- Modify: `E:\claude code test\docs\superpowers\specs\2026-04-04-optional-desktop-update-design.md`

- [ ] **Step 1: Add packaging script sanity check for updater prerequisites**

```powershell
if (-not $env:TAURI_UPDATER_PRIVATE_KEY) {
  Write-Warning "TAURI_UPDATER_PRIVATE_KEY 尚未設定，桌面安裝包可建立，但正式自動更新 metadata 無法簽章。"
}
if (-not $env:TAURI_UPDATER_KEY_PASSWORD) {
  Write-Warning "TAURI_UPDATER_KEY_PASSWORD 尚未設定，若需要簽章 updater 產物請先補齊。"
}
```

- [ ] **Step 2: Run full frontend verification**

Run:
```powershell
npm test
npm run build
```
Expected: All PASS

- [ ] **Step 3: Run packaged desktop verification**

Run:
```powershell
npm run desktop:package
```
Expected: PASS, producing installer artifacts while warning (not failing) if signing env vars are missing.

- [ ] **Step 4: Record implementation note in spec if runtime assumptions changed**

```md
## Implementation note

第一版 updater UI 已落地；正式自動更新仍需 GitHub Releases 最新版本 metadata 與 Tauri updater signing key 完成配置後才可供終端使用者下載安裝。
```

- [ ] **Step 5: Final verification summary**

Run:
```powershell
npm test
npm run build
npm run desktop:build
npm run desktop:package
```
Expected: PASS with only non-blocking warnings for missing release signing variables.

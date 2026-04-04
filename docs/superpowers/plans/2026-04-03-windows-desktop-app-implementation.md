# Windows Desktop App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將目前的 React 前端與 Python 後端整合為 `Windows 專用、完全自包含` 的 Tauri 桌面 App，啟動時自動在背景拉起 Python sidecar，關閉視窗時一併結束。

**Architecture:** 使用 Tauri 作為桌面殼層，前端沿用既有 Vite build，新增一個桌面專用的 Python 啟動入口作為 sidecar。前端預設先開啟主畫面，再透過桌面橋接層檢測後端狀態並提供重試能力；後端啟停由 Tauri 控制，不讓使用者看到額外 console 視窗。

**Tech Stack:** React 18 + Vite + TypeScript、Python 3.11、Tauri 2.x、Rust、Windows installer bundling

---

## File Structure

### New files

- Create: `E:\claude code test\src-tauri\Cargo.toml`
- Create: `E:\claude code test\src-tauri\tauri.conf.json`
- Create: `E:\claude code test\src-tauri\src\main.rs`
- Create: `E:\claude code test\src-tauri\src\backend.rs`
- Create: `E:\claude code test\desktop_backend.py`
- Create: `E:\claude code test\src\desktopBridge.ts`
- Create: `E:\claude code test\src\types\desktop.ts`
- Create: `E:\claude code test\src\components\DesktopBackendBanner.tsx`
- Create: `E:\claude code test\src\components\DesktopBackendBanner.test.tsx`
- Create: `E:\claude code test\scripts\package_desktop.ps1`

### Modified files

- Modify: `E:\claude code test\package.json`
- Modify: `E:\claude code test\src\App.tsx`
- Modify: `E:\claude code test\src\components\AppShell.tsx`
- Modify: `E:\claude code test\src\components\MarketDataProvider.tsx`
- Modify: `E:\claude code test\src\store.ts`
- Modify: `E:\claude code test\requirements.txt`
- Modify: `E:\claude code test\README` or desktop docs file if one is added later

### Responsibilities

- `desktop_backend.py`: 桌面版後端入口；統一 `.env` 載入、工作目錄、子程序啟動與退出碼處理
- `src-tauri/src/main.rs`: Tauri 視窗與 app lifecycle 入口
- `src-tauri/src/backend.rs`: sidecar 啟動、關閉、健康檢查、重試命令
- `src/desktopBridge.ts`: 前端呼叫 Tauri 命令的薄封裝
- `src/types/desktop.ts`: 桌面狀態型別契約
- `DesktopBackendBanner.tsx`: 後端啟動中 / 失敗 / 可重試狀態 UI

## Task 1: Scaffold Tauri Shell

**Files:**
- Create: `E:\claude code test\src-tauri\Cargo.toml`
- Create: `E:\claude code test\src-tauri\tauri.conf.json`
- Create: `E:\claude code test\src-tauri\src\main.rs`
- Modify: `E:\claude code test\package.json`

- [ ] **Step 1: Write the failing setup test/verification command**

Use the shell command below to confirm Tauri is not initialized yet:

```powershell
Test-Path .\src-tauri\tauri.conf.json
```

Expected: `False`

- [ ] **Step 2: Initialize minimal Tauri project files**

Create a minimal `Cargo.toml`:

```toml
[package]
name = "taiwan-alpha-radar"
version = "0.1.0"
edition = "2021"

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

Create a minimal `src-tauri/src/main.rs`:

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("failed to run tauri app");
}
```

- [ ] **Step 3: Add desktop scripts to `package.json`**

Add scripts like:

```json
{
  "scripts": {
    "desktop:dev": "tauri dev",
    "desktop:build": "tauri build"
  }
}
```

- [ ] **Step 4: Run a config-level verification**

Run:

```powershell
Get-ChildItem .\src-tauri
```

Expected: contains `Cargo.toml`, `tauri.conf.json`, `src`

- [ ] **Step 5: Commit**

Workspace is currently not a git repo. If git is initialized later, use:

```bash
git add package.json src-tauri
git commit -m "feat: scaffold tauri desktop shell"
```

## Task 2: Create Desktop Python Entry Point

**Files:**
- Create: `E:\claude code test\desktop_backend.py`
- Modify: `E:\claude code test\requirements.txt`
- Test: `E:\claude code test\test_run.py`

- [ ] **Step 1: Write the failing verification**

Run:

```powershell
python -m py_compile desktop_backend.py
```

Expected: file not found / compile failure

- [ ] **Step 2: Write the minimal desktop backend wrapper**

Create `desktop_backend.py` with a structure like:

```python
from __future__ import annotations

import os
import pathlib
import runpy
import sys

from dotenv import load_dotenv


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    os.chdir(root)
    load_dotenv(root / ".env")
    runpy.run_path(str(root / "run.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Add a focused regression test**

Add a test to `test_run.py` that verifies the desktop entry point loads `.env` from the project root and delegates to `run.py` without changing CLI behavior.

Example test shape:

```python
def test_desktop_backend_uses_project_root(monkeypatch, tmp_path):
    ...
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest test_run.py -q
python -m py_compile desktop_backend.py run.py
```

Expected: tests pass and compile succeeds

- [ ] **Step 5: Commit**

```bash
git add desktop_backend.py test_run.py requirements.txt
git commit -m "feat: add desktop backend entry point"
```

## Task 3: Add Tauri Sidecar Lifecycle Management

**Files:**
- Create: `E:\claude code test\src-tauri\src\backend.rs`
- Modify: `E:\claude code test\src-tauri\src\main.rs`
- Modify: `E:\claude code test\src-tauri\tauri.conf.json`

- [ ] **Step 1: Write the failing behavior description**

Document the expected lifecycle:

```text
App launch -> start sidecar
Window close -> stop sidecar
Retry action -> restart sidecar
```

Then verify no sidecar management module exists:

```powershell
Test-Path .\src-tauri\src\backend.rs
```

Expected: `False`

- [ ] **Step 2: Implement minimal sidecar state manager**

Create `backend.rs` with:

```rust
use std::sync::Mutex;
use tauri::{AppHandle, Manager};

pub struct BackendState {
    pub child: Mutex<Option<tauri::process::CommandChild>>,
}
```

Add commands for:
- `start_backend`
- `stop_backend`
- `restart_backend`
- `backend_status`

- [ ] **Step 3: Wire sidecar startup into `main.rs`**

Update `main.rs` to:

```rust
mod backend;

fn main() {
    tauri::Builder::default()
        .manage(backend::BackendState::default())
        .invoke_handler(tauri::generate_handler![
            backend::start_backend,
            backend::stop_backend,
            backend::restart_backend,
            backend::backend_status,
        ])
        .setup(|app| {
            backend::start_backend_internal(app.handle())?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run tauri app");
}
```

- [ ] **Step 4: Configure the sidecar in `tauri.conf.json`**

Add a bundle/sidecar entry for the Python backend artifact so Tauri includes it in the Windows package.

- [ ] **Step 5: Run Rust config verification**

Run:

```powershell
Get-Content .\src-tauri\src\main.rs
Get-Content .\src-tauri\src\backend.rs
```

Expected: startup, shutdown, retry commands are wired

- [ ] **Step 6: Commit**

```bash
git add src-tauri/src/main.rs src-tauri/src/backend.rs src-tauri/tauri.conf.json
git commit -m "feat: manage python sidecar lifecycle from tauri"
```

## Task 4: Add Desktop Bridge in the Frontend

**Files:**
- Create: `E:\claude code test\src\desktopBridge.ts`
- Create: `E:\claude code test\src\types\desktop.ts`
- Modify: `E:\claude code test\src\App.tsx`
- Test: `E:\claude code test\src\components\DesktopBackendBanner.test.tsx`

- [ ] **Step 1: Write the failing test**

Create a test proving the frontend can render a backend-error state without crashing:

```tsx
it("shows backend retry UI when desktop backend is unavailable", () => {
  ...
})
```

- [ ] **Step 2: Add typed desktop bridge**

Create `desktopBridge.ts` with functions:

```ts
export async function getDesktopBackendStatus(): Promise<DesktopBackendStatus> {}
export async function restartDesktopBackend(): Promise<void> {}
export function isDesktopRuntime(): boolean {}
```

- [ ] **Step 3: Add desktop types**

Create `DesktopBackendStatus` like:

```ts
export type DesktopBackendPhase = "idle" | "starting" | "running" | "error";

export interface DesktopBackendStatus {
  phase: DesktopBackendPhase;
  message?: string;
}
```

- [ ] **Step 4: Run targeted frontend test**

Run:

```powershell
npm test -- DesktopBackendBanner.test.tsx
```

Expected: failing test becomes passing after bridge/type integration

- [ ] **Step 5: Commit**

```bash
git add src/desktopBridge.ts src/types/desktop.ts src/App.tsx src/components/DesktopBackendBanner.test.tsx
git commit -m "feat: add desktop backend bridge"
```

## Task 5: Render Backend Status Banner and Retry Entry

**Files:**
- Create: `E:\claude code test\src\components\DesktopBackendBanner.tsx`
- Modify: `E:\claude code test\src\App.tsx`
- Modify: `E:\claude code test\src\components\AppShell.tsx`
- Test: `E:\claude code test\src\components\DesktopBackendBanner.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create assertions for:

```tsx
expect(screen.getByText("後端啟動中")).toBeInTheDocument()
expect(screen.getByRole("button", { name: "重新啟動後端" })).toBeInTheDocument()
```

- [ ] **Step 2: Implement minimal banner component**

Create a component with four states:
- `idle`
- `starting`
- `running` (renders nothing or a compact badge)
- `error`

- [ ] **Step 3: Mount the banner near the app shell / dashboard top area**

Keep the main UI visible even during error state.

- [ ] **Step 4: Run the test suite**

Run:

```powershell
npm test -- DesktopBackendBanner.test.tsx AppShell.test.tsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/DesktopBackendBanner.tsx src/App.tsx src/components/AppShell.tsx src/components/DesktopBackendBanner.test.tsx
git commit -m "feat: show desktop backend status and retry UI"
```

## Task 6: Wire Desktop-Aware Startup and Shutdown

**Files:**
- Modify: `E:\claude code test\src\components\MarketDataProvider.tsx`
- Modify: `E:\claude code test\src\store.ts`
- Modify: `E:\claude code test\src\desktopBridge.ts`
- Test: `E:\claude code test\src\components\MarketDataProvider.test.tsx`

- [ ] **Step 1: Write the failing lifecycle test**

Add a test verifying:
- desktop runtime checks backend state before declaring the app ready
- retry updates the visible state

- [ ] **Step 2: Implement minimal state wiring**

Extend store or component-local state to track desktop backend phase separately from WebSocket connection phase.

- [ ] **Step 3: Preserve browser dev workflow**

Ensure:
- browser/dev mode still works without Tauri
- desktop-only code is gated behind `isDesktopRuntime()`

- [ ] **Step 4: Run tests**

Run:

```powershell
npm test -- MarketDataProvider.test.tsx DesktopBackendBanner.test.tsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/MarketDataProvider.tsx src/store.ts src/desktopBridge.ts src/components/MarketDataProvider.test.tsx
git commit -m "feat: wire desktop backend startup states into frontend"
```

## Task 7: Add Windows Packaging Script and Installer Verification

**Files:**
- Create: `E:\claude code test\scripts\package_desktop.ps1`
- Modify: `E:\claude code test\package.json`
- Modify: `E:\claude code test\requirements.txt`

- [ ] **Step 1: Write the failing packaging command**

Run:

```powershell
Test-Path .\scripts\package_desktop.ps1
```

Expected: `False`

- [ ] **Step 2: Add packaging script**

Create a PowerShell script that:
- builds the frontend
- prepares Python sidecar assets
- invokes `tauri build`

Skeleton:

```powershell
$ErrorActionPreference = "Stop"
npm run build
npm run desktop:build
```

- [ ] **Step 3: Add a package.json wrapper**

Add:

```json
{
  "scripts": {
    "desktop:package": "powershell -ExecutionPolicy Bypass -File scripts/package_desktop.ps1"
  }
}
```

- [ ] **Step 4: Run packaging smoke verification**

Run:

```powershell
npm run desktop:package
```

Expected: installer artifact appears under Tauri bundle output directory

- [ ] **Step 5: Commit**

```bash
git add scripts/package_desktop.ps1 package.json requirements.txt
git commit -m "build: add windows desktop packaging flow"
```

## Task 8: Final End-to-End Verification

**Files:**
- Verify only

- [ ] **Step 1: Run frontend verification**

```powershell
npm test
npm run build
```

Expected: all frontend tests pass, Vite build succeeds

- [ ] **Step 2: Run Python verification**

```powershell
pytest -q
python -m py_compile run.py sinopac_bridge.py notifier.py auto_trader.py analyzer.py main.py desktop_backend.py
```

Expected: Python suite passes; `test_db.py` may skip if optional dependency is unavailable

- [ ] **Step 3: Run desktop smoke test**

```powershell
npm run desktop:dev
```

Manual expectation:
- front window opens
- no extra console window shown to user
- backend starts in background
- closing the app exits the backend

- [ ] **Step 4: Run installer smoke test**

```powershell
npm run desktop:package
```

Manual expectation:
- Windows installer is produced
- app can be installed from installer
- start menu entry appears
- uninstall entry appears

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: ship windows desktop app"
```

## Self-Review

### Spec coverage

- Windows-only Tauri shell: covered by Tasks 1, 3, 7
- Python sidecar background startup: covered by Tasks 2, 3, 6
- Main UI opens even if backend fails: covered by Tasks 4, 5, 6
- Retry button: covered by Tasks 4, 5
- Close window stops backend: covered by Task 3 and verified in Task 8
- General installer output: covered by Tasks 7 and 8

No obvious spec gaps remain.

### Placeholder scan

- No `TODO` or `TBD`
- Every task includes file paths and concrete verification commands
- Desktop smoke steps are intentionally manual where automation would not be reliable

### Type consistency

- Frontend desktop state uses `DesktopBackendStatus` / `DesktopBackendPhase`
- Sidecar lifecycle uses `start / stop / restart / status` consistently across Rust and TS bridge

## Execution Handoff

Plan complete and saved to [2026-04-03-windows-desktop-app-implementation.md](E:\claude code test\docs\superpowers\plans\2026-04-03-windows-desktop-app-implementation.md). Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?


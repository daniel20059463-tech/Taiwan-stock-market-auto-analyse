# Project Tech Debt Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the project by cleaning the worktree, isolating generated artifacts, and reducing the highest-risk code concentration in `auto_trader.py`, `sinopac_bridge.py`, and `run.py` without changing trading behavior.

**Architecture:** Treat this as a staged refactor. First make the repository safe to work in by tightening `.gitignore`, isolating generated files, and separating unrelated changes from the current `main` worktree. Then extract behavior-preserving service boundaries out of the two God Objects so later feature work has clear seams. Finish by adding a lightweight data-correctness audit path and strategy observability hooks so live debugging stops depending on ad-hoc log inspection.

**Tech Stack:** Python, TypeScript/React, pytest, npm/vite, Shioaji runtime, git.

---

## File Map

**Repository hygiene and generated artifacts**
- Modify: `E:\claude code test\.gitignore`
- Verify: `E:\claude code test\logs\`
- Verify: `E:\claude code test\tmp\`
- Verify: `E:\claude code test\src-tauri\target\`
- Verify: `E:\claude code test\flutter_app\build\`

**Core runtime decomposition**
- Modify: `E:\claude code test\auto_trader.py`
- Create: `E:\claude code test\trading\paper_execution.py`
- Create: `E:\claude code test\trading\swing_runtime.py`
- Create: `E:\claude code test\trading\persistence_reporting.py`
- Modify: `E:\claude code test\sinopac_bridge.py`
- Create: `E:\claude code test\quote_runtime\universe_loader.py`
- Create: `E:\claude code test\quote_runtime\subscription_manager.py`
- Create: `E:\claude code test\quote_runtime\native_buffers.py`
- Create: `E:\claude code test\quote_runtime\detail_broadcaster.py`
- Modify: `E:\claude code test\run.py`
- Create: `E:\claude code test\runtime_bootstrap.py`
- Create: `E:\claude code test\strategy_runtime.py`

**Validation and observability**
- Create: `E:\claude code test\data_integrity_audit.py`
- Create: `E:\claude code test\test_data_integrity_audit.py`
- Modify: `E:\claude code test\retail_flow_strategy.py`
- Modify: `E:\claude code test\auto_trader.py`
- Create: `E:\claude code test\test_retail_flow_observability.py`

---

### Task 1: Tighten repository hygiene before more feature work

**Files:**
- Modify: `E:\claude code test\.gitignore`
- Verify: `E:\claude code test\logs\`
- Verify: `E:\claude code test\tmp\`
- Verify: `E:\claude code test\src-tauri\target\`
- Verify: `E:\claude code test\flutter_app\build\`

- [ ] **Step 1: Write a failing check for generated artifacts being tracked**

Create or extend a shell-based verification note in the task log that treats these paths as generated artifacts and expects them to be ignored:

```powershell
git check-ignore -v `
  "logs\example.log" `
  "tmp\example.tmp" `
  "src-tauri\target\debug\dummy.txt" `
  "flutter_app\build\dummy.txt"
```

- [ ] **Step 2: Run the ignore check and confirm at least one path is not yet covered**

Run:

```powershell
git check-ignore -v `
  "logs\example.log" `
  "tmp\example.tmp" `
  "src-tauri\target\debug\dummy.txt" `
  "flutter_app\build\dummy.txt"
```

Expected: at least one path is missing from ignore coverage or inconsistent with the intended cleanup.

- [ ] **Step 3: Add explicit ignore rules**

Update `E:\claude code test\.gitignore` to include clear generated-artifact rules:

```gitignore
# Runtime logs and temp data
logs/
tmp/

# Tauri / Rust build output
src-tauri/target/

# Flutter build output
flutter_app/build/
.dart_tool/
```

- [ ] **Step 4: Re-run ignore verification**

Run:

```powershell
git check-ignore -v `
  "logs\example.log" `
  "tmp\example.tmp" `
  "src-tauri\target\debug\dummy.txt" `
  "flutter_app\build\dummy.txt"
```

Expected: all target paths resolve to the new ignore rules.

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: tighten generated artifact ignores"
```

### Task 2: Isolate worktree risk before refactoring

**Files:**
- Verify only: `E:\claude code test`

- [ ] **Step 1: Inventory current modified and untracked files**

Run:

```powershell
git status --short
```

- [ ] **Step 2: Group work into buckets**

Use the status output to classify every path into:
- runtime/python
- web frontend
- flutter frontend
- docs/specs/plans
- generated artifacts

Record the grouping in the task log so subsequent work does not mix unrelated edits.

- [ ] **Step 3: Verify generated artifacts are now removable from the active change set**

Run:

```powershell
git status --short
```

Expected: generated-artifact paths are absent or ready to be cleaned without touching source files.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: prepare worktree for refactor batching"
```

### Task 3: Extract paper execution responsibilities out of `auto_trader.py`

**Files:**
- Create: `E:\claude code test\trading\paper_execution.py`
- Modify: `E:\claude code test\auto_trader.py`
- Test: `E:\claude code test\test_auto_trader_short_flow.py`
- Test: `E:\claude code test\test_auto_trader_manual_orders.py`

- [ ] **Step 1: Write failing tests around paper execution boundaries**

Add tests that assert `AutoTrader` still:
- records `BUY / SELL`
- records `SHORT / COVER`
- updates `recentTrades`
- updates `PAPER_PORTFOLIO`

but no longer requires paper execution internals to live directly inside `AutoTrader`.

- [ ] **Step 2: Run targeted tests to see red**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q `
  .\test_auto_trader_short_flow.py `
  .\test_auto_trader_manual_orders.py
```

Expected: failure after extracting call sites or after adding new execution-boundary assertions.

- [ ] **Step 3: Extract a focused execution service**

Create `E:\claude code test\trading\paper_execution.py` with one responsibility: translate approved entry/exit instructions into `PaperPosition` and `TradeRecord` mutations.

Target interface:

```python
class PaperExecutionService:
    async def execute_buy(...): ...
    async def execute_sell(...): ...
    async def execute_short(...): ...
    async def execute_cover(...): ...
```

- [ ] **Step 4: Replace direct execution internals in `AutoTrader` with service calls**

Move only behavior-preserving code. Keep:
- risk gating
- signal generation
- strategy state

inside `AutoTrader`, and move:
- position open/close mutation
- record creation
- common persistence hooks

into the new service.

- [ ] **Step 5: Re-run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q `
  .\test_auto_trader_short_flow.py `
  .\test_auto_trader_manual_orders.py
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add .\auto_trader.py .\trading\paper_execution.py .\test_auto_trader_short_flow.py .\test_auto_trader_manual_orders.py
git commit -m "refactor: extract paper execution from auto trader"
```

### Task 4: Extract swing-state runtime logic from `auto_trader.py`

**Files:**
- Create: `E:\claude code test\trading\swing_runtime.py`
- Modify: `E:\claude code test\auto_trader.py`
- Test: `E:\claude code test\test_retail_flow_strategy.py`
- Test: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: Write failing tests for explicit swing runtime states**

Add tests that assert per-symbol swing state is externally observable as:
- `skip`
- `watch`
- `ready_to_buy`
- `entered`

and that state transitions do not spam duplicate entries.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q `
  .\test_retail_flow_strategy.py `
  .\test_auto_trader_decision_reports.py -k swing
```

- [ ] **Step 3: Extract swing runtime coordinator**

Create `E:\claude code test\trading\swing_runtime.py`:

```python
class SwingRuntimeState:
    watch_states: dict[str, str]

class SwingRuntimeCoordinator:
    def classify_entry_state(...): ...
    def should_trigger_entry(...): ...
    def mark_entered(...): ...
    def reset_for_new_day(...): ...
```

- [ ] **Step 4: Rewire `AutoTrader` to delegate swing state transitions**

`AutoTrader` should still own the main tick loop, but should stop owning the low-level swing-state bookkeeping.

- [ ] **Step 5: Re-run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q `
  .\test_retail_flow_strategy.py `
  .\test_auto_trader_decision_reports.py -k swing
```

- [ ] **Step 6: Commit**

```bash
git add .\auto_trader.py .\trading\swing_runtime.py .\test_retail_flow_strategy.py .\test_auto_trader_decision_reports.py
git commit -m "refactor: extract swing runtime state from auto trader"
```

### Task 5: Split `sinopac_bridge.py` into clear runtime units

**Files:**
- Create: `E:\claude code test\quote_runtime\universe_loader.py`
- Create: `E:\claude code test\quote_runtime\subscription_manager.py`
- Create: `E:\claude code test\quote_runtime\native_buffers.py`
- Create: `E:\claude code test\quote_runtime\detail_broadcaster.py`
- Modify: `E:\claude code test\sinopac_bridge.py`
- Test: `E:\claude code test\test_sinopac_bridge.py`

- [ ] **Step 1: Write failing tests around quote-runtime boundaries**

Add tests that keep current behavior but force these seams:
- universe loading remains correct
- visible set subscription remains correct
- native bidask/tick buffers remain correct
- websocket detail snapshots remain correct

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_sinopac_bridge.py
```

- [ ] **Step 3: Extract non-overlapping modules**

Create:

```python
# universe_loader.py
class ShioajiUniverseLoader: ...

# subscription_manager.py
class VisibleSubscriptionManager: ...

# native_buffers.py
class NativeOrderBookBuffers: ...
class NativeTradeTapeBuffers: ...

# detail_broadcaster.py
class QuoteDetailBroadcaster: ...
```

- [ ] **Step 4: Reduce `sinopac_bridge.py` to orchestration**

Keep login/runtime orchestration there. Move:
- contract filtering
- visible subscription bookkeeping
- native detail buffering
- snapshot payload creation

into the extracted modules.

- [ ] **Step 5: Re-run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_sinopac_bridge.py
```

- [ ] **Step 6: Commit**

```bash
git add .\sinopac_bridge.py .\quote_runtime\*.py .\test_sinopac_bridge.py
git commit -m "refactor: split shioaji bridge runtime responsibilities"
```

### Task 6: Reduce `run.py` to bootstrap wiring

**Files:**
- Create: `E:\claude code test\runtime_bootstrap.py`
- Create: `E:\claude code test\strategy_runtime.py`
- Modify: `E:\claude code test\run.py`
- Test: `E:\claude code test\test_run.py`

- [ ] **Step 1: Write failing tests for extracted runtime assembly**

Add tests that lock in:
- strategy dependency assembly
- cache priming
- calendar guard behavior
- runtime component creation

while allowing `run.py` itself to shrink.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_run.py
```

- [ ] **Step 3: Extract bootstrap helpers**

Create:

```python
# strategy_runtime.py
def build_strategy_dependencies(...): ...
def prime_institutional_flow_cache(...): ...

# runtime_bootstrap.py
def build_runtime_components(...): ...
```

- [ ] **Step 4: Rewire `run.py` to thin bootstrap**

After extraction, `run.py` should mainly:
- parse env
- call bootstrap helpers
- start runtime

- [ ] **Step 5: Re-run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_run.py
```

- [ ] **Step 6: Commit**

```bash
git add .\run.py .\runtime_bootstrap.py .\strategy_runtime.py .\test_run.py
git commit -m "refactor: shrink runtime bootstrap entrypoint"
```

### Task 7: Add a data-integrity audit path for live UI correctness

**Files:**
- Create: `E:\claude code test\data_integrity_audit.py`
- Create: `E:\claude code test\test_data_integrity_audit.py`
- Verify: `E:\claude code test\src\workers\data.worker.ts`
- Verify: `E:\claude code test\src\components\QuoteTable.tsx`

- [ ] **Step 1: Write failing tests for price/change/volume sanity checks**

Define tests that reject bad states such as:
- `price` present but `previousClose` mirrored incorrectly
- `changePct` zero while price differs materially from previous close
- suspicious seed/fallback volume during live mode

- [ ] **Step 2: Run targeted test**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_data_integrity_audit.py
```

- [ ] **Step 3: Implement minimal audit module**

Create:

```python
def audit_quote_snapshot(snapshot: dict) -> list[str]:
    ...
```

Return concrete issue codes, not prose.

- [ ] **Step 4: Re-run targeted test**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_data_integrity_audit.py
```

- [ ] **Step 5: Commit**

```bash
git add .\data_integrity_audit.py .\test_data_integrity_audit.py
git commit -m "feat: add quote data integrity audit checks"
```

### Task 8: Add swing-strategy observability

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Modify: `E:\claude code test\retail_flow_strategy.py`
- Create: `E:\claude code test\test_retail_flow_observability.py`

- [ ] **Step 1: Write failing tests for observability hooks**

Add tests that require:
- current watch state visibility per symbol
- explicit reason codes for non-entry
- candidate/watchlist export for the current day

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_observability.py
```

- [ ] **Step 3: Implement minimal observability surfaces**

Expose read-only methods or snapshot fields such as:

```python
def get_retail_flow_watch_state(self, symbol: str) -> str | None: ...
def get_retail_flow_candidates(self) -> list[str]: ...
```

and include non-entry reason codes where decisions are skipped.

- [ ] **Step 4: Re-run targeted tests**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_observability.py
```

- [ ] **Step 5: Commit**

```bash
git add .\auto_trader.py .\retail_flow_strategy.py .\test_retail_flow_observability.py
git commit -m "feat: add retail swing observability surfaces"
```

### Task 9: Full regression and build verification

**Files:**
- Verify only

- [ ] **Step 1: Run focused Python regression**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q `
  .\test_market_calendar.py `
  .\test_run.py `
  .\test_sinopac_bridge.py `
  .\test_retail_flow_strategy.py `
  .\test_auto_trader_decision_reports.py `
  .\test_auto_trader_short_flow.py `
  .\test_auto_trader_manual_orders.py `
  .\test_data_integrity_audit.py `
  .\test_retail_flow_observability.py
```

- [ ] **Step 2: Run compile verification**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m py_compile `
  .\auto_trader.py `
  .\sinopac_bridge.py `
  .\run.py `
  .\market_calendar.py `
  .\runtime_bootstrap.py `
  .\strategy_runtime.py `
  .\data_integrity_audit.py
```

- [ ] **Step 3: Run frontend verification if touched**

Run:

```powershell
npm.cmd test
npm.cmd run build
```

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "test: verify project tech debt remediation baseline"
```


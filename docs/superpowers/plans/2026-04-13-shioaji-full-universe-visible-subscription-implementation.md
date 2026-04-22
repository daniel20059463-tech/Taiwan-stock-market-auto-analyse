# Shioaji 全市場股票池與可見集高頻訂閱 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓台股上市/上櫃普通股完整進入類群股與報價表，但只對可見集股票做高頻即時訂閱。

**Architecture:** 後端在啟動時從 Shioaji 動態建立完整股票池，前端則只把可見集同步給後端更新高頻訂閱。一般類股依 metadata 自動分群，主題群分類保留前端補充映射。

**Tech Stack:** Python, Shioaji, WebSocket, TypeScript, React, Vitest

---

### Task 1: 後端股票池動態載入

**Files:**
- Modify: `E:\claude code test\sinopac_bridge.py`
- Modify: `E:\claude code test\run.py`
- Test: `E:\claude code test\test_sinopac_bridge.py`
- Test: `E:\claude code test\test_run.py`

- [ ] **Step 1: Write the failing Python tests**

Add tests that assert:

```python
def test_loads_full_tw_stock_universe_from_shioaji_contracts():
    universe = load_shioaji_stock_universe(fake_api)
    assert "2330" in universe
    assert "0050" not in universe
    assert universe["2330"]["market"] in {"TSE", "OTC"}


def test_falls_back_to_default_symbols_when_universe_load_fails():
    symbols = resolve_runtime_symbols(use_mock=False, auto_universe_loader=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "2330" in symbols
```

- [ ] **Step 2: Run the targeted Python tests and confirm they fail**

Run:

```powershell
python -m pytest -q E:\claude code test\test_sinopac_bridge.py E:\claude code test\test_run.py
```

Expected: FAIL because `load_shioaji_stock_universe` / `resolve_runtime_symbols` behavior does not exist yet.

- [ ] **Step 3: Implement dynamic universe loading**

In `E:\claude code test\sinopac_bridge.py`, add a helper that:

- reads Shioaji stock contracts
- keeps only `上市 + 上櫃普通股`
- excludes ETF / warrant / odd non-stock contracts
- returns metadata map

In `E:\claude code test\run.py`, use this helper before collector creation when not in mock mode.

- [ ] **Step 4: Re-run targeted Python tests**

Run:

```powershell
python -m pytest -q E:\claude code test\test_sinopac_bridge.py E:\claude code test\test_run.py
```

Expected: PASS for new universe-loading behavior.

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\sinopac_bridge.py E:\claude code test\run.py E:\claude code test\test_sinopac_bridge.py E:\claude code test\test_run.py
git commit -m "feat: load full tw stock universe from shioaji"
```

### Task 2: 後端可見集高頻訂閱控制

**Files:**
- Modify: `E:\claude code test\sinopac_bridge.py`
- Test: `E:\claude code test\test_sinopac_bridge.py`

- [ ] **Step 1: Write the failing Python tests**

Add tests that assert:

```python
def test_set_visible_symbols_updates_high_frequency_subscription_set():
    collector = build_test_collector()
    collector.set_visible_symbols(["2330", "2317"])
    assert collector.visible_symbols == {"2330", "2317"}


def test_setting_same_visible_symbols_twice_does_not_reapply_subscription():
    collector = build_test_collector()
    collector.set_visible_symbols(["2330"])
    collector.set_visible_symbols(["2330"])
    assert collector._subscription_update_count == 1
```

- [ ] **Step 2: Run the targeted Python tests and confirm they fail**

Run:

```powershell
python -m pytest -q E:\claude code test\test_sinopac_bridge.py
```

Expected: FAIL because `set_visible_symbols` and deduplicated subscription behavior do not exist yet.

- [ ] **Step 3: Implement visible-symbol subscription management**

In `E:\claude code test\sinopac_bridge.py`:

- add `visible_symbols`
- add `set_visible_symbols(symbols: list[str])`
- avoid no-op duplicate re-subscribe
- wire the update into the collector transport layer

- [ ] **Step 4: Re-run targeted Python tests**

Run:

```powershell
python -m pytest -q E:\claude code test\test_sinopac_bridge.py
```

Expected: PASS for visible-set management tests.

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\sinopac_bridge.py E:\claude code test\test_sinopac_bridge.py
git commit -m "feat: add visible symbol high-frequency subscriptions"
```

### Task 3: Worker 協議支援 SET_VISIBLE_SYMBOLS

**Files:**
- Modify: `E:\claude code test\src\types\market.ts`
- Modify: `E:\claude code test\src\workers\data.worker.ts`
- Test: `E:\claude code test\src\workers\data.worker.test.ts`

- [ ] **Step 1: Write the failing worker test**

Add a test that asserts:

```ts
it("forwards SET_VISIBLE_SYMBOLS to backend websocket", () => {
  // initialize worker socket mock
  // send SET_VISIBLE_SYMBOLS
  // expect socket.send(JSON.stringify({ type: "set_visible_symbols", symbols: [...] }))
})
```

- [ ] **Step 2: Run the targeted worker test and confirm it fails**

Run:

```powershell
npm.cmd test -- src/workers/data.worker.test.ts
```

Expected: FAIL because worker does not handle `SET_VISIBLE_SYMBOLS` yet.

- [ ] **Step 3: Implement worker message forwarding**

In `E:\claude code test\src\types\market.ts`, add inbound worker message type for `SET_VISIBLE_SYMBOLS`.

In `E:\claude code test\src\workers\data.worker.ts`, on this message:

- update internal tracked visible set if needed
- send backend WebSocket message:

```ts
{ type: "set_visible_symbols", symbols: message.symbols }
```

- [ ] **Step 4: Re-run the worker test**

Run:

```powershell
npm.cmd test -- src/workers/data.worker.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\src\types\market.ts E:\claude code test\src\workers\data.worker.ts E:\claude code test\src\workers\data.worker.test.ts
git commit -m "feat: forward visible symbol updates from worker"
```

### Task 4: 前端類群股改用完整股票池與動態可見集

**Files:**
- Modify: `E:\claude code test\src\components\QuoteTable.tsx`
- Modify: `E:\claude code test\src\components\Dashboard.tsx`
- Modify: `E:\claude code test\src\workerBridge.ts`
- Test: `E:\claude code test\src\components\QuoteTable.test.tsx`
- Test: `E:\claude code test\src\components\Dashboard.test.tsx`

- [ ] **Step 1: Write the failing frontend tests**

Add tests that assert:

```tsx
it("filters category rows from full metadata universe", () => {
  // store with many symbols across markets/sectors
  // expect category tab to show matching rows
})

it("sends visible symbols when category changes", () => {
  // click category tab
  // expect worker bridge to receive SET_VISIBLE_SYMBOLS
})
```

- [ ] **Step 2: Run the targeted frontend tests and confirm they fail**

Run:

```powershell
npm.cmd test -- src/components/QuoteTable.test.tsx src/components/Dashboard.test.tsx
```

Expected: FAIL because visible-set sync and full-universe category logic do not exist yet.

- [ ] **Step 3: Implement full-universe category filtering and visible-set sync**

In `E:\claude code test\src\components\QuoteTable.tsx`:

- derive category rows from full symbol metadata
- keep theme-topic mappings as overlays

In `E:\claude code test\src\components\Dashboard.tsx`:

- compute current visible set from selected category top 60 and selected symbol
- send to worker bridge on category / selection changes

In `E:\claude code test\src\workerBridge.ts`:

- expose helper for `SET_VISIBLE_SYMBOLS`

- [ ] **Step 4: Re-run the targeted frontend tests**

Run:

```powershell
npm.cmd test -- src/components/QuoteTable.test.tsx src/components/Dashboard.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\src\components\QuoteTable.tsx E:\claude code test\src\components\Dashboard.tsx E:\claude code test\src\workerBridge.ts E:\claude code test\src\components\QuoteTable.test.tsx E:\claude code test\src\components\Dashboard.test.tsx
git commit -m "feat: sync dashboard visible symbols with full market universe"
```

### Task 5: 全量驗證

**Files:**
- Modify: none unless fixes are required

- [ ] **Step 1: Run backend test suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS

- [ ] **Step 2: Run frontend test suite**

Run:

```powershell
npm.cmd test
```

Expected: PASS

- [ ] **Step 3: Run production build**

Run:

```powershell
npm.cmd run build
```

Expected: PASS

- [ ] **Step 4: Manual smoke check**

Verify:

- 類群股 `全部` 顯示不再只是 133 檔 universe
- 切分類時表格有變化
- 選股後右側主圖仍正常
- 未選中的大量股票不會全部高頻刷動

- [ ] **Step 5: Commit**

```powershell
git add -A
git commit -m "feat: support full tw stock universe with visible subscriptions"
```


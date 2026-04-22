# Retail Flow Swing Intraday-Verifiable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `retail_flow_swing` verifiable during market hours by driving `watch -> ready_to_buy -> automatic paper trade` from official cached institutional flow plus intraday price and volume confirmation.

**Architecture:** Keep official institutional flow as a daily cache input, then tighten `retail_flow_strategy.py` and `auto_trader.py` so intraday state transitions are explicit and testable. Do not add new data sources or change the existing paper-trade transport.

**Tech Stack:** Python, pytest, existing AutoTrader runtime, official TWSE/TPEX JSON providers.

---

### Task 1: Tighten strategy state transitions

**Files:**
- Modify: `E:\claude code test\retail_flow_strategy.py`
- Test: `E:\claude code test\test_retail_flow_strategy.py`

- [ ] **Step 1: Write failing tests for `consecutive_trust_days >= 2` and `ready_to_buy`**

Add tests that require:
- `watch` when `consecutive_trust_days=1`
- `ready_to_buy` when all conditions pass and `consecutive_trust_days=2`

- [ ] **Step 2: Run test to verify it fails if logic is not yet strict enough**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_strategy.py`

- [ ] **Step 3: Implement minimal strategy changes**

Ensure `classify_watch_state()` enforces:
- `skip` when flow score <= 0
- `skip` when recent run-up is too high
- `watch` when trust streak < 2
- `ready_to_buy` only when above `MA10`, volume confirmed, trust streak >= 2

- [ ] **Step 4: Run tests**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_strategy.py`

- [ ] **Step 5: Commit**

```bash
git add .\retail_flow_strategy.py .\test_retail_flow_strategy.py
git commit -m "feat: tighten retail swing intraday watch states"
```

### Task 2: Make AutoTrader trigger automatic paper trades from `ready_to_buy`

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Test: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: Write failing test for automatic paper trade when swing state becomes `ready_to_buy`**

Add a test that primes:
- cached institutional row
- trust streak >= 2
- above `MA10`
- confirmed volume

Assert:
- `paper buy` path executes
- `DecisionReport` reflects swing entry

- [ ] **Step 2: Run targeted test**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_auto_trader_decision_reports.py -k swing`

- [ ] **Step 3: Implement minimal AutoTrader adjustments**

In `auto_trader.py`:
- compute explicit intraday swing state
- trigger buy only once on transition into `ready_to_buy`
- keep exit logic unchanged

- [ ] **Step 4: Run targeted test again**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_auto_trader_decision_reports.py -k swing`

- [ ] **Step 5: Commit**

```bash
git add .\auto_trader.py .\test_auto_trader_decision_reports.py
git commit -m "feat: wire intraday-verifiable swing paper trades"
```

### Task 3: Validate startup cache priming and runtime wiring

**Files:**
- Modify: `E:\claude code test\run.py`
- Test: `E:\claude code test\test_run.py`

- [ ] **Step 1: Write failing test for non-empty swing cache prime and dependency wiring**

Add/adjust tests so startup verifies:
- official provider rows are stored in cache
- `retail_flow_swing` mode still constructs correct dependencies

- [ ] **Step 2: Run targeted tests**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_run.py -k retail_flow`

- [ ] **Step 3: Implement minimal runtime adjustments**

If needed, adjust `run.py` so:
- cache prime remains explicit
- logs make it clear when swing cache is empty vs primed

- [ ] **Step 4: Re-run targeted tests**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_run.py -k retail_flow`

- [ ] **Step 5: Commit**

```bash
git add .\run.py .\test_run.py
git commit -m "chore: validate retail swing cache prime on startup"
```

### Task 4: Full regression and smoke-prep verification

**Files:**
- Verify only

- [ ] **Step 1: Run combined Python regression**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_institutional_flow_provider.py .\test_institutional_flow_cache.py .\test_retail_flow_strategy.py .\test_auto_trader_decision_reports.py .\test_run.py`

- [ ] **Step 2: Run compile check**

Run: `E:\claude code test\.venv\Scripts\python.exe -m py_compile .\institutional_flow_provider.py .\institutional_flow_cache.py .\retail_flow_strategy.py .\auto_trader.py .\run.py`

- [ ] **Step 3: Manual runtime check**

Run a short startup with `STRATEGY_MODE=retail_flow_swing` and verify:
- live runtime starts
- cache prime row count is non-zero
- logs do not show strategy wiring errors

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "test: verify intraday-verifiable retail swing runtime"
```

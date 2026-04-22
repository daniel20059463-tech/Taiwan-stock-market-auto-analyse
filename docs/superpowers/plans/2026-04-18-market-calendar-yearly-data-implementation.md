# Market Calendar Yearly Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the TWSE market calendar from a single hard-coded year to a year-based data-file loader with a ready 2027 placeholder.

**Architecture:** Keep market-calendar logic thin. Store yearly open-date lists in `data/market_calendar/`, load by year in `market_calendar.py`, and preserve fail-closed behavior for missing or empty years.

**Tech Stack:** Python, JSON data files, pytest.

---

### Task 1: Add 2027 yearly data skeleton

**Files:**
- Create: `E:\claude code test\data\market_calendar\twse_open_dates_2027.json`
- Test: `E:\claude code test\test_market_calendar.py`

- [ ] **Step 1: Write failing test for 2027 empty placeholder behavior**

Add a test asserting:
- a 2027 date returns `False`
- loader handles the 2027 file without crashing

- [ ] **Step 2: Run targeted test**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_market_calendar.py -k 2027`

- [ ] **Step 3: Create 2027 JSON skeleton**

Create `twse_open_dates_2027.json` with:
- `exchange`
- `timezone`
- `source_note`
- empty `open_dates`

- [ ] **Step 4: Re-run targeted test**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_market_calendar.py -k 2027`

- [ ] **Step 5: Commit**

```bash
git add .\data\market_calendar\twse_open_dates_2027.json .\test_market_calendar.py
git commit -m "chore: add 2027 TWSE calendar placeholder"
```

### Task 2: Refactor loader to resolve per-year files

**Files:**
- Modify: `E:\claude code test\market_calendar.py`
- Test: `E:\claude code test\test_market_calendar.py`

- [ ] **Step 1: Write failing tests for yearly file resolution**

Add tests that cover:
- loading 2026 from its file
- loading 2027 from its own file
- returning `False` if a year file is absent

- [ ] **Step 2: Run tests**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_market_calendar.py`

- [ ] **Step 3: Implement yearly loader**

In `market_calendar.py`:
- resolve the JSON path by year
- cache loaded years
- fail closed on missing file or empty year data

- [ ] **Step 4: Re-run tests**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_market_calendar.py`

- [ ] **Step 5: Commit**

```bash
git add .\market_calendar.py .\test_market_calendar.py
git commit -m "refactor: load TWSE market calendar by year"
```

### Task 3: Verify runtime and trading-hours integration still holds

**Files:**
- Verify: `E:\claude code test\run.py`
- Verify: `E:\claude code test\auto_trader.py`
- Test: `E:\claude code test\test_run.py`
- Test: `E:\claude code test\test_auto_trader_market_hours.py`

- [ ] **Step 1: Run integration-facing tests**

Run: `E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_market_calendar.py .\test_auto_trader_market_hours.py .\test_run.py`

- [ ] **Step 2: If any assumptions break, adjust callers minimally**

Only patch `run.py` / `auto_trader.py` if the new loader changes signatures or error handling.

- [ ] **Step 3: Run compile check**

Run: `E:\claude code test\.venv\Scripts\python.exe -m py_compile .\market_calendar.py .\run.py .\auto_trader.py`

- [ ] **Step 4: Commit**

```bash
git add .\market_calendar.py .\run.py .\auto_trader.py .\test_auto_trader_market_hours.py .\test_run.py
git commit -m "test: verify yearly market calendar integration"
```

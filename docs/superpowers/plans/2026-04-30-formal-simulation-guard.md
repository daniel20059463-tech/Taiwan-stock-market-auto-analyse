# Formal Simulation Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure tomorrow's formal simulation only runs with 1,000,000 TWD capital, live Sinopac feed, fresh sector cache, and runtime-origin EOD Telegram reports.

**Architecture:** Add a small preflight module for formal-simulation invariants, wire it into `run.py` before live startup, and require `runtime_eod` source on Telegram daily reports. Keep the changes narrow and test-driven.

**Tech Stack:** Python, pytest, dotenv, urllib, existing sector signal cache and daily report pipeline

---

### Task 1: Formal simulation preflight module

**Files:**
- Create: `E:\claude code test\formal_simulation.py`
- Create: `E:\claude code test\tests\test_formal_simulation.py`

- [ ] Add result dataclass and preflight function for capital, mock mode, Telegram, and sector cache checks.
- [ ] Add focused unit tests for pass/fail cases.

### Task 2: Runtime startup guard

**Files:**
- Modify: `E:\claude code test\run.py`
- Test: `E:\claude code test\tests\test_formal_simulation.py`

- [ ] Call preflight before live startup when `SINOPAC_MOCK=false`.
- [ ] Abort startup with explicit log if preflight fails.

### Task 3: Daily report source validation

**Files:**
- Modify: `E:\claude code test\trading\reporting.py`
- Modify: `E:\claude code test\daily_reporter.py`
- Modify: `E:\claude code test\auto_trader.py`
- Modify: `E:\claude code test\test_daily_reporter.py`
- Modify: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] Stamp runtime-built EOD payloads with `source="runtime_eod"`.
- [ ] Reject non-runtime payloads in `DailyReporter.build_and_send`.
- [ ] Update tests for accepted and rejected sources.

### Task 4: Preflight CLI

**Files:**
- Create: `E:\claude code test\scripts\run_formal_simulation_preflight.py`
- Test: `E:\claude code test\tests\test_formal_simulation.py`

- [ ] Add a CLI that loads `.env`, runs preflight, prints JSON, and returns non-zero on failure.

### Task 5: Verification

**Files:**
- N/A

- [ ] Run:
  - `.\.venv\Scripts\python.exe -m pytest -q tests\test_formal_simulation.py test_daily_reporter.py test_auto_trader_decision_reports.py`
  - `.\.venv\Scripts\python.exe .\scripts\run_formal_simulation_preflight.py`

# Visible History Preload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preload daily K-line cache for the currently visible stocks at dashboard startup so daily, weekly, and monthly charts do not wait for first-click fetches.

**Architecture:** The dashboard computes a small visible-symbol slice and sends it through the existing worker bridge. The worker forwards a new websocket message to the backend bridge. The backend runs cache warming in the background, writes results into `data/daily_price_cache.json`, and keeps `history_bars` reading from that cache first.

**Tech Stack:** React, TypeScript worker, Python websocket bridge, local JSON daily price cache

---

### Task 1: Add preload message types

**Files:**
- Modify: `E:\claude code test\src\types\market.ts`

- [ ] Add a worker inbound message type for history preloading with `symbols` and optional `months`.
- [ ] Include the new type in `WorkerInboundMessage`.

### Task 2: Forward preload requests from worker to backend

**Files:**
- Modify: `E:\claude code test\src\workers\data.worker.ts`

- [ ] Handle `PRELOAD_HISTORY` in `self.onmessage`.
- [ ] When websocket is open, send `{ type: "preload_history", symbols, months }`.
- [ ] Ignore empty symbol lists.

### Task 3: Trigger preload from dashboard visible rows

**Files:**
- Modify: `E:\claude code test\src\components\Dashboard.tsx`

- [ ] Derive a small top-of-list symbol slice from `filteredRows`.
- [ ] On first render and whenever that slice changes, send `PRELOAD_HISTORY`.
- [ ] Limit preload to a small batch, for example 12 symbols.

### Task 4: Add backend preload handler

**Files:**
- Modify: `E:\claude code test\sinopac_bridge.py`

- [ ] Add a background task registry for history preload jobs.
- [ ] Handle websocket message `{ type: "preload_history" }`.
- [ ] Deduplicate symbols already warming or already cached.
- [ ] Run cache warm in executor so websocket handling stays responsive.

### Task 5: Persist fetched history into local cache

**Files:**
- Modify: `E:\claude code test\sinopac_bridge.py`

- [ ] Reuse the existing fallback history fetch path.
- [ ] Persist fetched bars into `data/daily_price_cache.json`.
- [ ] Ensure later `history_bars` reads use this cache first.

### Task 6: Verify end-to-end behavior

**Files:**
- Modify: `E:\claude code test\src\components\Dashboard.test.tsx` if needed

- [ ] Build the frontend with `npm run build`.
- [ ] Run Python syntax check on `sinopac_bridge.py`.
- [ ] Manually confirm preload message path and cache file creation or updates.

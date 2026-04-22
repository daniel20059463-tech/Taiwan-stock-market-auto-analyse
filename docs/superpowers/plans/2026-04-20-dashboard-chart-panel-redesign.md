# Dashboard Chart Panel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 Dashboard 首頁右側主圖表卡改成深色台股技術圖面板，支援 `日線 / 週K / 月K` 三種模式、成交量副圖與空狀態提示。

**Architecture:** 以既有 `Dashboard.tsx` 為中心，不新增後端協定。前端把既有 session 與 history 資料重新映射成 `daily / weekly / monthly` 三種展示模式，並將圖表 series 的顯示、MA 圖例與 overlay 提示集中在同一個圖表卡區塊內處理。

**Tech Stack:** React 18, TypeScript, Vite, Zustand, lightweight-charts, Vitest, Testing Library

---

### Task 1: 鎖定圖表模式與資料轉換函式

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Test: `src/components/Dashboard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("shows the three chart period buttons", () => {
  render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

  expect(screen.getByRole("button", { name: "日線" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "週K" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "月K" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Dashboard.test.tsx`
Expected: FAIL because the current UI still renders `即時` / `歷史` instead of `日線` / `週K` / `月K`

- [ ] **Step 3: Write minimal implementation**

```ts
type ChartMode = "daily" | "weekly" | "monthly";

type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

function startOfWeekKey(ts: number): string {
  const date = new Date(ts);
  const day = date.getDay();
  const offset = day === 0 ? -6 : 1 - day;
  date.setDate(date.getDate() + offset);
  date.setHours(0, 0, 0, 0);
  return date.toISOString().slice(0, 10);
}

function monthKey(ts: number): string {
  const date = new Date(ts);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function aggregateCandles(source: Candle[], mode: "weekly" | "monthly"): Candle[] {
  const buckets = new Map<string, Candle[]>();

  for (const candle of source) {
    const key = mode === "weekly" ? startOfWeekKey(candle.time) : monthKey(candle.time);
    const list = buckets.get(key) ?? [];
    list.push(candle);
    buckets.set(key, list);
  }

  return Array.from(buckets.values()).map((group) => ({
    time: group[0].time,
    open: group[0].open,
    high: Math.max(...group.map((item) => item.high)),
    low: Math.min(...group.map((item) => item.low)),
    close: group[group.length - 1].close,
    volume: group.reduce((sum, item) => sum + item.volume, 0),
  }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- Dashboard.test.tsx`
Expected: PASS for the period button assertion

- [ ] **Step 5: Commit**

```bash
git add src/components/Dashboard.tsx src/components/Dashboard.test.tsx
git commit -m "refactor: replace dashboard chart mode model"
```

### Task 2: 實作頂部工具列與 MA 圖例列

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Test: `src/components/Dashboard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("shows MA legend only for weekly and monthly modes", async () => {
  const user = userEvent.setup();
  render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

  expect(screen.queryByText("MA5")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "週K" }));
  expect(screen.getByText("MA5")).toBeInTheDocument();
  expect(screen.getByText("MA10")).toBeInTheDocument();
  expect(screen.getByText("MA20")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Dashboard.test.tsx`
Expected: FAIL because the current UI still renders toggle chips for MA and uses old labels

- [ ] **Step 3: Write minimal implementation**

```tsx
const periodLabel =
  chartMode === "daily" ? "日線" : chartMode === "weekly" ? "週K" : "月K";

<div style={{ height: "34px", background: "#101419", ... }}>
  <div>
    <span>{selectedRow?.symbol ?? "--"}</span>
    <span>{periodLabel}</span>
  </div>
  <div>
    {(["daily", "weekly", "monthly"] as ChartMode[]).map((mode) => (
      <button key={mode} ...>
        {mode === "daily" ? "日線" : mode === "weekly" ? "週K" : "月K"}
      </button>
    ))}
  </div>
</div>

{chartMode !== "daily" ? (
  <div style={{ height: "26px", ... }}>
    <span style={{ color: "#ffbd2e" }}>MA5</span>
    <span style={{ color: "#3aa0ff" }}>MA10</span>
    <span style={{ color: "#b088ff" }}>MA20</span>
  </div>
) : null}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- Dashboard.test.tsx`
Expected: PASS for the MA legend visibility rule

- [ ] **Step 5: Commit**

```bash
git add src/components/Dashboard.tsx src/components/Dashboard.test.tsx
git commit -m "feat: redesign dashboard chart toolbar and legends"
```

### Task 3: 接上日線 / 週K / 月K 的 series 顯示規則

**Files:**
- Modify: `src/components/Dashboard.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("shows daily empty-state copy when no intraday data exists", () => {
  useMarketStore.setState((state) => ({
    ...state,
    selectedSymbol: "1101",
    sessionCache: new Map(),
    snapshot: {
      ...snapshot,
      symbols: snapshot.symbols.map((item) =>
        item.symbol === "1101" ? { ...item, candles: [] } : item
      ),
    },
  }));

  render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);
  expect(screen.getByText("尚無當日資料")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Dashboard.test.tsx`
Expected: FAIL because the current chart area has no overlay copy for this condition

- [ ] **Step 3: Write minimal implementation**

```ts
const intradayCandles =
  sessionEntry?.candles?.length
    ? processCandles(sessionEntry.candles)
    : selectedRow?.candles?.length
      ? processCandles(selectedRow.candles)
      : [];

const historicalCandles = processCandles(historyEntry?.candles ?? []);

const chartCandles =
  chartMode === "daily"
    ? intradayCandles
    : chartMode === "weekly"
      ? aggregateCandles(historicalCandles, "weekly")
      : aggregateCandles(historicalCandles, "monthly");

const chartOverlayMessage =
  !selectedRow
    ? "選取股票後顯示圖表"
    : chartMode === "daily"
      ? (chartCandles.length ? null : "尚無當日資料")
      : (chartCandles.length ? null : "尚無K線資料");
```

- [ ] **Step 4: Expand the chart update logic**

```ts
const lineData = chartCandles.map((candle) => ({
  time: Math.floor(candle.time / 1000) as UTCTimestamp,
  value: candle.close,
}));

const candleData = chartCandles.map((candle) => ({
  time: Math.floor(candle.time / 1000) as UTCTimestamp,
  open: candle.open,
  high: candle.high,
  low: candle.low,
  close: candle.close,
}));

lineRef.current.applyOptions({ visible: chartMode === "daily" });
candleRef.current.applyOptions({ visible: chartMode !== "daily" });
lineRef.current.setData(chartMode === "daily" ? lineData : []);
candleRef.current.setData(chartMode !== "daily" ? candleData : []);
ma5Ref.current?.setData(chartMode === "daily" ? [] : smaLine(chartCandles, 5));
ma10Ref.current?.setData(chartMode === "daily" ? [] : smaLine(chartCandles, 10));
ma20Ref.current?.setData(chartMode === "daily" ? [] : smaLine(chartCandles, 20));
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- Dashboard.test.tsx`
Expected: PASS for the daily empty-state case

- [ ] **Step 6: Commit**

```bash
git add src/components/Dashboard.tsx src/components/Dashboard.test.tsx
git commit -m "feat: map dashboard chart periods to intraday and aggregated k-bars"
```

### Task 4: 套用深色圖表樣式、漸層與成交量比例

**Files:**
- Modify: `src/components/Dashboard.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("shows the chart empty-state overlay when no symbol is selected", () => {
  useMarketStore.setState((state) => ({ ...state, selectedSymbol: "" }));
  render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);
  expect(screen.getByText("選取股票後顯示圖表")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Dashboard.test.tsx`
Expected: FAIL because the current dashboard auto-picks a symbol and renders no overlay

- [ ] **Step 3: Write minimal implementation**

```tsx
lineRef.current = mainChart.addAreaSeries({
  lineColor: "#2f80ff",
  topColor: "rgba(47, 128, 255, 0.28)",
  bottomColor: "rgba(47, 128, 255, 0.02)",
  lineWidth: 2,
  priceLineVisible: true,
  crosshairMarkerVisible: false,
});

volumeRef.current = volumeChart.addHistogramSeries({
  priceFormat: { type: "volume" },
  priceLineVisible: false,
  lastValueVisible: false,
});

<div style={{ display: "grid", gridTemplateRows: "minmax(0,1fr) 72px", ... }}>
  <div style={{ position: "relative" }}>
    <div ref={mainHostRef} style={{ width: "100%", height: "100%" }} />
    {chartOverlayMessage ? (
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "#7f8b96" }}>
        {chartOverlayMessage}
      </div>
    ) : null}
  </div>
  <div ref={volumeHostRef} style={{ width: "100%", height: "72px" }} />
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- Dashboard.test.tsx`
Expected: PASS for the empty-state overlay assertion

- [ ] **Step 5: Commit**

```bash
git add src/components/Dashboard.tsx src/components/Dashboard.test.tsx
git commit -m "feat: restyle dashboard chart panel for dark market view"
```

### Task 5: 完成回歸驗證

**Files:**
- Modify: `src/components/Dashboard.test.tsx`

- [ ] **Step 1: Add final targeted assertions**

```tsx
it("shows monthly empty-state copy when historical k bars are missing", async () => {
  const user = userEvent.setup();
  useMarketStore.setState((state) => ({
    ...state,
    historyCache: new Map(),
  }));

  render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);
  await user.click(screen.getByRole("button", { name: "月K" }));
  expect(screen.getByText("尚無K線資料")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run targeted tests**

Run: `npm test -- Dashboard.test.tsx`
Expected: PASS

- [ ] **Step 3: Run typecheck**

Run: `npm run typecheck`
Expected: PASS

- [ ] **Step 4: Run production build**

Run: `npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/Dashboard.tsx src/components/Dashboard.test.tsx
git commit -m "test: verify dashboard chart panel redesign"
```

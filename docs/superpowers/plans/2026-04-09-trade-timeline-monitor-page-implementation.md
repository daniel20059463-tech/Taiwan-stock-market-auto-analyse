# 交易時間線監控頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一個獨立的桌面 App 交易監控頁，使用現有 `replayTrades / recentTrades` 顯示今天與最近 7 天的成交、平倉時間線與單筆詳情。

**Architecture:** 以前端 store 的既有資料為單一來源，新頁面只做派生資料整理與顯示，不新增後端事件流。透過一個小型 helper/selectors 負責合併、去重、篩選與格式化，頁面本身維持純 render 與互動狀態。

**Tech Stack:** React, TypeScript, Vite, Zustand, React Router, Vitest

---

## File Structure

### Create

- `E:\claude code test\src\pages\TradeMonitor.tsx`
- `E:\claude code test\src\pages\TradeMonitor.test.tsx`
- `E:\claude code test\src\pages\tradeMonitorModel.ts`

### Modify

- `E:\claude code test\src\App.tsx`
- `E:\claude code test\src\components\AppShell.tsx`
- `E:\claude code test\src\store.ts`

### Notes

- `tradeMonitorModel.ts` 專門放時間線資料整理邏輯，避免把資料清洗塞進頁面元件
- 不修改後端檔案

---

### Task 1: 建立時間線資料模型 helper

**Files:**
- Create: `E:\claude code test\src\pages\tradeMonitorModel.ts`
- Test: `E:\claude code test\src\pages\TradeMonitor.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, expect, it } from "vitest";
import { buildTradeMonitorRows } from "./tradeMonitorModel";

describe("buildTradeMonitorRows", () => {
  it("merges replayTrades first and deduplicates recentTrades duplicates", () => {
    const rows = buildTradeMonitorRows({
      replayTrades: [
        {
          symbol: "2330",
          action: "BUY",
          price: 100,
          shares: 1000,
          reason: "SIGNAL",
          netPnl: 0,
          grossPnl: 0,
          ts: 1_700_000_000_000,
        },
      ],
      recentTrades: [
        {
          symbol: "2330",
          action: "BUY",
          price: 100,
          shares: 1000,
          reason: "SIGNAL",
          netPnl: 0,
          grossPnl: 0,
          ts: 1_700_000_000_000,
        },
      ],
      instruments: [{ symbol: "2330", name: "台積電", sector: "24", sectorName: "半導體業" }],
      range: "today",
      filter: "all",
      query: "",
      nowTs: 1_700_000_100_000,
    });

    expect(rows).toHaveLength(1);
    expect(rows[0].symbolLabel).toBe("2330 台積電");
    expect(rows[0].action).toBe("BUY");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- FAIL because `tradeMonitorModel.ts` and exports do not exist yet

- [ ] **Step 3: Write minimal implementation**

```ts
import type { PaperTrade } from "../types/market";

type RangeFilter = "today" | "sevenDays";
type ActionFilter = "all" | "entries" | "exits";

type InstrumentLike = {
  symbol: string;
  name?: string;
  sector?: string;
  sectorName?: string;
};

type BuildParams = {
  replayTrades: PaperTrade[];
  recentTrades: PaperTrade[];
  instruments: InstrumentLike[];
  range: RangeFilter;
  filter: ActionFilter;
  query: string;
  nowTs: number;
};

export type TradeMonitorRow = PaperTrade & {
  symbolLabel: string;
  actionLabel: string;
  direction: "entry" | "exit";
  instrumentName: string;
};

function dedupeTrades(trades: PaperTrade[]): PaperTrade[] {
  const map = new Map<string, PaperTrade>();
  for (const trade of trades) {
    const key = [
      trade.symbol,
      trade.action,
      trade.price,
      trade.shares,
      trade.reason,
      trade.ts,
      trade.netPnl,
      trade.grossPnl,
    ].join("|");
    map.set(key, trade);
  }
  return Array.from(map.values());
}

function isSameTaipeiDay(left: Date, right: Date): boolean {
  return (
    left.getUTCFullYear() === right.getUTCFullYear() &&
    left.getUTCMonth() === right.getUTCMonth() &&
    left.getUTCDate() === right.getUTCDate()
  );
}

function toTaipeiDate(ts: number): Date {
  return new Date(new Date(ts).toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
}

function actionLabel(action: PaperTrade["action"]): string {
  switch (action) {
    case "BUY":
      return "買進";
    case "SELL":
      return "賣出";
    case "SHORT":
      return "放空";
    case "COVER":
      return "回補";
    default:
      return action;
  }
}

export function buildTradeMonitorRows(params: BuildParams): TradeMonitorRow[] {
  const merged = dedupeTrades([...params.replayTrades, ...params.recentTrades]);
  const query = params.query.trim().toLowerCase();
  const nowDate = toTaipeiDate(params.nowTs);
  const earliest = new Date(nowDate);
  earliest.setDate(earliest.getDate() - 6);

  return merged
    .filter((trade) => {
      const tradeDate = toTaipeiDate(trade.ts);
      if (params.range === "today" && !isSameTaipeiDay(tradeDate, nowDate)) {
        return false;
      }
      if (params.range === "sevenDays" && tradeDate < earliest) {
        return false;
      }
      if (params.filter === "entries" && !["BUY", "SHORT"].includes(trade.action)) {
        return false;
      }
      if (params.filter === "exits" && !["SELL", "COVER"].includes(trade.action)) {
        return false;
      }
      const instrument = params.instruments.find((item) => item.symbol === trade.symbol);
      const name = instrument?.name ?? "未知標的";
      if (!query) {
        return true;
      }
      return trade.symbol.toLowerCase().includes(query) || name.toLowerCase().includes(query);
    })
    .sort((left, right) => right.ts - left.ts)
    .map((trade) => {
      const instrument = params.instruments.find((item) => item.symbol === trade.symbol);
      const name = instrument?.name ?? "未知標的";
      return {
        ...trade,
        symbolLabel: `${trade.symbol} ${name}`,
        instrumentName: name,
        actionLabel: actionLabel(trade.action),
        direction: trade.action === "BUY" || trade.action === "SHORT" ? "entry" : "exit",
      };
    });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- PASS for `buildTradeMonitorRows`

- [ ] **Step 5: Commit**

```bash
git add src/pages/tradeMonitorModel.ts src/pages/TradeMonitor.test.tsx
git commit -m "feat: add trade monitor timeline model"
```

---

### Task 2: 建立交易監控頁面

**Files:**
- Create: `E:\claude code test\src\pages\TradeMonitor.tsx`
- Modify: `E:\claude code test\src\store.ts`
- Test: `E:\claude code test\src\pages\TradeMonitor.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TradeMonitor } from "./TradeMonitor";
import { useMarketStore } from "../store";

test("renders timeline rows from replay trades and shows detail panel", () => {
  useMarketStore.setState({
    replayTrades: [
      {
        symbol: "2330",
        action: "BUY",
        price: 100,
        shares: 1000,
        reason: "SIGNAL",
        netPnl: 0,
        grossPnl: 0,
        ts: Date.now(),
        decisionReport: {
          reportId: "r1",
          symbol: "2330",
          ts: Date.now(),
          decisionType: "buy",
          triggerType: "mixed",
          confidence: 80,
          finalReason: "signal_confirmed",
          summary: "買進摘要",
          supportingFactors: [],
          opposingFactors: [],
          riskFlags: [],
          sourceEvents: [],
          orderResult: { status: "executed" },
          bullCase: "多方觀點",
          bearCase: "空方觀點",
          riskCase: "風控觀點",
          bullArgument: "多方論點",
          bearArgument: "空方論點",
          refereeVerdict: "裁決",
          debateWinner: "bull",
        },
      },
    ],
    portfolio: null,
  });

  render(
    <MemoryRouter>
      <TradeMonitor />
    </MemoryRouter>,
  );

  expect(screen.getByText("交易監控")).toBeInTheDocument();
  expect(screen.getByText("2330 台積電")).toBeInTheDocument();
  expect(screen.getByText("多方論點")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- FAIL because `TradeMonitor` page does not exist yet

- [ ] **Step 3: Write minimal implementation**

```tsx
import { useMemo, useState } from "react";
import { useMarketStore } from "../store";
import { DEFAULT_TW_STOCKS } from "../data/twStocks";
import { buildTradeMonitorRows } from "./tradeMonitorModel";

type RangeFilter = "today" | "sevenDays";
type ActionFilter = "all" | "entries" | "exits";

export function TradeMonitor() {
  const replayTrades = useMarketStore((state) => state.replayTrades);
  const portfolio = useMarketStore((state) => state.portfolio);
  const [range, setRange] = useState<RangeFilter>("today");
  const [filter, setFilter] = useState<ActionFilter>("all");
  const [query, setQuery] = useState("");

  const rows = useMemo(
    () =>
      buildTradeMonitorRows({
        replayTrades,
        recentTrades: portfolio?.recentTrades ?? [],
        instruments: DEFAULT_TW_STOCKS,
        range,
        filter,
        query,
        nowTs: Date.now(),
      }),
    [filter, portfolio?.recentTrades, query, range, replayTrades],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = rows.find((row) => `${row.symbol}-${row.action}-${row.ts}` === selectedId) ?? rows[0] ?? null;

  return (
    <section style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(320px, 1fr)", gap: 16, padding: 20 }}>
      <div style={{ minWidth: 0 }}>
        <h1>交易監控</h1>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <button onClick={() => setRange("today")}>今天</button>
          <button onClick={() => setRange("sevenDays")}>最近 7 天</button>
          <button onClick={() => setFilter("all")}>全部</button>
          <button onClick={() => setFilter("entries")}>只看成交</button>
          <button onClick={() => setFilter("exits")}>只看平倉</button>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋代碼或名稱" />
        </div>
        <div style={{ maxHeight: "calc(100vh - 220px)", overflowY: "auto", border: "1px solid #242428" }}>
          {rows.length === 0 ? (
            <div style={{ padding: 16 }}>此範圍內沒有可顯示的成交或平倉事件。</div>
          ) : (
            rows.map((row) => {
              const key = `${row.symbol}-${row.action}-${row.ts}`;
              return (
                <button
                  key={key}
                  onClick={() => setSelectedId(key)}
                  style={{ display: "block", width: "100%", textAlign: "left", padding: 16, background: "transparent", color: "inherit", border: 0, borderBottom: "1px solid #242428" }}
                >
                  <div>{row.symbolLabel}</div>
                  <div>{row.actionLabel}</div>
                  <div>{row.reason}</div>
                </button>
              );
            })
          )}
        </div>
      </div>
      <aside style={{ border: "1px solid #242428", padding: 16 }}>
        {selected ? (
          <>
            <h2>{selected.symbolLabel}</h2>
            <div>{selected.actionLabel}</div>
            <div>{selected.reason}</div>
            <div>{selected.decisionReport?.finalReason ?? "無決策報告"}</div>
            <div>{selected.decisionReport?.bullArgument ?? "無決策報告"}</div>
            <div>{selected.decisionReport?.bearArgument ?? "無決策報告"}</div>
            <div>{selected.decisionReport?.refereeVerdict ?? "無決策報告"}</div>
          </>
        ) : (
          <div>請先從左側選擇一筆交易。</div>
        )}
      </aside>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- PASS for page render and detail panel

- [ ] **Step 5: Commit**

```bash
git add src/pages/TradeMonitor.tsx src/pages/TradeMonitor.test.tsx src/store.ts
git commit -m "feat: add trade monitor timeline page"
```

---

### Task 3: 接上路由與導航

**Files:**
- Modify: `E:\claude code test\src\App.tsx`
- Modify: `E:\claude code test\src\components\AppShell.tsx`
- Test: `E:\claude code test\src\pages\TradeMonitor.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "../components/AppShell";

test("shows trade monitor nav item", () => {
  render(
    <MemoryRouter>
      <AppShell>
        <div>content</div>
      </AppShell>
    </MemoryRouter>,
  );

  expect(screen.getByText("交易監控")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- FAIL because navigation item and route do not exist yet

- [ ] **Step 3: Write minimal implementation**

```tsx
// in src/components/AppShell.tsx
const NAV_ITEMS = [
  { path: "/", label: "即時盤面" },
  { path: "/monitor", label: "交易監控" },
  { path: "/strategy", label: "策略作戰台" },
  { path: "/replay", label: "交易回放" },
  { path: "/performance", label: "績效分析" },
  { path: "/config", label: "策略設定" },
] as const;
```

```tsx
// in src/App.tsx
import { TradeMonitor } from "./pages/TradeMonitor";

<Route
  path="/monitor"
  element={
    <ErrorBoundary label="交易監控">
      <TradeMonitor />
    </ErrorBoundary>
  }
/>
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- PASS for nav item and route wiring

- [ ] **Step 5: Commit**

```bash
git add src/App.tsx src/components/AppShell.tsx src/pages/TradeMonitor.test.tsx
git commit -m "feat: wire trade monitor route into app shell"
```

---

### Task 4: 補完整篩選、空狀態與缺失決策報告處理

**Files:**
- Modify: `E:\claude code test\src\pages\TradeMonitor.tsx`
- Modify: `E:\claude code test\src\pages\tradeMonitorModel.ts`
- Test: `E:\claude code test\src\pages\TradeMonitor.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { TradeMonitor } from "./TradeMonitor";
import { useMarketStore } from "../store";

test("filters exits only and shows fallback when decision report is missing", async () => {
  useMarketStore.setState({
    replayTrades: [
      {
        symbol: "2330",
        action: "BUY",
        price: 100,
        shares: 1000,
        reason: "SIGNAL",
        netPnl: 0,
        grossPnl: 0,
        ts: Date.now(),
      },
      {
        symbol: "2454",
        action: "SELL",
        price: 200,
        shares: 1000,
        reason: "TAKE_PROFIT",
        netPnl: 5000,
        grossPnl: 5200,
        ts: Date.now() - 1000,
      },
    ],
    portfolio: null,
  });

  render(
    <MemoryRouter>
      <TradeMonitor />
    </MemoryRouter>,
  );

  await userEvent.click(screen.getByText("只看平倉"));

  expect(screen.queryByText("買進")).not.toBeInTheDocument();
  expect(screen.getByText("賣出")).toBeInTheDocument();
  expect(screen.getByText("無決策報告")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- FAIL because filtering/fallback handling is incomplete

- [ ] **Step 3: Write minimal implementation**

```tsx
// In TradeMonitor.tsx detail panel
<section>
  <h3>最終理由</h3>
  <div>{selected.decisionReport?.finalReason ?? "無決策報告"}</div>
</section>
<section>
  <h3>支持因素</h3>
  {selected.decisionReport?.supportingFactors?.length ? (
    selected.decisionReport.supportingFactors.map((factor) => <div key={`${factor.label}-${factor.detail}`}>{factor.detail}</div>)
  ) : (
    <div>無決策報告</div>
  )}
</section>
```

```ts
// In tradeMonitorModel.ts
if (params.filter === "entries" && !["BUY", "SHORT"].includes(trade.action)) return false;
if (params.filter === "exits" && !["SELL", "COVER"].includes(trade.action)) return false;
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- PASS for filters and fallback detail behavior

- [ ] **Step 5: Commit**

```bash
git add src/pages/TradeMonitor.tsx src/pages/tradeMonitorModel.ts src/pages/TradeMonitor.test.tsx
git commit -m "feat: finalize trade monitor timeline filters and details"
```

---

### Task 5: 完整驗證

**Files:**
- Verify only

- [ ] **Step 1: Run targeted front-end tests**

Run:

```bash
npm.cmd test -- src/pages/TradeMonitor.test.tsx
```

Expected:

- PASS

- [ ] **Step 2: Run full front-end test suite**

Run:

```bash
npm.cmd test
```

Expected:

- PASS all existing tests plus new monitor page tests

- [ ] **Step 3: Run production build**

Run:

```bash
npm.cmd run build
```

Expected:

- Exit 0
- Vite build output generated successfully

- [ ] **Step 4: Sanity-check route integration**

Run:

```bash
npm.cmd run desktop:package
```

Expected:

- Successful packaging
- No route/build regression from the new page

- [ ] **Step 5: Commit**

```bash
git add src/App.tsx src/components/AppShell.tsx src/pages/TradeMonitor.tsx src/pages/TradeMonitor.test.tsx src/pages/tradeMonitorModel.ts src/store.ts
git commit -m "feat: add trade monitor desktop page"
```

---

## Self-Review

### Spec coverage

- 新增獨立頁面：有
- `今天 / 最近 7 天`：有
- `全部 / 只看成交 / 只看平倉`：有
- 搜尋 symbol/name：有
- 左側時間線、右側詳情：有
- 直接吃 `replayTrades / recentTrades`：有
- 不新增後端事件流：有
- 空狀態與缺少 decisionReport 降級：有

### Placeholder scan

- 無 `TODO / TBD / implement later`
- 每個 task 都有具體檔案、測試、命令與預期結果

### Type consistency

- `TradeMonitor.tsx` 與 `tradeMonitorModel.ts` 共用 `RangeFilter / ActionFilter`
- 事件類型統一使用 `BUY / SELL / SHORT / COVER`
- 路由統一使用 `/monitor`

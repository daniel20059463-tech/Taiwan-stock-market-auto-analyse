# Homepage Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the homepage into the approved A-market-first layout with a shorter, wider information hierarchy centered on market opportunities, sector heat, and a detailed single-symbol panel.

**Architecture:** Keep the existing worker/store/chart data flow intact and reshape only the homepage composition inside `Dashboard` and its shell framing. Use store-derived ranking for the market cards, a lightweight sector aggregation for the sector heat ranking, and a deterministic default-symbol selection rule that prefers open positions and recent trades before market rank.

**Tech Stack:** React, TypeScript, Vite, Zustand, lightweight-charts, @tanstack/react-virtual, Vitest, Testing Library

---

## File Map

- Modify: `src/components/Dashboard.tsx`
  - Rebuild homepage into three layers: market overview strip, market-first main zone, detail zone.
  - Implement sector ranking aggregation and default-symbol prioritization.
- Modify: `src/components/AppShell.tsx`
  - Keep shell consistent with the softer homepage hierarchy.
- Modify: `src/components/Dashboard.test.tsx`
  - Add regression coverage for the new homepage sections and default-symbol behavior.
- Verify: `src/index.css`
  - Keep typography and spacing consistent with the new shorter layout.

### Task 1: Lock the approved homepage structure with tests

**Files:**
- Modify: `src/components/Dashboard.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it("renders the market-first homepage sections", () => {
  render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

  expect(screen.getByText("全市場機會")).toBeInTheDocument();
  expect(screen.getByText("類股熱度排行")).toBeInTheDocument();
  expect(screen.getByText("單一標的盤面")).toBeInTheDocument();
  expect(screen.getByText("標的摘要與帳本")).toBeInTheDocument();
});

it("prefers the held symbol for the detail panel default selection", () => {
  useMarketStore.setState((state) => ({
    ...state,
    selectedSymbol: "",
    portfolio: {
      type: "PAPER_PORTFOLIO",
      positions: [
        {
          symbol: "1102",
          entryPrice: 35.25,
          currentPrice: 35.25,
          shares: 1000,
          pnl: 0,
          pct: 0,
          entryTs: Date.now(),
        },
      ],
      recentTrades: [],
      realizedPnl: 0,
      unrealizedPnl: 0,
      totalPnl: 0,
      tradeCount: 0,
      winRate: 0,
      marketChangePct: 0,
    },
  }));

  render(<Dashboard symbols={instruments.map((item) => item.symbol)} instruments={instruments} />);

  expect(screen.getByText("1102 亞泥")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- Dashboard.test.tsx`
Expected: FAIL because the current homepage still renders the older section set and does not prioritize the held symbol.

- [ ] **Step 3: Write minimal implementation**

```tsx
// Dashboard.tsx
// Add a market-first layout with explicit section titles:
// - 全市場機會
// - 類股熱度排行
// - 單一標的盤面
// - 標的摘要與帳本
// Add getPreferredSymbol() that checks positions, then recentTrades, then ranked market rows.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- Dashboard.test.tsx`
Expected: PASS

### Task 2: Rebuild Dashboard into the approved shorter A-layout

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Verify: `src/index.css`

- [ ] **Step 1: Implement the new layout skeleton**

```tsx
return (
  <div>
    <section>{/* 市場總覽條 */}</section>
    <section>{/* 左: 全市場機會 / 右: 類股熱度排行 */}</section>
    <section>{/* 左: 單一標的盤面 / 右: 標的摘要與帳本 */}</section>
  </div>
);
```

- [ ] **Step 2: Add sector ranking aggregation from snapshot rows**

```tsx
const sectorLeaders = useMemo(() => {
  const groups = new Map<string, { sector: string; count: number; avgChangePct: number; leader: string }>();
  // group rows, compute average change, keep representative symbol
  return Array.from(groups.values())
    .sort((a, b) => Math.abs(b.avgChangePct) - Math.abs(a.avgChangePct))
    .slice(0, 6);
}, [rows]);
```

- [ ] **Step 3: Add preferred-symbol resolution**

```tsx
const preferredSymbol = useMemo(() => {
  const held = portfolio?.positions?.[0]?.symbol;
  if (held) return held;
  const recent = portfolio?.recentTrades?.slice(-1)[0]?.symbol;
  if (recent) return recent;
  return filteredRows[0]?.symbol ?? "";
}, [portfolio, filteredRows]);
```

- [ ] **Step 4: Keep the detailed panel chart logic intact while moving it lower on the page**

```tsx
const detailSymbol = selectedSymbol || preferredSymbol;
// Reuse history/session/tick chart logic with the new composition.
```

- [ ] **Step 5: Run the homepage tests**

Run: `npm test -- Dashboard.test.tsx`
Expected: PASS

### Task 3: Polish homepage readability and shell consistency

**Files:**
- Modify: `src/components/AppShell.tsx`
- Modify: `src/components/Dashboard.tsx`

- [ ] **Step 1: Soften shell emphasis so homepage remains the focal point**

```tsx
// AppShell.tsx
// Keep the navigation, connection card, and pnl card, but avoid oversized decorative emphasis.
```

- [ ] **Step 2: Normalize card titles, helper copy, and button styles across the homepage**

```tsx
// Dashboard.tsx
// Use one title style, one helper-text style, one rounded card style.
```

- [ ] **Step 3: Re-run the full frontend suite**

Run: `npm test`
Expected: PASS

- [ ] **Step 4: Run the production build**

Run: `npm run build`
Expected: PASS

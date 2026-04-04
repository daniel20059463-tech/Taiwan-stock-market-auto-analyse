# Multi-Analyst Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將多角色分析層接入現有台股模擬交易系統，讓盤中決策由 News / Sentiment / Technical / Risk 四種觀點共同組成結構化 `DecisionReport`，並在回放頁中以全中文方式呈現。

**Architecture:** 新增純 Python 的 `multi_analyst` 模組，定義 `AnalystView`、`DecisionBundle` 與各 analyst / composer；由 `auto_trader.py` 呼叫該層組裝買進、賣出與略過決策，透過既有 websocket 與 store 契約送往前端。前端沿用現有 replay / performance data flow，只擴充型別與顯示區塊。

**Tech Stack:** Python dataclasses / pytest、React + TypeScript + Zustand + Vitest

---

### Task 1: 建立多角色分析核心型別與純函式分析器

**Files:**
- Create: `E:\claude code test\multi_analyst.py`
- Test: `E:\claude code test\test_multi_analyst.py`

- [ ] **Step 1: Write the failing test**

```python
from multi_analyst import (
    AnalystContext,
    DecisionComposer,
    NewsAnalyst,
    RiskAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)


def test_multi_analyst_composer_builds_bull_bear_and_risk_cases():
    context = AnalystContext(
        symbol="2330",
        ts=1_775_600_000_000,
        price=101.0,
        change_pct=2.4,
        previous_close=98.6,
        open_price=99.2,
        high=101.8,
        low=98.9,
        volume=45000,
        average_volume=20000,
        ma5=100.2,
        ma20=98.8,
        near_day_high=False,
        volume_confirmed=True,
        sentiment_score=0.36,
        sentiment_blocked=False,
        market_change_pct=0.7,
        weekly_halt=False,
        risk_allowed=True,
        risk_reason="OK",
        article_id="2330:news-1",
        analyzer_keywords=("擴產", "AI"),
    )

    views = [
        NewsAnalyst().evaluate(context),
        SentimentAnalyst().evaluate(context),
        TechnicalAnalyst().evaluate(context),
        RiskAnalyst().evaluate(context),
    ]
    bundle = DecisionComposer().compose(context, views, decision_type="buy")

    assert bundle.final_decision == "buy"
    assert bundle.confidence > 0
    assert "多方觀點" in bundle.bull_case
    assert "空方觀點" in bundle.bear_case
    assert "風控觀點" in bundle.risk_case
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_multi_analyst.py`
Expected: FAIL with `ModuleNotFoundError` or missing symbol failures because `multi_analyst.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class AnalystFactor:
    kind: str
    label: str
    detail: str


@dataclass(slots=True)
class AnalystView:
    agent_name: str
    stance: str
    score: int
    summary: str
    supporting_factors: list[AnalystFactor] = field(default_factory=list)
    opposing_factors: list[AnalystFactor] = field(default_factory=list)
    blocking: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class AnalystContext:
    symbol: str
    ts: int
    price: float
    change_pct: float
    previous_close: float
    open_price: float
    high: float
    low: float
    volume: int
    average_volume: int
    ma5: float | None
    ma20: float | None
    near_day_high: bool
    volume_confirmed: bool
    sentiment_score: float | None
    sentiment_blocked: bool
    market_change_pct: float
    weekly_halt: bool
    risk_allowed: bool
    risk_reason: str
    article_id: str | None = None
    analyzer_keywords: tuple[str, ...] = ()


@dataclass(slots=True)
class DecisionBundle:
    symbol: str
    ts: int
    views: list[AnalystView]
    bull_case: str
    bear_case: str
    risk_case: str
    final_decision: str
    confidence: int


class NewsAnalyst:
    def evaluate(self, context: AnalystContext) -> AnalystView:
        if not context.article_id:
            return AnalystView("新聞觀點", "neutral", 40, "目前沒有有效新聞事件。")
        stance = "bullish" if context.change_pct >= 0 else "bearish"
        return AnalystView(
            "新聞觀點",
            stance,
            min(90, 45 + int(abs(context.change_pct) * 10)),
            "新聞事件與盤中走勢方向一致。",
            supporting_factors=[AnalystFactor("support", "事件來源", f"新聞編號 {context.article_id}")],
        )


class SentimentAnalyst:
    def evaluate(self, context: AnalystContext) -> AnalystView:
        score = context.sentiment_score or 0.0
        stance = "blocking" if context.sentiment_blocked else ("bullish" if score >= 0 else "bearish")
        return AnalystView(
            "輿情觀點",
            stance,
            max(5, min(95, 50 + int(score * 30))),
            "輿情分數已納入買進前檢查。",
            supporting_factors=[AnalystFactor("support", "情緒分數", f"{score:.3f}")],
            blocking=context.sentiment_blocked,
        )


class TechnicalAnalyst:
    def evaluate(self, context: AnalystContext) -> AnalystView:
        score = 45
        if context.ma5 is not None and context.price >= context.ma5:
            score += 15
        if context.ma20 is not None and context.price >= context.ma20:
            score += 15
        if context.volume_confirmed:
            score += 10
        if context.near_day_high:
            score -= 10
        return AnalystView(
            "技術面觀點",
            "bullish" if score >= 55 else "neutral",
            max(5, min(95, score)),
            "依均線、量能與日內位置判讀技術強弱。",
        )


class RiskAnalyst:
    def evaluate(self, context: AnalystContext) -> AnalystView:
        return AnalystView(
            "風控觀點",
            "bullish" if context.risk_allowed and not context.weekly_halt else "blocking",
            80 if context.risk_allowed and not context.weekly_halt else 10,
            "依持倉、風控與市場狀態判斷是否放行。",
            opposing_factors=[] if context.risk_allowed else [AnalystFactor("oppose", "風控限制", context.risk_reason)],
            blocking=(not context.risk_allowed) or context.weekly_halt,
        )


class DecisionComposer:
    def compose(self, context: AnalystContext, views: list[AnalystView], *, decision_type: str) -> DecisionBundle:
        confidence = max(5, min(95, round(sum(view.score for view in views) / max(1, len(views)))))
        return DecisionBundle(
            symbol=context.symbol,
            ts=context.ts,
            views=views,
            bull_case="多方觀點：" + "；".join(view.summary for view in views if view.stance == "bullish"),
            bear_case="空方觀點：" + "；".join(view.summary for view in views if view.stance in {"bearish", "blocking"}),
            risk_case="風控觀點：" + "；".join(view.summary for view in views if view.agent_name == "風控觀點"),
            final_decision=decision_type,
            confidence=confidence,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_multi_analyst.py`
Expected: PASS with `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add test_multi_analyst.py multi_analyst.py
git commit -m "feat: add multi-analyst decision bundle core"
```

### Task 2: 將多角色分析層接入 AutoTrader 的買進、賣出與略過決策

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Test: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: Write the failing test**

```python
import types

import pytest

from auto_trader import AutoTrader


@pytest.mark.asyncio
async def test_auto_trader_uses_multi_analyst_bundle_for_buy_and_skip_reports():
    trader = AutoTrader(telegram_token="", chat_id="")

    async def _noop(*args, **kwargs):
        return None

    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)
    trader._is_near_day_high = types.MethodType(lambda self, symbol, price, payload: False, trader)
    trader._calc_atr = types.MethodType(lambda self, symbol: 1.2, trader)

    await trader._evaluate_buy(
        "2330",
        101.0,
        2.1,
        1_775_500_000_000,
        {"open": 100.0, "high": 102.0, "low": 99.5, "previousClose": 98.9, "volume": 50000},
    )

    snapshot = trader.get_portfolio_snapshot()
    report = snapshot["recentTrades"][0]["decisionReport"]

    assert report["summary"]
    assert report["bullCase"]
    assert report["bearCase"]
    assert report["riskCase"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py`
Expected: FAIL because `DecisionReport` payloads do not yet include multi-analyst bundle fields such as `bullCase`, `bearCase`, `riskCase`.

- [ ] **Step 3: Write minimal implementation**

```python
from multi_analyst import (
    AnalystContext,
    DecisionComposer,
    NewsAnalyst,
    RiskAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)


def _build_analyst_context(...):
    return AnalystContext(...)


def _collect_views(...):
    return [
        NewsAnalyst().evaluate(context),
        SentimentAnalyst().evaluate(context),
        TechnicalAnalyst().evaluate(context),
        RiskAnalyst().evaluate(context),
    ]


def _compose_bundle(...):
    return DecisionComposer().compose(context, views, decision_type=decision_type)


def _decision_report_from_bundle(bundle, ...):
    return {
        "bullCase": bundle.bull_case,
        "bearCase": bundle.bear_case,
        "riskCase": bundle.risk_case,
        ...
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py`
Expected: PASS with buy / sell / skip decision report tests all green.

- [ ] **Step 5: Commit**

```bash
git add auto_trader.py test_auto_trader_decision_reports.py
git commit -m "feat: wire multi-analyst views into auto trader decisions"
```

### Task 3: 擴充前端型別與 replay store 契約，保留 analyst bundle 中文欄位

**Files:**
- Modify: `E:\claude code test\src\types\market.ts`
- Modify: `E:\claude code test\src\store.ts`
- Test: `E:\claude code test\src\pages\TradeReplayDecisionReport.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("renders analyst bundle fields on replay page", () => {
  render(<TradeReplay />);

  expect(screen.getByText("多方觀點")).toBeInTheDocument();
  expect(screen.getByText("空方觀點")).toBeInTheDocument();
  expect(screen.getByText("風控觀點")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/pages/TradeReplayDecisionReport.test.tsx`
Expected: FAIL because the replay page does not yet render `bullCase` / `bearCase` / `riskCase`.

- [ ] **Step 3: Write minimal implementation**

```ts
export interface DecisionReport {
  ...
  bullCase?: string;
  bearCase?: string;
  riskCase?: string;
}

export function useReplayDecisions(): DecisionReport[] {
  return useMarketStore((state) => state.replayDecisions);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/pages/TradeReplayDecisionReport.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/types/market.ts src/store.ts src/pages/TradeReplayDecisionReport.test.tsx
git commit -m "feat: extend replay contract for analyst bundle fields"
```

### Task 4: 用全中文方式在交易回放頁顯示多角色分析結果

**Files:**
- Modify: `E:\claude code test\src\pages\TradeReplay.tsx`
- Test: `E:\claude code test\src\pages\TradeReplayDecisionReport.test.tsx`
- Test: `E:\claude code test\src\pages\PageCopy.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("shows analyst sections in Chinese on the replay page", () => {
  render(<TradeReplay />);

  expect(screen.getByText("決策摘要")).toBeInTheDocument();
  expect(screen.getByText("支持理由")).toBeInTheDocument();
  expect(screen.getByText("反對理由")).toBeInTheDocument();
  expect(screen.getByText("多方觀點")).toBeInTheDocument();
  expect(screen.getByText("空方觀點")).toBeInTheDocument();
  expect(screen.getByText("風控觀點")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/pages/TradeReplayDecisionReport.test.tsx src/pages/PageCopy.test.tsx`
Expected: FAIL because the replay UI does not yet render those Chinese sections.

- [ ] **Step 3: Write minimal implementation**

```tsx
<section>
  <div>決策摘要</div>
  <div>{report.summary}</div>
</section>
<section>
  <div>支持理由</div>
  ...
</section>
<section>
  <div>反對理由</div>
  ...
</section>
<section>
  <div>多方觀點</div>
  <div>{report.bullCase ?? "暫無多方結論"}</div>
</section>
<section>
  <div>空方觀點</div>
  <div>{report.bearCase ?? "暫無空方結論"}</div>
</section>
<section>
  <div>風控觀點</div>
  <div>{report.riskCase ?? "暫無風控結論"}</div>
</section>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/pages/TradeReplayDecisionReport.test.tsx src/pages/PageCopy.test.tsx`
Expected: PASS with all replay copy tests green.

- [ ] **Step 5: Commit**

```bash
git add src/pages/TradeReplay.tsx src/pages/TradeReplayDecisionReport.test.tsx src/pages/PageCopy.test.tsx
git commit -m "feat: show multi-analyst decision evidence on replay page"
```

### Task 5: Debug and verify the full system end-to-end

**Files:**
- Verify only: `E:\claude code test\auto_trader.py`
- Verify only: `E:\claude code test\multi_analyst.py`
- Verify only: `E:\claude code test\src\pages\TradeReplay.tsx`
- Verify only: `E:\claude code test\src\types\market.ts`
- Verify only: `E:\claude code test\src\store.ts`

- [ ] **Step 1: Run backend test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS for all Python tests, no regressions in analyzer / notifier / bridge / main / auto trader.

- [ ] **Step 2: Run frontend test suite**

Run: `npm test`
Expected: PASS for all Vitest suites.

- [ ] **Step 3: Run Python syntax verification**

Run: `.\.venv\Scripts\python.exe -m py_compile auto_trader.py multi_analyst.py run.py sinopac_bridge.py notifier.py analyzer.py main.py desktop_backend.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Run production frontend build**

Run: `npm run build`
Expected: PASS with Vite production bundle generated.

- [ ] **Step 5: If any verification fails, fix the regression and rerun until green**

```bash
git add .
git commit -m "fix: resolve multi-analyst integration regressions"
```

# Short Selling Minimal Intrusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-pass Taiwan intraday short-entry and cover support to the existing paper-trading engine without refactoring the multi-analyst or portfolio architecture.

**Architecture:** Keep long and short positions in the same `self._positions` dictionary and distinguish direction with a new `PaperPosition.side` field. Implement four new short-specific methods in `auto_trader.py`, reuse existing decision-report and replay plumbing, and extend tests first so both long and short behavior are locked down before code changes.

**Tech Stack:** Python 3.11, pytest, asyncio, existing `AutoTrader` / `RiskManager` / `DecisionReport` stack

---

## File map

- Modify: `E:\claude code test\auto_trader.py`
  - Add `PaperPosition.side`
  - Route `on_tick()` through long/short branches
  - Implement `_evaluate_short`, `_paper_short`, `_check_short_exit`, `_paper_cover`
  - Extend EOD flattening and portfolio snapshots
- Modify: `E:\claude code test\multi_analyst.py`
  - Improve wording for `decision_type="short"` and `decision_type="cover"`
- Modify: `E:\claude code test\test_auto_trader_decision_reports.py`
  - Extend replay/decision-report tests to cover short and cover payloads
- Create: `E:\claude code test\test_auto_trader_short_flow.py`
  - Focused tests for short entry, short skip, stop-loss cover, target cover, EOD cover

## Task 1: Lock short-selling behavior with failing tests

**Files:**
- Create: `E:\claude code test\test_auto_trader_short_flow.py`
- Modify: `E:\claude code test\test_auto_trader_decision_reports.py`
- Test: `E:\claude code test\test_auto_trader_short_flow.py`

- [ ] **Step 1: Write the failing short-flow tests**

```python
@pytest.mark.asyncio
async def test_short_entry_requires_negative_sentiment_and_volume_confirmation() -> None:
    trader = AutoTrader(
        telegram_token="",
        chat_id="",
        risk_manager=_FakeRiskManager(),
        sentiment_filter=_FakeSentimentFilter(score=-0.55, blocked=False),
    )
    trader._send = types.MethodType(_noop, trader)
    trader._persist_trade = types.MethodType(_noop, trader)
    trader._is_volume_confirmed = types.MethodType(lambda self, symbol: True, trader)

    await trader._evaluate_short(
        "2454",
        1288.0,
        -2.1,
        1_775_500_700_000,
        {
            "high": 1312.0,
            "low": 1280.0,
            "open": 1308.0,
            "previousClose": 1315.0,
            "volume": 80_000,
        },
    )

    assert "2454" in trader._positions
    assert trader._positions["2454"].side == "short"
    assert trader.get_portfolio_snapshot()["recentTrades"][-1]["action"] == "SHORT"
```

```python
@pytest.mark.asyncio
async def test_short_stop_loss_covers_when_price_rebounds() -> None:
    ...
    await trader._evaluate_short(...)
    await trader._check_short_exit("2454", rebound_price, ts_ms + 60_000)
    snapshot = trader.get_portfolio_snapshot()
    assert snapshot["recentTrades"][-1]["action"] == "COVER"
    assert snapshot["recentTrades"][-1]["reason"] == "STOP_LOSS"
```

```python
@pytest.mark.asyncio
async def test_short_take_profit_covers_when_price_drops_to_target() -> None:
    ...
```

```python
@pytest.mark.asyncio
async def test_short_position_is_flattened_at_eod() -> None:
    ...
    await trader._close_all_eod(ts_ms)
    snapshot = trader.get_portfolio_snapshot()
    assert snapshot["recentTrades"][-1]["action"] == "COVER"
    assert snapshot["recentTrades"][-1]["reason"] == "EOD"
```

```python
@pytest.mark.asyncio
async def test_short_signal_is_skipped_when_sentiment_not_negative_enough() -> None:
    ...
    await trader._evaluate_short(...)
    snapshot = trader.get_portfolio_snapshot()
    assert snapshot["recentTrades"] == []
    assert snapshot["recentDecisions"][-1]["decisionType"] == "skip"
```

- [ ] **Step 2: Run the short-flow tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_short_flow.py test_auto_trader_decision_reports.py
```

Expected:

- `AttributeError` or `AssertionError` because `_evaluate_short`, `_paper_short`, `_check_short_exit`, `_paper_cover`, and short replay data do not exist yet

- [ ] **Step 3: Extend decision-report tests for short / cover records**

Add a focused assertion block to `test_auto_trader_decision_reports.py`:

```python
assert short_trade["action"] == "SHORT"
assert short_report["decisionType"] == "short"
assert cover_trade["action"] == "COVER"
assert cover_report["decisionType"] == "cover"
assert cover_report["orderResult"]["status"] == "executed"
```

- [ ] **Step 4: Re-run only the decision-report test file and confirm it still fails for the expected short-path reasons**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py
```

Expected:

- Failures tied to missing short-path implementation, not import or syntax errors

- [ ] **Step 5: Commit**

No git repo is present in this workspace, so skip the commit step and record the reason in the worker notes.

## Task 2: Add minimal short position support to AutoTrader

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Test: `E:\claude code test\test_auto_trader_short_flow.py`

- [ ] **Step 1: Add direction to the position model**

Update `PaperPosition`:

```python
@dataclass
class PaperPosition:
    symbol: str
    side: str
    entry_price: float
    shares: int
    entry_ts: int
    ...
```

- [ ] **Step 2: Update long entry to set `side="long"`**

Minimal patch inside `_paper_buy()`:

```python
position = PaperPosition(
    symbol=symbol,
    side="long",
    entry_price=price,
    shares=shares,
    ...
)
```

- [ ] **Step 3: Route `on_tick()` by position side**

Replace the existing position branch with:

```python
position = self._positions.get(symbol)
if position is not None and position.side == "long":
    await self._check_exit(symbol, price, ts_ms)
elif position is not None and position.side == "short":
    await self._check_short_exit(symbol, price, ts_ms)
elif _is_opening_breakout_window(ts_ms) and change_pct >= OPENING_BREAKOUT_PCT:
    await self._evaluate_buy(symbol, price, change_pct, ts_ms, payload)
elif change_pct >= self._buy_signal_pct:
    await self._evaluate_buy(symbol, price, change_pct, ts_ms, payload)

if symbol not in self._positions:
    await self._evaluate_short(symbol, price, change_pct, ts_ms, payload)
```

Keep the mutual exclusion invariant by storing both directions in the same `self._positions` dictionary.

- [ ] **Step 4: Implement `_evaluate_short()` with the approved gate conditions**

Use these checks in order:

```python
if sentiment_score is None or sentiment_score >= -0.25:
    record skip
if change_pct > -1.5:
    record skip
if not self._is_volume_confirmed(symbol):
    record skip
allowed, reason = self._risk.can_buy(symbol, price, shares, len(self._positions))
if not allowed:
    record skip
```

Then create the short entry:

```python
atr = self._calc_atr(symbol)
stop_price = self._risk.calc_stop_price(price, atr)
target_price = self._risk.calc_target_price(price, stop_price)
short_stop = round(price + (price - stop_price), 2)
short_target = round(price - (target_price - price), 2)
await self._paper_short(
    symbol,
    price,
    change_pct,
    ts_ms,
    stop_price=short_stop,
    target_price=short_target,
    atr=atr,
    decision_report=decision_report,
    shares=shares,
)
```

- [ ] **Step 5: Implement `_paper_short()`**

Model it after `_paper_buy()`:

```python
async def _paper_short(...):
    position = PaperPosition(
        symbol=symbol,
        side="short",
        entry_price=price,
        shares=shares,
        ...
    )
    self._positions[symbol] = position
    record = TradeRecord(
        symbol=symbol,
        action="SHORT",
        price=price,
        shares=shares,
        reason="SIGNAL",
        pnl=0.0,
        ts=ts_ms,
        stop_price=stop_price,
        target_price=target_price,
        decision_report=decision_report,
    )
```

- [ ] **Step 6: Implement `_check_short_exit()`**

```python
async def _check_short_exit(self, symbol: str, price: float, ts_ms: int) -> None:
    position = self._positions[symbol]
    reason: str | None = None
    if price >= position.stop_price:
        reason = "STOP_LOSS"
    elif price <= position.target_price:
        reason = "TAKE_PROFIT"
    if reason:
        pct_from_entry = (position.entry_price - price) / position.entry_price * 100
        await self._paper_cover(symbol, price, reason, pct_from_entry, ts_ms)
```

- [ ] **Step 7: Implement `_paper_cover()`**

Compute short PnL explicitly rather than assuming long math:

```python
gross_pnl = (position.entry_price - price) * position.shares
entry_notional = position.entry_price * position.shares
exit_notional = price * position.shares
buy_fee = price * position.shares * TX_FEE_BUY_PCT / 100
sell_fee = position.entry_price * position.shares * (TX_FEE_SELL_PCT + TX_TAX_SELL_PCT) / 100
net_pnl = round(gross_pnl - buy_fee - sell_fee, 2)
```

Then write the `COVER` trade record and `decision_type="cover"` report.

- [ ] **Step 8: Run the short-flow test file**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_short_flow.py
```

Expected:

- All tests in `test_auto_trader_short_flow.py` pass

- [ ] **Step 9: Commit**

No git repo is present in this workspace, so skip the commit step and record the reason in the worker notes.

## Task 3: Extend replay, EOD flattening, and analyst wording

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Modify: `E:\claude code test\multi_analyst.py`
- Modify: `E:\claude code test\test_auto_trader_decision_reports.py`
- Test: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: Extend `_close_all_eod()` so short positions cover instead of sell**

Use the shared positions dict:

```python
for symbol in symbols:
    position = self._positions[symbol]
    price = self._last_prices.get(symbol, position.entry_price)
    if position.side == "short":
        pct = (position.entry_price - price) / position.entry_price * 100
        await self._paper_cover(symbol, price, "EOD", pct, ts_ms)
    else:
        pct = (price - position.entry_price) / position.entry_price * 100
        await self._paper_sell(symbol, price, "EOD", pct, ts_ms)
```

- [ ] **Step 2: Ensure portfolio snapshot and daily report payload include `SHORT` / `COVER` without schema changes**

Minimal check:

```python
"action": trade.action,
"decisionReport": trade.decision_report.to_dict() if trade.decision_report is not None else None,
```

No new fields should be required.

- [ ] **Step 3: Adjust `multi_analyst.py` copy for short / cover decisions**

Example pattern:

```python
if context.decision_type == "short":
    conclusion = "空方觀點認為利空事件與盤中轉弱已形成有效放空視窗。"
elif context.decision_type == "cover":
    conclusion = "空方觀點認為主要下跌段已完成，回補能保住已實現利潤。"
```

Do the same for the bull, bear, and referee summaries so replay text remains readable.

- [ ] **Step 4: Run the decision-report test file**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py
```

Expected:

- PASS, including short / cover replay assertions

- [ ] **Step 5: Commit**

No git repo is present in this workspace, so skip the commit step and record the reason in the worker notes.

## Task 4: Full verification and regression sweep

**Files:**
- Test: `E:\claude code test\test_auto_trader_short_flow.py`
- Test: `E:\claude code test\test_auto_trader_decision_reports.py`
- Test: full suite

- [ ] **Step 1: Run focused short and decision-report tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_short_flow.py test_auto_trader_decision_reports.py
```

Expected:

- All short-flow and decision-report tests pass

- [ ] **Step 2: Run the full Python test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected:

- Entire backend suite stays green

- [ ] **Step 3: Run Python syntax verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile auto_trader.py multi_analyst.py analyzer.py daily_reporter.py run.py sinopac_bridge.py notifier.py main.py desktop_backend.py
```

Expected:

- No output, exit code `0`

- [ ] **Step 4: Summarize real behavior changes**

Capture in the worker handoff:

- New short entry gate
- Stop / target / EOD cover behavior
- Shared `self._positions` with `side`
- No trailing stop for shorts

- [ ] **Step 5: Commit**

No git repo is present in this workspace, so skip the commit step and record the reason in the worker notes.

## Self-review

- Spec coverage: This plan covers the new `side` field, shared positions dict, short/cover actions and decision types, EOD cover, explicit short PnL handling, analyst wording, and regression testing.
- Placeholder scan: No `TODO` / `TBD` placeholders remain. Each task includes concrete files, code, and commands.
- Type consistency: `PaperPosition.side`, `action="SHORT" / "COVER"`, and `decision_type="short" / "cover"` are used consistently across the plan.

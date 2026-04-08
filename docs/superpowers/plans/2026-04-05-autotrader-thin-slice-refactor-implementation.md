# AutoTrader 薄切重構與單一路徑啟動 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改變策略邏輯與參數的前提下，拆分 `auto_trader.py` 的資料與副作用責任，並將 `main.py` / `run.py` 收斂成單一路徑啟動設計。

**Architecture:** 採薄切重構：保留 `AutoTrader` 作為協調器，只將市場狀態、持倉帳本、決策報告、盤後日報節流等狀態與副作用抽到 `trading/` 子模組。啟動路徑則由 `main.py` 擔任唯一正式 supervisor，`run.py` 退化為 runtime 組裝與相容入口。

**Tech Stack:** Python 3.11、pytest、aiohttp、asyncio、dataclasses、現有 Tauri/React 前端不改行為

---

## File Structure

### New files

- `E:\claude code test\trading\__init__.py`
  - 提供薄切重構後的模組匯出
- `E:\claude code test\trading\market_state.py`
  - 管理 tick/K 棒、均量、ATR、開高低量等市場狀態
- `E:\claude code test\trading\positions.py`
  - 管理 `PaperPosition`、`TradeRecord`、帳本與持倉快照
- `E:\claude code test\trading\decision_reports.py`
  - 管理 `DecisionFactor`、`DecisionReport` 與 replay/front-end 序列化
- `E:\claude code test\trading\reporting.py`
  - 管理 EOD 日報 task、節流狀態與 payload 組裝
- `E:\claude code test\test_trading_market_state.py`
  - 驗證市場狀態抽離後行為不變
- `E:\claude code test\test_trading_positions.py`
  - 驗證持倉與損益快照不變
- `E:\claude code test\test_trading_reporting.py`
  - 驗證 EOD 節流與 task 管理

### Modified files

- `E:\claude code test\auto_trader.py`
  - 改成協調器；保留策略流程，抽離狀態與副作用
- `E:\claude code test\main.py`
  - 明確以 runtime builder 組裝正式 supervisor 路徑
- `E:\claude code test\run.py`
  - 降為 runtime wiring 與相容入口
- `E:\claude code test\test_auto_trader_market_hours.py`
  - 既有保護測試持續使用
- `E:\claude code test\test_auto_trader_short_flow.py`
  - 重構後保持空方流程一致
- `E:\claude code test\test_auto_trader_decision_reports.py`
  - 重構後保持 decision report 一致
- `E:\claude code test\test_main.py`
  - 驗證 supervisor 仍由 `main.py` 控制
- `E:\claude code test\test_run.py`
  - 驗證 `run.py` 仍可作為 builder / 相容入口

---

### Task 1: 建立 `trading` 套件骨架與市場狀態測試

**Files:**
- Create: `E:\claude code test\trading\__init__.py`
- Create: `E:\claude code test\trading\market_state.py`
- Test: `E:\claude code test\test_trading_market_state.py`

- [ ] **Step 1: 寫市場狀態 failing tests**

```python
from trading.market_state import MarketState


def test_market_state_updates_open_last_and_bars() -> None:
    state = MarketState()

    state.update_tick("2330", price=100.0, volume=1000, ts_ms=1_710_000_000_000)
    state.update_tick("2330", price=101.0, volume=2000, ts_ms=1_710_000_020_000)

    assert state.open_price("2330") == 100.0
    assert state.last_price("2330") == 101.0
    assert state.latest_bar("2330").close == 101.0


def test_market_state_tracks_average_volume_and_atr_inputs() -> None:
    state = MarketState()
    base = 1_710_000_000_000

    for index, price in enumerate([100.0, 101.0, 102.0, 103.0, 104.0, 105.0]):
        state.update_tick("2454", price=price, volume=1000 * (index + 1), ts_ms=base + index * 60_000)

    assert state.average_volume("2454") > 0
    assert state.calculate_atr("2454") is not None
```

- [ ] **Step 2: 跑測試確認失敗**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_trading_market_state.py
```

Expected:
`ModuleNotFoundError: No module named 'trading'`

- [ ] **Step 3: 寫最小實作**

`E:\claude code test\trading\__init__.py`
```python
from .market_state import CandleBar, MarketState

__all__ = ["CandleBar", "MarketState"]
```

`E:\claude code test\trading\market_state.py`
```python
from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Optional


@dataclass
class CandleBar:
    ts_min: int
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketState:
    def __init__(self) -> None:
        self._open_prices: dict[str, float] = {}
        self._last_prices: dict[str, float] = {}
        self._current_bar: dict[str, CandleBar] = {}
        self._candle_history: dict[str, collections.deque[CandleBar]] = {}
        self._volume_history: dict[str, collections.deque[int]] = {}

    def update_tick(self, symbol: str, *, price: float, volume: int, ts_ms: int) -> None:
        if symbol not in self._open_prices:
            self._open_prices[symbol] = price
        self._last_prices[symbol] = price

        ts_min = ts_ms // 60_000
        current = self._current_bar.get(symbol)
        if current is None or current.ts_min != ts_min:
            if current is not None:
                self._history(symbol).append(current)
                self._volumes(symbol).append(current.volume)
            self._current_bar[symbol] = CandleBar(ts_min=ts_min, open=price, high=price, low=price, close=price, volume=volume)
            return

        current.high = max(current.high, price)
        current.low = min(current.low, price)
        current.close = price
        current.volume += volume

    def open_price(self, symbol: str) -> float | None:
        return self._open_prices.get(symbol)

    def last_price(self, symbol: str) -> float | None:
        return self._last_prices.get(symbol)

    def latest_bar(self, symbol: str) -> CandleBar | None:
        return self._current_bar.get(symbol)

    def average_volume(self, symbol: str) -> float:
        volumes = self._volumes(symbol)
        return sum(volumes) / len(volumes) if volumes else 0.0

    def calculate_atr(self, symbol: str, bars_needed: int = 5) -> Optional[float]:
        bars = list(self._history(symbol))
        if len(bars) < bars_needed:
            return None
        recent = bars[-bars_needed:]
        ranges = [bar.high - bar.low for bar in recent]
        return sum(ranges) / len(ranges)

    def _history(self, symbol: str) -> collections.deque[CandleBar]:
        if symbol not in self._candle_history:
            self._candle_history[symbol] = collections.deque(maxlen=120)
        return self._candle_history[symbol]

    def _volumes(self, symbol: str) -> collections.deque[int]:
        if symbol not in self._volume_history:
            self._volume_history[symbol] = collections.deque(maxlen=60)
        return self._volume_history[symbol]
```

- [ ] **Step 4: 跑測試確認通過**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_trading_market_state.py
```

Expected:
`2 passed`

- [ ] **Step 5: Commit**

```powershell
git add trading/__init__.py trading/market_state.py test_trading_market_state.py
git commit -m "refactor: add trading market state module"
```

### Task 2: 抽出持倉/帳本模型與損益快照

**Files:**
- Create: `E:\claude code test\trading\positions.py`
- Modify: `E:\claude code test\trading\__init__.py`
- Test: `E:\claude code test\test_trading_positions.py`

- [ ] **Step 1: 寫持倉快照 failing tests**

```python
from trading.positions import PaperPosition, PositionBook, TradeRecord


def test_position_book_computes_long_and_short_unrealized_pnl() -> None:
    book = PositionBook()
    book.positions["2330"] = PaperPosition(
        symbol="2330",
        side="long",
        entry_price=100.0,
        shares=1000,
        entry_ts=1,
        entry_change_pct=0.0,
        stop_price=95.0,
        target_price=110.0,
    )
    book.positions["2317"] = PaperPosition(
        symbol="2317",
        side="short",
        entry_price=100.0,
        shares=1000,
        entry_ts=1,
        entry_change_pct=0.0,
        stop_price=105.0,
        target_price=90.0,
    )

    snapshot = book.build_snapshot({"2330": 105.0, "2317": 95.0}, session_id="abc123")

    long_position = next(item for item in snapshot["positions"] if item["symbol"] == "2330")
    short_position = next(item for item in snapshot["positions"] if item["symbol"] == "2317")

    assert long_position["unrealizedPnl"] > 0
    assert short_position["unrealizedPnl"] > 0
    assert short_position["side"] == "short"


def test_position_book_includes_recent_trades() -> None:
    book = PositionBook()
    book.trade_history.append(
        TradeRecord(symbol="2330", action="SELL", price=110.0, shares=1000, reason="TAKE_PROFIT", pnl=8000.0, ts=2)
    )

    snapshot = book.build_snapshot({}, session_id="abc123")
    assert snapshot["recentTrades"][0]["action"] == "SELL"
```

- [ ] **Step 2: 跑測試確認失敗**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_trading_positions.py
```

Expected:
`ImportError` or attribute error for `PositionBook`

- [ ] **Step 3: 寫最小實作**

`E:\claude code test\trading\positions.py`
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PaperPosition:
    symbol: str
    side: str
    entry_price: float
    shares: int
    entry_ts: int
    entry_change_pct: float
    stop_price: float
    target_price: float
    entry_atr: float | None = None
    peak_price: float = 0.0
    trail_stop_price: float = 0.0


@dataclass
class TradeRecord:
    symbol: str
    action: str
    price: float
    shares: int
    reason: str
    pnl: float
    ts: int
    stop_price: float = 0.0
    target_price: float = 0.0
    gross_pnl: float = 0.0
    decision_report: Any = None


class PositionBook:
    def __init__(self) -> None:
        self.positions: dict[str, PaperPosition] = {}
        self.trade_history: list[TradeRecord] = []

    def build_snapshot(self, last_prices: dict[str, float], *, session_id: str) -> dict[str, Any]:
        positions = []
        unrealized_total = 0.0
        for position in self.positions.values():
            last_price = float(last_prices.get(position.symbol, position.entry_price))
            if position.side == "short":
                unrealized = (position.entry_price - last_price) * position.shares
                change_pct = ((position.entry_price - last_price) / position.entry_price * 100) if position.entry_price else 0.0
            else:
                unrealized = (last_price - position.entry_price) * position.shares
                change_pct = ((last_price - position.entry_price) / position.entry_price * 100) if position.entry_price else 0.0
            unrealized_total += unrealized
            positions.append(
                {
                    "symbol": position.symbol,
                    "side": position.side,
                    "entryPrice": position.entry_price,
                    "lastPrice": last_price,
                    "shares": position.shares,
                    "unrealizedPnl": round(unrealized, 2),
                    "changePct": round(change_pct, 2),
                }
            )

        recent_trades = [
            {
                "symbol": trade.symbol,
                "action": trade.action,
                "price": trade.price,
                "shares": trade.shares,
                "reason": trade.reason,
                "pnl": trade.pnl,
                "ts": trade.ts,
            }
            for trade in self.trade_history[-20:]
        ][::-1]

        return {
            "type": "PAPER_PORTFOLIO",
            "sessionId": session_id,
            "positions": positions,
            "recentTrades": recent_trades,
            "unrealizedPnl": round(unrealized_total, 2),
        }
```

`E:\claude code test\trading\__init__.py`
```python
from .market_state import CandleBar, MarketState
from .positions import PaperPosition, PositionBook, TradeRecord

__all__ = ["CandleBar", "MarketState", "PaperPosition", "PositionBook", "TradeRecord"]
```

- [ ] **Step 4: 跑測試確認通過**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_trading_positions.py
```

Expected:
`2 passed`

- [ ] **Step 5: Commit**

```powershell
git add trading/__init__.py trading/positions.py test_trading_positions.py
git commit -m "refactor: add trading position book module"
```

### Task 3: 抽出決策報告模型與序列化

**Files:**
- Create: `E:\claude code test\trading\decision_reports.py`
- Modify: `E:\claude code test\trading\__init__.py`
- Test: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: 先把現有測試鎖成外部模組匯入**

在 `E:\claude code test\test_auto_trader_decision_reports.py` 新增或改寫：

```python
from trading.decision_reports import DecisionFactor, DecisionReport


def test_decision_report_to_dict_keeps_debate_fields() -> None:
    report = DecisionReport(
        report_id="r1",
        symbol="2330",
        ts=1,
        decision_type="buy",
        trigger_type="mixed",
        confidence=80,
        final_reason="訊號成立",
        summary="決策摘要",
        supporting_factors=[DecisionFactor(kind="news", label="利多", detail="新聞支持")],
        opposing_factors=[],
        risk_flags=["none"],
        source_events=[],
        order_result={"status": "executed"},
        bull_case="多方觀點",
        bear_case="空方觀點",
        risk_case="風控觀點",
        bull_argument="多方論點",
        bear_argument="空方論點",
        referee_verdict="裁決結論",
        debate_winner="bull",
    )

    payload = report.to_dict()
    assert payload["bullArgument"] == "多方論點"
    assert payload["refereeVerdict"] == "裁決結論"
```

- [ ] **Step 2: 跑測試確認失敗**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py
```

Expected:
現有 import 失敗或需調整為新模組

- [ ] **Step 3: 抽出最小實作**

`E:\claude code test\trading\decision_reports.py`
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DecisionFactor:
    kind: str
    label: str
    detail: str


@dataclass
class DecisionReport:
    report_id: str
    symbol: str
    ts: int
    decision_type: str
    trigger_type: str
    confidence: int
    final_reason: str
    summary: str
    supporting_factors: list[DecisionFactor]
    opposing_factors: list[DecisionFactor]
    risk_flags: list[str]
    source_events: list[dict[str, Any]]
    order_result: dict[str, Any]
    bull_case: str = ""
    bear_case: str = ""
    risk_case: str = ""
    bull_argument: str = ""
    bear_argument: str = ""
    referee_verdict: str = ""
    debate_winner: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reportId": self.report_id,
            "symbol": self.symbol,
            "ts": self.ts,
            "decisionType": self.decision_type,
            "triggerType": self.trigger_type,
            "confidence": self.confidence,
            "finalReason": self.final_reason,
            "summary": self.summary,
            "supportingFactors": [
                {"kind": factor.kind, "label": factor.label, "detail": factor.detail}
                for factor in self.supporting_factors
            ],
            "opposingFactors": [
                {"kind": factor.kind, "label": factor.label, "detail": factor.detail}
                for factor in self.opposing_factors
            ],
            "riskFlags": list(self.risk_flags),
            "sourceEvents": list(self.source_events),
            "orderResult": dict(self.order_result),
            "bullCase": self.bull_case,
            "bearCase": self.bear_case,
            "riskCase": self.risk_case,
            "bullArgument": self.bull_argument,
            "bearArgument": self.bear_argument,
            "refereeVerdict": self.referee_verdict,
            "debateWinner": self.debate_winner,
        }
```

`E:\claude code test\trading\__init__.py`
```python
from .decision_reports import DecisionFactor, DecisionReport
from .market_state import CandleBar, MarketState
from .positions import PaperPosition, PositionBook, TradeRecord

__all__ = [
    "CandleBar",
    "DecisionFactor",
    "DecisionReport",
    "MarketState",
    "PaperPosition",
    "PositionBook",
    "TradeRecord",
]
```

- [ ] **Step 4: 跑測試確認通過**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py
```

Expected:
相關 report 測試通過

- [ ] **Step 5: Commit**

```powershell
git add trading/__init__.py trading/decision_reports.py test_auto_trader_decision_reports.py
git commit -m "refactor: extract decision report models"
```

### Task 4: 抽出 EOD reporting 節流模組

**Files:**
- Create: `E:\claude code test\trading\reporting.py`
- Test: `E:\claude code test\test_trading_reporting.py`

- [ ] **Step 1: 寫 reporting failing tests**

```python
import asyncio

from trading.reporting import ReportingCoordinator


def test_reporting_coordinator_only_schedules_one_report_per_day() -> None:
    coordinator = ReportingCoordinator(delay_seconds=1.0)

    assert coordinator.should_schedule_for_date("2026-04-05") is True
    coordinator.mark_scheduled("2026-04-05", asyncio.create_task(asyncio.sleep(0)))
    assert coordinator.should_schedule_for_date("2026-04-05") is False


def test_reporting_coordinator_can_cancel_pending_task() -> None:
    coordinator = ReportingCoordinator(delay_seconds=1.0)
    task = asyncio.create_task(asyncio.sleep(10))
    coordinator.mark_scheduled("2026-04-05", task)

    coordinator.cancel_pending_report()
    assert task.cancelled() is True or task.cancelling() > 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_trading_reporting.py
```

Expected:
`ModuleNotFoundError` or missing `ReportingCoordinator`

- [ ] **Step 3: 寫最小實作**

`E:\claude code test\trading\reporting.py`
```python
from __future__ import annotations

import asyncio
from typing import Any


class ReportingCoordinator:
    def __init__(self, *, delay_seconds: float) -> None:
        self.delay_seconds = max(0.0, float(delay_seconds))
        self._last_eod_report_date: str | None = None
        self._eod_report_task: asyncio.Task[Any] | None = None

    def should_schedule_for_date(self, trading_date: str) -> bool:
        return self._last_eod_report_date != trading_date

    def mark_scheduled(self, trading_date: str, task: asyncio.Task[Any]) -> None:
        self._last_eod_report_date = trading_date
        self._eod_report_task = task

    def cancel_pending_report(self) -> None:
        if self._eod_report_task is not None and not self._eod_report_task.done():
            self._eod_report_task.cancel()

    @property
    def pending_task(self) -> asyncio.Task[Any] | None:
        return self._eod_report_task
```

- [ ] **Step 4: 跑測試確認通過**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_trading_reporting.py
```

Expected:
`2 passed`

- [ ] **Step 5: Commit**

```powershell
git add trading/reporting.py test_trading_reporting.py
git commit -m "refactor: add reporting coordinator"
```

### Task 5: 在 `auto_trader.py` 內接入新模組，但保持行為不變

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Test: `E:\claude code test\test_auto_trader_market_hours.py`
- Test: `E:\claude code test\test_auto_trader_short_flow.py`
- Test: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: 先鎖現有核心行為測試**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_market_hours.py test_auto_trader_short_flow.py test_auto_trader_decision_reports.py
```

Expected:
全部通過，作為重構前基線

- [ ] **Step 2: 用新模組取代內部資料欄位**

在 `E:\claude code test\auto_trader.py` 中：

- 匯入：
```python
from trading.decision_reports import DecisionFactor, DecisionReport
from trading.market_state import CandleBar, MarketState
from trading.positions import PaperPosition, PositionBook, TradeRecord
from trading.reporting import ReportingCoordinator
```

- 在 `__init__` 改成：
```python
self._market_state = MarketState()
self._position_book = PositionBook()
self._reporting = ReportingCoordinator(delay_seconds=self._eod_report_delay_seconds)
```

- 保留原有公開方法名稱，但把：
  - `_open_prices`
  - `_last_prices`
  - `_current_bar`
  - `_candle_history`
  - `_volume_history`
  - `_positions`
  - `_trade_history`
  - `_decision_history`
  - `_eod_report_task`
  - `_last_eod_report_date`
 逐步改成委派給 service 物件。

- [ ] **Step 3: 跑核心行為測試**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_market_hours.py test_auto_trader_short_flow.py test_auto_trader_decision_reports.py
```

Expected:
全部仍通過

- [ ] **Step 4: 跑完整 Python 測試**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected:
所有 Python 測試通過

- [ ] **Step 5: Commit**

```powershell
git add auto_trader.py
git commit -m "refactor: slim auto trader orchestration"
```

### Task 6: 收斂 `main.py` / `run.py` 啟動責任

**Files:**
- Modify: `E:\claude code test\main.py`
- Modify: `E:\claude code test\run.py`
- Test: `E:\claude code test\test_main.py`
- Test: `E:\claude code test\test_run.py`

- [ ] **Step 1: 寫結構保護測試**

在 `E:\claude code test\test_run.py` 或新增斷言：

```python
from run import build_runtime_components


def test_build_runtime_components_returns_dependencies_only() -> None:
    runtime = build_runtime_components()
    assert hasattr(runtime, "collector")
    assert hasattr(runtime, "notifier")
    assert hasattr(runtime, "analyzer")
```

在 `E:\claude code test\test_main.py` 新增：

```python
async def test_supervisor_can_start_from_runtime_builder() -> None:
    from main import create_supervisor_from_runtime

    supervisor = create_supervisor_from_runtime(...)
    assert supervisor is not None
```

- [ ] **Step 2: 跑測試確認失敗或缺少 builder**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_main.py test_run.py
```

Expected:
至少一個測試因缺少 builder/helper 而失敗

- [ ] **Step 3: 在 `run.py` 抽 runtime builder，在 `main.py` 使用它**

`E:\claude code test\run.py`
```python
from dataclasses import dataclass


@dataclass
class RuntimeComponents:
    state_store: object
    analyzer: object
    collector: object
    notifier: object
    ipc_manager: object | None = None


def build_runtime_components(...) -> RuntimeComponents:
    ...
    return RuntimeComponents(
        state_store=state_store,
        analyzer=analyzer,
        collector=collector,
        notifier=notifier,
        ipc_manager=ipc_manager,
    )
```

`E:\claude code test\main.py`
```python
from run import build_runtime_components


def create_supervisor_from_runtime(...) -> AppSupervisor:
    runtime = build_runtime_components(...)
    return AppSupervisor(
        state_store=runtime.state_store,
        analyzer=runtime.analyzer,
        collector=runtime.collector,
        notifier=runtime.notifier,
        ipc_manager=runtime.ipc_manager,
    )
```

- [ ] **Step 4: 跑整合測試**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q test_main.py test_run.py
```

Expected:
全部通過

- [ ] **Step 5: Commit**

```powershell
git add main.py run.py test_main.py test_run.py
git commit -m "refactor: unify runtime startup path"
```

### Task 7: 完整驗證並確認桌面與前端不受影響

**Files:**
- Modify: `E:\claude code test\docs\superpowers\specs\2026-04-05-autotrader-thin-slice-refactor-design.md`
  - 如有需要，更新實作結果與實際路徑差異

- [ ] **Step 1: 跑完整 Python 測試**

Run:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected:
全部通過

- [ ] **Step 2: 跑前端測試**

Run:
```powershell
npm.cmd test
```

Expected:
全部通過

- [ ] **Step 3: 跑前端 build**

Run:
```powershell
npm.cmd run build
```

Expected:
成功完成

- [ ] **Step 4: 跑桌面打包 smoke test**

Run:
```powershell
npm.cmd run desktop:package
```

Expected:
成功完成桌面打包

- [ ] **Step 5: Commit**

```powershell
git add .
git commit -m "test: verify thin-slice autotrader refactor"
```


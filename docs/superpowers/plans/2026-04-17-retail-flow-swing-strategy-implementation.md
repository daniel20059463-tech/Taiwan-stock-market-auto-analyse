# Retail Flow Swing Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一套以外資、投信、主力買超為主訊號、持有 3 到 10 天、非當沖的散戶波段策略，並與現有短線策略並存。

**Architecture:** 保留現有 `auto_trader.py` 執行與風控骨架，新增獨立的籌碼資料提供器、每日籌碼快取與 `RetailFlowSwingStrategy`。盤後從 Wantgoo 更新籌碼資料，盤中使用籌碼快照加上 `10 日線 + 量能` 確認進場，賣出使用 `硬停損 + 跌破 10 日線 + 籌碼轉弱 + 時間出場`。

**Tech Stack:** Python 3.11、aiohttp/urllib 既有 HTTP 能力、現有 `AutoTrader` / `RiskManager` / `models.py`、pytest

---

## File Structure

- Create: `E:\claude code test\institutional_flow_provider.py`
  - 從 Wantgoo 抓取外資/投信/主力買賣超資料
  - 清洗成統一資料模型

- Create: `E:\claude code test\institutional_flow_cache.py`
  - 保存每日盤後籌碼快照
  - 提供查詢最近交易日籌碼資料的介面

- Create: `E:\claude code test\retail_flow_strategy.py`
  - 實作波段策略進出場判斷
  - 提供 `watch / ready_to_buy / skip / sell` 類型輸出

- Modify: `E:\claude code test\auto_trader.py`
  - 新增策略模式切換
  - 在不破壞現有短線策略前提下接入 swing strategy
  - Swing 模式下停用 EOD flatten 主路徑

- Modify: `E:\claude code test\run.py`
  - 建立新策略需要的 provider/cache 實例
  - 注入 `AutoTrader`

- Modify: `E:\claude code test\models.py`
  - 若需要，新增簡單的籌碼快照持久化表或本地存取支援

- Modify: `E:\claude code test\.env.example`
  - 加入策略模式、資料抓取開關等設定

- Test: `E:\claude code test\test_institutional_flow_provider.py`
- Test: `E:\claude code test\test_institutional_flow_cache.py`
- Test: `E:\claude code test\test_retail_flow_strategy.py`
- Modify Test: `E:\claude code test\test_auto_trader_decision_reports.py`
- Modify Test: `E:\claude code test\test_run.py`

## Task 1: 定義籌碼資料模型與抓取器

**Files:**
- Create: `E:\claude code test\institutional_flow_provider.py`
- Test: `E:\claude code test\test_institutional_flow_provider.py`

- [ ] **Step 1: Write the failing tests**

```python
from institutional_flow_provider import (
    InstitutionalFlowRow,
    parse_wantgoo_rank_table,
)


def test_parse_wantgoo_rank_table_extracts_symbol_and_three_flow_columns():
    html = """
    <table>
      <tr>
        <th>股票</th><th>外資</th><th>投信</th><th>主力</th>
      </tr>
      <tr>
        <td>2330 台積電</td><td>12000</td><td>3000</td><td>8000</td>
      </tr>
    </table>
    """

    rows = parse_wantgoo_rank_table(html)

    assert rows == [
        InstitutionalFlowRow(
            symbol="2330",
            name="台積電",
            foreign_net_buy=12000,
            investment_trust_net_buy=3000,
            major_net_buy=8000,
        )
    ]


def test_parse_wantgoo_rank_table_returns_empty_when_required_columns_missing():
    html = "<html><body><div>no table</div></body></html>"
    assert parse_wantgoo_rank_table(html) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_institutional_flow_provider.py
```

Expected:
- FAIL with `ModuleNotFoundError` or missing symbol/function errors

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass
import re
from html.parser import HTMLParser


@dataclass(frozen=True)
class InstitutionalFlowRow:
    symbol: str
    name: str
    foreign_net_buy: int
    investment_trust_net_buy: int
    major_net_buy: int


class _SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"td", "th"}:
            self.in_cell = True
        elif tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            self.in_cell = False
        elif tag == "tr" and self.current_row:
            self.rows.append(self.current_row)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            text = data.strip()
            if text:
                self.current_row.append(text)


def _parse_number(text: str) -> int:
    return int(text.replace(",", "").strip())


def parse_wantgoo_rank_table(html: str) -> list[InstitutionalFlowRow]:
    parser = _SimpleTableParser()
    parser.feed(html)
    if len(parser.rows) < 2:
        return []

    header = parser.rows[0]
    if not {"股票", "外資", "投信", "主力"}.issubset(set(header)):
        return []

    stock_idx = header.index("股票")
    foreign_idx = header.index("外資")
    trust_idx = header.index("投信")
    major_idx = header.index("主力")

    output: list[InstitutionalFlowRow] = []
    for row in parser.rows[1:]:
        if len(row) <= max(stock_idx, foreign_idx, trust_idx, major_idx):
            continue
        match = re.match(r"(?P<symbol>\d{4})\s+(?P<name>.+)", row[stock_idx])
        if not match:
            continue
        output.append(
            InstitutionalFlowRow(
                symbol=match.group("symbol"),
                name=match.group("name"),
                foreign_net_buy=_parse_number(row[foreign_idx]),
                investment_trust_net_buy=_parse_number(row[trust_idx]),
                major_net_buy=_parse_number(row[major_idx]),
            )
        )
    return output
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_institutional_flow_provider.py
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add .\institutional_flow_provider.py .\test_institutional_flow_provider.py
git commit -m "feat: add institutional flow provider parser"
```

## Task 2: 加入每日籌碼快取

**Files:**
- Create: `E:\claude code test\institutional_flow_cache.py`
- Test: `E:\claude code test\test_institutional_flow_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
from institutional_flow_cache import InstitutionalFlowCache
from institutional_flow_provider import InstitutionalFlowRow


def test_cache_stores_rows_by_trade_date_and_symbol():
    cache = InstitutionalFlowCache()
    cache.store(
        trade_date="2026-04-17",
        rows=[
            InstitutionalFlowRow("2330", "台積電", 1000, 500, 800),
        ],
    )

    row = cache.get("2026-04-17", "2330")

    assert row is not None
    assert row.foreign_net_buy == 1000


def test_cache_returns_none_for_missing_symbol():
    cache = InstitutionalFlowCache()
    assert cache.get("2026-04-17", "1101") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_institutional_flow_cache.py
```

Expected:
- FAIL with missing module/class

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from collections import defaultdict
from institutional_flow_provider import InstitutionalFlowRow


class InstitutionalFlowCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, InstitutionalFlowRow]] = defaultdict(dict)

    def store(self, *, trade_date: str, rows: list[InstitutionalFlowRow]) -> None:
        self._data[trade_date] = {row.symbol: row for row in rows}

    def get(self, trade_date: str, symbol: str) -> InstitutionalFlowRow | None:
        return self._data.get(trade_date, {}).get(symbol)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_institutional_flow_cache.py
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add .\institutional_flow_cache.py .\test_institutional_flow_cache.py
git commit -m "feat: add institutional flow cache"
```

## Task 3: 實作籌碼分數與觀察名單邏輯

**Files:**
- Create: `E:\claude code test\retail_flow_strategy.py`
- Test: `E:\claude code test\test_retail_flow_strategy.py`

- [ ] **Step 1: Write the failing tests**

```python
from institutional_flow_provider import InstitutionalFlowRow
from retail_flow_strategy import compute_flow_score, classify_watch_state


def test_compute_flow_score_weights_foreign_trust_and_major():
    row = InstitutionalFlowRow(
        symbol="2330",
        name="台積電",
        foreign_net_buy=1000,
        investment_trust_net_buy=500,
        major_net_buy=800,
    )

    score = compute_flow_score(row)

    assert score > 0


def test_classify_watch_state_marks_watch_when_flow_is_positive_but_price_not_confirmed():
    state = classify_watch_state(
        flow_score=0.7,
        above_ma10=False,
        volume_confirmed=False,
        recent_runup_pct=2.0,
    )

    assert state == "watch"


def test_classify_watch_state_marks_ready_to_buy_when_all_confirmations_pass():
    state = classify_watch_state(
        flow_score=0.8,
        above_ma10=True,
        volume_confirmed=True,
        recent_runup_pct=3.0,
    )

    assert state == "ready_to_buy"


def test_classify_watch_state_marks_skip_when_recent_runup_is_too_high():
    state = classify_watch_state(
        flow_score=0.8,
        above_ma10=True,
        volume_confirmed=True,
        recent_runup_pct=11.0,
    )

    assert state == "skip"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_strategy.py
```

Expected:
- FAIL with missing symbols

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from institutional_flow_provider import InstitutionalFlowRow


def _positive_score(value: int) -> float:
    return 1.0 if value > 0 else 0.0


def compute_flow_score(row: InstitutionalFlowRow) -> float:
    trust = _positive_score(row.investment_trust_net_buy) * 0.4
    foreign = _positive_score(row.foreign_net_buy) * 0.35
    major = _positive_score(row.major_net_buy) * 0.25
    return round(trust + foreign + major, 2)


def classify_watch_state(
    *,
    flow_score: float,
    above_ma10: bool,
    volume_confirmed: bool,
    recent_runup_pct: float,
) -> str:
    if flow_score <= 0:
        return "skip"
    if recent_runup_pct >= 10.0:
        return "skip"
    if above_ma10 and volume_confirmed:
        return "ready_to_buy"
    return "watch"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_strategy.py
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add .\retail_flow_strategy.py .\test_retail_flow_strategy.py
git commit -m "feat: add retail flow scoring and watch states"
```

## Task 4: 補進場與出場判斷

**Files:**
- Modify: `E:\claude code test\retail_flow_strategy.py`
- Modify Test: `E:\claude code test\test_retail_flow_strategy.py`

- [ ] **Step 1: Write the failing tests**

```python
from retail_flow_strategy import should_enter_position, should_exit_position


def test_should_enter_position_requires_ready_to_buy_state():
    assert should_enter_position(watch_state="ready_to_buy") is True
    assert should_enter_position(watch_state="watch") is False


def test_should_exit_position_when_price_breaks_below_ma10():
    assert should_exit_position(
        stop_loss_hit=False,
        close_below_ma10=True,
        flow_weakened=False,
        holding_days=4,
    ) == "ma10_break"


def test_should_exit_position_when_flow_weakened():
    assert should_exit_position(
        stop_loss_hit=False,
        close_below_ma10=False,
        flow_weakened=True,
        holding_days=4,
    ) == "flow_weakened"


def test_should_exit_position_when_holding_days_exceed_limit():
    assert should_exit_position(
        stop_loss_hit=False,
        close_below_ma10=False,
        flow_weakened=False,
        holding_days=11,
    ) == "time_exit"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_strategy.py
```

Expected:
- FAIL on missing functions

- [ ] **Step 3: Write minimal implementation**

```python
def should_enter_position(*, watch_state: str) -> bool:
    return watch_state == "ready_to_buy"


def should_exit_position(
    *,
    stop_loss_hit: bool,
    close_below_ma10: bool,
    flow_weakened: bool,
    holding_days: int,
) -> str | None:
    if stop_loss_hit:
        return "stop_loss"
    if close_below_ma10:
        return "ma10_break"
    if flow_weakened:
        return "flow_weakened"
    if holding_days > 10:
        return "time_exit"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_retail_flow_strategy.py
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add .\retail_flow_strategy.py .\test_retail_flow_strategy.py
git commit -m "feat: add retail flow entry and exit rules"
```

## Task 5: 將策略整合進 AutoTrader 但不取代短線邏輯

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Modify Test: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_swing_strategy_path_does_not_trigger_eod_flatten(...):
    ...


def test_swing_strategy_uses_retail_flow_entry_logic(...):
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_auto_trader_decision_reports.py
```

Expected:
- FAIL because swing strategy path does not exist

- [ ] **Step 3: Write minimal implementation**

Implementation requirements:

```python
# add constructor argument
strategy_mode: str = "intraday"

# supported values
"intraday"
"retail_flow_swing"

# branch inside on_tick / evaluate path
if self._strategy_mode == "retail_flow_swing":
    # use swing strategy instead of existing intraday breakout logic
```

Also ensure:

```python
# EOD flatten only for intraday mode
if self._strategy_mode == "intraday" and _is_eod_close_time(ts_ms) and not self._eod_closed:
    await self._close_all_eod(ts_ms)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_auto_trader_decision_reports.py
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add .\auto_trader.py .\test_auto_trader_decision_reports.py
git commit -m "feat: add retail flow swing strategy mode"
```

## Task 6: 在 run.py 注入新策略依賴

**Files:**
- Modify: `E:\claude code test\run.py`
- Modify Test: `E:\claude code test\test_run.py`
- Modify: `E:\claude code test\.env.example`

- [ ] **Step 1: Write the failing tests**

```python
def test_runtime_builds_retail_flow_swing_dependencies_when_enabled(...):
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_run.py
```

Expected:
- FAIL because runtime does not create swing strategy dependencies

- [ ] **Step 3: Write minimal implementation**

Implementation requirements:

```python
# new env variable
STRATEGY_MODE=intraday

# when STRATEGY_MODE=retail_flow_swing:
# - build InstitutionalFlowProvider
# - build InstitutionalFlowCache
# - build RetailFlowSwingStrategy
# - inject into AutoTrader
```

Update `.env.example` with:

```env
STRATEGY_MODE=intraday
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q .\test_run.py
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add .\run.py .\test_run.py .\.env.example
git commit -m "feat: wire retail flow swing strategy into runtime"
```

## Task 7: 補整體回歸與文件

**Files:**
- Modify: `E:\claude code test\docs\superpowers\specs\2026-04-17-retail-flow-swing-strategy-design.md`
- Modify: `E:\claude code test\docs\superpowers\plans\2026-04-17-retail-flow-swing-strategy-implementation.md`
- Optional Modify: `E:\claude code test\README.md` if strategy modes are documented there

- [ ] **Step 1: Run full Python test suite**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m pytest -q
```

Expected:
- PASS with no new failures

- [ ] **Step 2: Run syntax verification**

Run:

```powershell
E:\claude code test\.venv\Scripts\python.exe -m py_compile .\auto_trader.py .\run.py .\institutional_flow_provider.py .\institutional_flow_cache.py .\retail_flow_strategy.py
```

Expected:
- no output

- [ ] **Step 3: Update docs if needed**

Document:
- `STRATEGY_MODE`
- data source limitations for Wantgoo
- that first version is daily post-close flow, not intraday institutional feed

- [ ] **Step 4: Commit**

```powershell
git add .\docs\superpowers\specs\2026-04-17-retail-flow-swing-strategy-design.md .\docs\superpowers\plans\2026-04-17-retail-flow-swing-strategy-implementation.md
git commit -m "docs: finalize retail flow swing strategy plan"
```

## Self-Review

### Spec coverage

- 策略並存：Task 5, Task 6
- Wantgoo 盤後資料源：Task 1, Task 2
- 外資 + 投信 + 主力評分：Task 3
- `10 日線 + 量能` 進場確認：Task 3, Task 4, Task 5
- `停損 + 跌破 10 日線 + 籌碼轉弱 + 時間出場`：Task 4, Task 5
- Swing 路徑不走 EOD flatten：Task 5

### Placeholder scan

- 沒有使用 `TBD` / `TODO`
- 仍保留的 `...` 僅出現在測試名稱示意，執行時必須展開成實際 fixtures；實作者不得保留 `...`

### Type consistency

- `InstitutionalFlowRow`
- `InstitutionalFlowCache`
- `RetailFlowSwingStrategy`
- `STRATEGY_MODE`
- `retail_flow_swing`

名稱已在任務中保持一致。

## Execution Handoff

Plan complete and saved to `E:\claude code test\docs\superpowers\plans\2026-04-17-retail-flow-swing-strategy-implementation.md`. Two execution options:

1. Subagent-Driven (recommended) - 我逐 task 派獨立實作，分段 review  
2. Inline Execution - 我在這個 session 直接按 TDD 連續做完

Which approach?

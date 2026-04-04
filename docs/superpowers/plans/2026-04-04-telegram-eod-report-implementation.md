# Telegram 盤後日報 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在收盤後延遲生成盤後 LLM 日報，並透過 Telegram 推送整日總結與單筆重點檢討。

**Architecture:** 新增 `daily_reporter.py` 作為獨立模組，負責整理日報輸入、挑選重點交易、呼叫 LLM 與 fallback 模板，最後透過 `NotifierService` 發送。`AutoTrader` 只負責在 EOD 平倉完成後排程延遲任務，不直接承擔日報內容生成。

**Tech Stack:** Python 3.11、pytest、現有 `NotifierService`、現有 `DecisionReport` / `TradeRecord`、asyncio

---

### Task 1: 建立日報模組與失敗測試

**Files:**
- Create: `E:\claude code test\daily_reporter.py`
- Create: `E:\claude code test\test_daily_reporter.py`

- [ ] **Step 1: 寫失敗測試**

```python
from daily_reporter import DailyReporter, DailyTradeInsight


def test_daily_reporter_generates_llm_report_from_top_trades():
    sent = []

    def fake_sender(*, chat_id: int, text: str, parse_mode: str):
        sent.append((chat_id, text, parse_mode))

    class FakeLLM:
        def summarize_trade(self, payload):
            return f"單筆檢討：{payload['symbol']} {payload['final_reason']}"

        def summarize_day(self, payload):
            return "盤後日報：今日表現穩定。"

    reporter = DailyReporter(chat_id=123, telegram_sender=fake_sender, llm_client=FakeLLM())
    result = reporter.build_and_send(day_payload={...})

    assert "盤後日報" in result.text
    assert sent
```

- [ ] **Step 2: 跑測試確認會失敗**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_daily_reporter.py`
Expected: FAIL，因為 `daily_reporter.py` 尚未存在或介面未實作。

- [ ] **Step 3: 寫最小實作**

```python
class DailyReporter:
    def __init__(self, *, chat_id, telegram_sender, llm_client): ...
    def build_and_send(self, day_payload): ...
```

- [ ] **Step 4: 再跑測試確認會通過**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_daily_reporter.py`
Expected: PASS

### Task 2: 補重點交易挑選與 fallback 路徑

**Files:**
- Modify: `E:\claude code test\daily_reporter.py`
- Modify: `E:\claude code test\test_daily_reporter.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_daily_reporter_falls_back_to_template_when_llm_fails():
    class FailingLLM:
        def summarize_trade(self, payload):
            raise RuntimeError("llm down")

        def summarize_day(self, payload):
            raise RuntimeError("llm down")

    reporter = DailyReporter(chat_id=123, telegram_sender=fake_sender, llm_client=FailingLLM())
    result = reporter.build_and_send(day_payload={...})

    assert "盤後日報" in result.text
    assert "模板摘要" in result.text
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_daily_reporter.py::test_daily_reporter_falls_back_to_template_when_llm_fails`
Expected: FAIL，因為 fallback 尚未實作。

- [ ] **Step 3: 實作重點交易挑選與 fallback**

```python
def select_highlight_trades(...): ...
def build_fallback_report(...): ...
```

- [ ] **Step 4: 再跑測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_daily_reporter.py`
Expected: PASS

### Task 3: 接入 AutoTrader 的收盤後延遲觸發

**Files:**
- Modify: `E:\claude code test\auto_trader.py`
- Modify: `E:\claude code test\test_auto_trader_decision_reports.py`

- [ ] **Step 1: 寫失敗測試**

```python
@pytest.mark.asyncio
async def test_auto_trader_triggers_delayed_eod_report_once_positions_closed():
    reporter = FakeReporter()
    trader = AutoTrader(..., daily_reporter=reporter, eod_report_delay_seconds=0.01)
    ...
    await trader._close_all_eod(ts_ms)
    await asyncio.sleep(0.05)
    assert reporter.calls == 1
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py::test_auto_trader_triggers_delayed_eod_report_once_positions_closed`
Expected: FAIL，因為 `AutoTrader` 尚未整合日報排程。

- [ ] **Step 3: 實作延遲觸發**

```python
self._daily_reporter = daily_reporter
self._eod_report_delay_seconds = eod_report_delay_seconds
...
asyncio.create_task(self._run_eod_report_after_delay(ts_ms))
```

- [ ] **Step 4: 再跑測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_auto_trader_decision_reports.py::test_auto_trader_triggers_delayed_eod_report_once_positions_closed`
Expected: PASS

### Task 4: 將日報內容整合到 Telegram 通知流程

**Files:**
- Modify: `E:\claude code test\daily_reporter.py`
- Modify: `E:\claude code test\test_daily_reporter.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_daily_reporter_respects_telegram_length_limit():
    result = reporter.build_and_send(day_payload=huge_payload)
    assert len(result.text) <= 4096
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_daily_reporter.py::test_daily_reporter_respects_telegram_length_limit`
Expected: FAIL，因為尚未截斷。

- [ ] **Step 3: 實作長度控制**

```python
def clamp_telegram_text(text: str) -> str: ...
```

- [ ] **Step 4: 再跑測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest -q test_daily_reporter.py`
Expected: PASS

### Task 5: 完整驗證

**Files:**
- Verify only

- [ ] **Step 1: 跑前端測試**

Run: `npm test`
Expected: 所有 vitest 通過

- [ ] **Step 2: 跑前端建置**

Run: `npm run build`
Expected: build 成功

- [ ] **Step 3: 跑後端測試**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 全部 pytest 通過

- [ ] **Step 4: 跑 Python 語法驗證**

Run: `.\.venv\Scripts\python.exe -m py_compile auto_trader.py daily_reporter.py multi_analyst.py run.py sinopac_bridge.py notifier.py analyzer.py main.py desktop_backend.py`
Expected: 無輸出，exit 0

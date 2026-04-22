# Sinopac Native Quote Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 [E:\claude code test\sinopac_bridge.py](E:\claude code test\sinopac_bridge.py) 的五檔與逐筆成交改為維護永豐原生 buffer，再透過既有 `ORDER_BOOK_SNAPSHOT / TRADE_TAPE_SNAPSHOT` WebSocket 協議推送給 Flutter。

**Architecture:** 保持現有 `subscribe_quote_detail` 協議不變，只替換資料來源層。`TickSTKv1` 直接維護逐筆成交 ring buffer，`BidAskSTKv1` 直接維護五檔快照，snapshot builder 只做格式轉譯，不再合成價階。先用測試鎖定原生 callback 寫入與空資料行為，再做最小實作。

**Tech Stack:** Python 3, asyncio, websockets, Shioaji 1.3.2, pytest

---

### Task 1: 為原生五檔與逐筆成交行為補測試

**Files:**
- Modify: `E:\claude code test\test_sinopac_bridge.py`
- Test: `E:\claude code test\test_sinopac_bridge.py`

- [ ] **Step 1: Write the failing tests**

在 [E:\claude code test\test_sinopac_bridge.py](E:\claude code test\test_sinopac_bridge.py) 追加以下測試：

```python
def test_build_order_book_snapshot_reads_native_bidask_buffer() -> None:
    collector = SinopacCollector(["2330"], api_key="demo", secret_key="demo")
    collector._order_book_buffers = {
        "2330": {
            "timestamp": 1_712_900_000_000,
            "asks": [
                {"level": 1, "price": 780.0, "volume": 342},
                {"level": 2, "price": 781.0, "volume": 120},
            ],
            "bids": [
                {"level": 1, "price": 779.0, "volume": 664},
                {"level": 2, "price": 778.0, "volume": 250},
            ],
        }
    }

    snapshot = collector._build_order_book_snapshot("2330")

    assert snapshot["type"] == "ORDER_BOOK_SNAPSHOT"
    assert snapshot["symbol"] == "2330"
    assert snapshot["asks"][0] == {"level": 1, "price": 780.0, "volume": 342}
    assert snapshot["bids"][0] == {"level": 1, "price": 779.0, "volume": 664}


def test_build_order_book_snapshot_returns_empty_lists_without_native_bidask() -> None:
    collector = SinopacCollector(["2330"], api_key="demo", secret_key="demo")

    snapshot = collector._build_order_book_snapshot("2330")

    assert snapshot["asks"] == []
    assert snapshot["bids"] == []


def test_record_native_trade_tape_uses_tick_price_direction() -> None:
    collector = SinopacCollector(["2330"], api_key="demo", secret_key="demo")

    collector._record_trade_tape("2330", price=780.0, volume=1000, ts_ms=1_712_900_000_000)
    collector._record_trade_tape("2330", price=781.0, volume=2000, ts_ms=1_712_900_060_000)
    collector._record_trade_tape("2330", price=780.5, volume=3000, ts_ms=1_712_900_120_000)

    rows = collector._build_trade_tape_snapshot("2330")["rows"]

    assert rows[0]["side"] == "neutral"
    assert rows[1]["side"] == "outer"
    assert rows[2]["side"] == "inner"


def test_on_bidask_callback_updates_native_order_book_buffer() -> None:
    collector = SinopacCollector(["2330"], api_key="demo", secret_key="demo")
    collector._loop = asyncio.new_event_loop()

    class _BidAsk:
        code = "2330"
        datetime = "2026-04-12 09:01:00"
        bid_price = [779.0, 778.0, 777.0, 776.0, 775.0]
        bid_volume = [664, 250, 180, 90, 50]
        ask_price = [780.0, 781.0, 782.0, 783.0, 784.0]
        ask_volume = [342, 120, 88, 60, 40]

    collector._apply_native_bidask(_BidAsk())
    snapshot = collector._build_order_book_snapshot("2330")

    assert snapshot["asks"][0] == {"level": 1, "price": 780.0, "volume": 342}
    assert snapshot["bids"][0] == {"level": 1, "price": 779.0, "volume": 664}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q '.\test_sinopac_bridge.py' -k 'native_bidask or native_trade_tape or build_order_book_snapshot'
```

Expected:
- FAIL because `_order_book_buffers` / `_apply_native_bidask` behavior does not exist yet
- Existing `_build_order_book_snapshot()` still returns synthetic levels

- [ ] **Step 3: Write minimal implementation hooks**

In [E:\claude code test\sinopac_bridge.py](E:\claude code test\sinopac_bridge.py), add these fields and helper signatures:

```python
self._order_book_buffers: dict[str, dict[str, Any]] = {}

def _apply_native_bidask(self, bidask: Any) -> None:
    ...

def _extract_bidask_levels(self, bidask: Any, side: str) -> list[dict[str, Any]]:
    ...
```

Also change `_build_order_book_snapshot()` so it reads from `self._order_book_buffers`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q '.\test_sinopac_bridge.py' -k 'native_bidask or native_trade_tape or build_order_book_snapshot'
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\test_sinopac_bridge.py E:\claude code test\sinopac_bridge.py
git commit -m "test: lock native quote detail snapshot behavior"
```

### Task 2: 將 SinopacCollector 改為維護原生五檔 buffer

**Files:**
- Modify: `E:\claude code test\sinopac_bridge.py`
- Test: `E:\claude code test\test_sinopac_bridge.py`

- [ ] **Step 1: Write the failing subscription test**

在 [E:\claude code test\test_sinopac_bridge.py](E:\claude code test\test_sinopac_bridge.py) 加入測試，驗證 collector 在個股訂閱時會同時訂閱 `Tick` 與 `BidAsk`：

```python
def test_login_and_subscribe_sync_subscribes_tick_and_bidask_for_symbols(monkeypatch) -> None:
    subscribed: list[tuple[str, str]] = []

    class _Quote:
        def subscribe(self, contract, quote_type=None):
            subscribed.append((contract.code, str(quote_type)))

        def set_on_tick_stk_v1_callback(self, func, bind=False):
            self.tick_callback = func

        def set_on_bidask_stk_v1_callback(self, func, bind=False):
            self.bidask_callback = func

    class _Stocks:
        TSE = {"2330": type("Contract", (), {"code": "2330", "name": "台積電", "category": "24"})()}
        OTC = {}
        OES = {}

    class _Contracts:
        Stocks = _Stocks()
        class Indices:
            TSE = {}

    class _Api:
        def __init__(self, simulation=False):
            self.quote = _Quote()
            self.Contracts = _Contracts()

        def login(self, api_key=None, secret_key=None):
            return None

        def snapshots(self, contracts):
            return []

    import sys
    fake_module = type("FakeShioajiModule", (), {"Shioaji": _Api})
    monkeypatch.setitem(sys.modules, "shioaji", fake_module)
    monkeypatch.setitem(
        sys.modules,
        "shioaji.constant",
        type("FakeConstModule", (), {"QuoteType": type("QuoteType", (), {"Tick": "Tick", "BidAsk": "BidAsk"})}),
    )

    collector = SinopacCollector(["2330"], api_key="demo", secret_key="demo")
    collector._loop = asyncio.new_event_loop()
    collector._login_and_subscribe_sync()

    assert ("2330", "Tick") in subscribed
    assert ("2330", "BidAsk") in subscribed
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q '.\test_sinopac_bridge.py' -k 'subscribes_tick_and_bidask'
```

Expected:
- FAIL because only `QuoteType.Tick` is subscribed now

- [ ] **Step 3: Write minimal implementation**

Update `_login_and_subscribe_sync()` in [E:\claude code test\sinopac_bridge.py](E:\claude code test\sinopac_bridge.py):

```python
try:
    api.quote.set_on_tick_stk_v1_callback(_on_tick)
except Exception:
    pass

def _on_bidask(exchange: Any, bidask: Any) -> None:
    if not self._accepting or loop is None or loop.is_closed():
        return
    self._offer_bidask_threadsafe(bidask)

try:
    api.quote.set_on_bidask_stk_v1_callback(_on_bidask)
except Exception as exc:
    logger.warning("BidAsk callback binding failed: %s", exc)

for symbol, contract in contracts_by_symbol.items():
    try:
        api.quote.subscribe(contract, quote_type=QuoteType.Tick)
    except Exception as exc:
        logger.warning("Tick subscription failed for %s: %s", symbol, exc)
    try:
        api.quote.subscribe(contract, quote_type=QuoteType.BidAsk)
    except Exception as exc:
        logger.warning("BidAsk subscription failed for %s: %s", symbol, exc)
```

Add helper:

```python
def _offer_bidask(self, bidask: Any) -> None:
    symbol = str(getattr(bidask, "code", ""))
    if not symbol:
        return
    self._apply_native_bidask(bidask)

def _offer_bidask_threadsafe(self, bidask: Any) -> None:
    loop = self._loop
    if loop is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(self._offer_bidask, bidask)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q '.\test_sinopac_bridge.py' -k 'subscribes_tick_and_bidask'
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\sinopac_bridge.py E:\claude code test\test_sinopac_bridge.py
git commit -m "feat: subscribe native bidask for quote detail"
```

### Task 3: 將逐筆成交 buffer 與五檔推播全面切到原生來源

**Files:**
- Modify: `E:\claude code test\sinopac_bridge.py`
- Modify: `E:\claude code test\test_sinopac_bridge.py`
- Test: `E:\claude code test\test_sinopac_bridge.py`

- [ ] **Step 1: Write the failing integration-style tests**

在 [E:\claude code test\test_sinopac_bridge.py](E:\claude code test\test_sinopac_bridge.py) 加入兩個測試：

```python
def test_subscribe_quote_detail_sends_native_order_book_snapshot() -> None:
    collector = SinopacCollector(["2330"], api_key="demo", secret_key="demo")
    collector._loop = asyncio.new_event_loop()
    collector._order_book_buffers["2330"] = {
        "timestamp": 1_712_900_000_000,
        "asks": [{"level": 1, "price": 780.0, "volume": 342}],
        "bids": [{"level": 1, "price": 779.0, "volume": 664}],
    }
    websocket = _FakeWebSocket(incoming=['{"type":"subscribe_quote_detail","symbol":"2330"}'])

    try:
        asyncio.run(collector._ws_handler(websocket))
    finally:
        collector._loop.close()

    sent = ''.join(str(payload) for payload in websocket.sent)
    assert '"type":"ORDER_BOOK_SNAPSHOT"' in sent
    assert '"price":780.0' in sent
    assert '"volume":342' in sent


def test_subscribe_quote_detail_sends_empty_order_book_when_native_buffer_missing() -> None:
    collector = SinopacCollector(["2330"], api_key="demo", secret_key="demo")
    collector._loop = asyncio.new_event_loop()
    websocket = _FakeWebSocket(incoming=['{"type":"subscribe_quote_detail","symbol":"2330"}'])

    try:
        asyncio.run(collector._ws_handler(websocket))
    finally:
        collector._loop.close()

    order_book_payloads = [str(payload) for payload in websocket.sent if '"type":"ORDER_BOOK_SNAPSHOT"' in str(payload)]
    assert order_book_payloads
    assert '"asks":[]' in order_book_payloads[0]
    assert '"bids":[]' in order_book_payloads[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q '.\test_sinopac_bridge.py' -k 'native_order_book_snapshot or empty_order_book'
```

Expected:
- FAIL because current implementation still synthesizes asks/bids from price ladder

- [ ] **Step 3: Write minimal implementation**

In [E:\claude code test\sinopac_bridge.py](E:\claude code test\sinopac_bridge.py):

1. Remove `_record_trade_tape(...)` call from `_offer_tick()`

```python
def _offer_tick(self, payload: dict[str, Any]) -> None:
    symbol = str(payload.get("symbol", ""))
    if not symbol:
        self._dropped_ticks += 1
        return
    self._last_tick_monotonic = time.monotonic()
    self._current_ticks[symbol] = payload
    self._dirty_symbols.add(symbol)
    if self._tick_event is not None:
        self._tick_event.set()
```

2. Add native tick recorder used from `_on_tick(...)`

```python
def _record_native_tick_tape(self, tick: Any) -> None:
    symbol = str(getattr(tick, "code", "") or "")
    if not symbol:
        return
    price = float(getattr(tick, "close", None) or getattr(tick, "price", None) or 0.0)
    volume = int(getattr(tick, "volume", None) or getattr(tick, "qty", None) or 0)
    ts_ms = int(time.time() * 1000)
    tick_dt = getattr(tick, "datetime", None)
    if tick_dt is not None:
        try:
            if hasattr(tick_dt, "timestamp"):
                ts_ms = int(tick_dt.timestamp() * 1000)
        except Exception:
            pass
    self._record_trade_tape(symbol, price=price, volume=volume, ts_ms=ts_ms)
```

3. Update `_on_tick(...)` body to record native trade tape before normalizing:

```python
self._record_native_tick_tape(tick)
payload = _normalise_tick(tick, self._market_meta.get(symbol, {}))
```

4. Replace `_build_order_book_snapshot()` synthetic implementation:

```python
def _build_order_book_snapshot(self, symbol: str) -> dict[str, Any]:
    buffer = self._order_book_buffers.get(symbol, {})
    return {
        "type": "ORDER_BOOK_SNAPSHOT",
        "symbol": symbol,
        "timestamp": int(buffer.get("timestamp", time.time() * 1000)),
        "asks": list(buffer.get("asks", [])),
        "bids": list(buffer.get("bids", [])),
    }
```

5. Implement native bidask parser:

```python
def _apply_native_bidask(self, bidask: Any) -> None:
    symbol = str(getattr(bidask, "code", "") or "")
    if not symbol:
        return
    asks = self._extract_bidask_levels(bidask, "ask")
    bids = self._extract_bidask_levels(bidask, "bid")
    if not asks and not bids:
        return
    ts_ms = int(time.time() * 1000)
    raw_dt = getattr(bidask, "datetime", None)
    if raw_dt is not None:
        try:
            if hasattr(raw_dt, "timestamp"):
                ts_ms = int(raw_dt.timestamp() * 1000)
        except Exception:
            pass
    self._order_book_buffers[symbol] = {
        "timestamp": ts_ms,
        "asks": asks,
        "bids": bids,
    }


def _extract_bidask_levels(self, bidask: Any, side: str) -> list[dict[str, Any]]:
    prices = list(getattr(bidask, f"{side}_price", []) or [])
    volumes = list(getattr(bidask, f"{side}_volume", []) or [])
    levels: list[dict[str, Any]] = []
    for index, (price, volume) in enumerate(zip(prices[:5], volumes[:5]), start=1):
        price_value = float(price or 0.0)
        volume_value = int(volume or 0)
        if price_value <= 0:
            continue
        levels.append({
            "level": index,
            "price": round(price_value, 2),
            "volume": volume_value,
        })
    return levels
```

- [ ] **Step 4: Run targeted tests to verify they pass**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q '.\test_sinopac_bridge.py' -k 'native_bidask or native_trade_tape or empty_order_book or subscribes_quote_detail'
```

Expected:
- PASS

- [ ] **Step 5: Run regression verification**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m py_compile '.\run.py' '.\sinopac_bridge.py'
```

Expected:
- Full pytest green
- py_compile green

- [ ] **Step 6: Commit**

```powershell
git add E:\claude code test\sinopac_bridge.py E:\claude code test\test_sinopac_bridge.py
git commit -m "feat: push native sinopac order book and trade tape"
```

### Task 4: 驗證 Flutter 端協議相容性不變

**Files:**
- Read: `E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart`
- Test: `E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart`

- [ ] **Step 1: Run Flutter tests without code changes**

Run:

```powershell
& 'E:\tools\flutter\bin\flutter.bat' test 'test/stock_detail_quote_page_test.dart'
& 'E:\tools\flutter\bin\flutter.bat' analyze
```

Expected:
- PASS without modifying Flutter code

- [ ] **Step 2: Commit if no changes were required**

If no Flutter file changed, skip commit. If a test fixture or contract note needs update:

```powershell
git add E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart
git commit -m "test: verify flutter quote detail contract compatibility"
```


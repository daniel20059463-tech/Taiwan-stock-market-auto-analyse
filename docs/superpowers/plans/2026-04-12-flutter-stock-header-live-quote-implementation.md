# Flutter Stock Detail Header Live Quote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 Flutter 個股詳細報價頁上方 header 的即時價、漲跌、漲跌幅、開高低昨收與總量，改為直接吃現有 Python tick/snapshot 資料流，不再使用頁內 mock summary。

**Architecture:** 不擴充 `quote_detail` 協議，也不新增 HTTP API。Flutter 端在 `paper_trade_gateway.dart` 補一條最小的 live quote stream，直接解析現有 WebSocket 主行情 payload；`stock_detail_quote_page.dart` 訂閱該 stream 後覆蓋 header 狀態，若該 symbol 尚未收到資料則顯示 `--`。

**Tech Stack:** Flutter, Dart, WebSocket, flutter_test

---

### Task 1: 鎖定 header live quote 行為

**Files:**
- Modify: `E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart`
- Modify: `E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart`
- Modify: `E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart`

- [ ] **Step 1: Write the failing tests**

在 `E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart` 新增以下測試與 fake gateway 介面擴充：

```dart
final StreamController<LiveQuoteSnapshot> _liveQuoteController =
    StreamController<LiveQuoteSnapshot>.broadcast();

@override
Stream<LiveQuoteSnapshot> subscribeLiveQuote(String symbol) {
  return _liveQuoteController.stream.where(
    (snapshot) => snapshot.symbol == symbol,
  );
}

void emitLiveQuote(LiveQuoteSnapshot snapshot) {
  _liveQuoteController.add(snapshot);
}
```

```dart
testWidgets('個股頁在沒有即時 quote 時 header 顯示空值', (tester) async {
  final gateway = _FakeGateway();

  addTearDown(gateway.dispose);

  await tester.pumpWidget(
    MaterialApp(
      home: StockDetailQuotePage(
        symbol: '2330',
        name: '台積電',
        gateway: gateway,
      ),
    ),
  );
  await tester.pumpAndSettle();

  expect(find.text('--'), findsWidgets);
});

testWidgets('個股頁收到即時 quote 後 header 會更新', (tester) async {
  final gateway = _FakeGateway();

  addTearDown(gateway.dispose);

  await tester.pumpWidget(
    MaterialApp(
      home: StockDetailQuotePage(
        symbol: '2330',
        name: '台積電',
        gateway: gateway,
      ),
    ),
  );
  await tester.pumpAndSettle();

  gateway.emitLiveQuote(
    const LiveQuoteSnapshot(
      symbol: '2330',
      price: 780.0,
      previousClose: 770.0,
      open: 772.0,
      high: 785.0,
      low: 768.0,
      totalVolume: 34500,
      changePct: 1.30,
    ),
  );
  await tester.pump();

  expect(find.text('780.00'), findsOneWidget);
  expect(find.text('+10.00'), findsOneWidget);
  expect(find.text('+1.30%'), findsOneWidget);
  expect(find.text('772.00'), findsOneWidget);
  expect(find.text('785.00'), findsOneWidget);
  expect(find.text('768.00'), findsOneWidget);
  expect(find.text('770.00'), findsOneWidget);
  expect(find.text('34500'), findsOneWidget);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart
```

Expected:
- FAIL because `LiveQuoteSnapshot` and `subscribeLiveQuote()` do not exist yet
- FAIL because header still reads mock summary

- [ ] **Step 3: Write minimal implementation hooks**

在 `E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart` 加入最小型別與介面：

```dart
class LiveQuoteSnapshot {
  const LiveQuoteSnapshot({
    required this.symbol,
    required this.price,
    required this.previousClose,
    required this.open,
    required this.high,
    required this.low,
    required this.totalVolume,
    required this.changePct,
  });

  final String symbol;
  final double price;
  final double previousClose;
  final double open;
  final double high;
  final double low;
  final int totalVolume;
  final double changePct;
}
```

```dart
abstract class PaperTradeGateway {
  Stream<LiveQuoteSnapshot> subscribeLiveQuote(String symbol);
  Stream<OrderBookSnapshot> subscribeOrderBook(String symbol);
  Stream<TradeTapeSnapshot> subscribeTradeTape(String symbol);
  Future<void> unsubscribeQuoteDetail(String symbol);
  Future<List<IntradayTrendPoint>> loadIntradayTrend(String symbol);
  Future<PaperTradeResult> submitManualTrade({
    required String symbol,
    required String action,
    required int shares,
  });
}
```

在 `E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart` 補 state hook：

```dart
LiveQuoteSnapshot? _liveQuote;
StreamSubscription<LiveQuoteSnapshot>? _liveQuoteSubscription;
```

- [ ] **Step 4: Run test to verify it still fails for the right reason**

Run:

```powershell
E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart
```

Expected:
- FAIL only because `StockDetailQuotePage` still has not subscribed to live quote or rendered it

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart
git commit -m "test: lock stock detail header live quote behavior"
```

### Task 2: 在 gateway 接入現有 quote snapshot stream

**Files:**
- Modify: `E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart`
- Test: `E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart`

- [ ] **Step 1: Re-run the focused widget test to confirm the current failure**

Run:

```powershell
E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart
```

Expected:
- FAIL because `WsPaperTradeGateway` does not implement `subscribeLiveQuote`

- [ ] **Step 2: Write minimal implementation**

在 `E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart` 補 live quote socket 狀態：

```dart
WebSocket? _liveQuoteSocket;
StreamController<LiveQuoteSnapshot>? _liveQuoteController;
Future<void>? _connectingLiveQuote;
```

實作訂閱方法：

```dart
@override
Stream<LiveQuoteSnapshot> subscribeLiveQuote(String symbol) {
  _liveQuoteController ??= StreamController<LiveQuoteSnapshot>.broadcast();
  unawaited(_ensureLiveQuoteSocket());
  return _liveQuoteController!.stream.where(
    (snapshot) => snapshot.symbol == symbol,
  );
}
```

實作連線與監聽：

```dart
Future<void> _ensureLiveQuoteSocket() async {
  if (_liveQuoteSocket != null) return;
  if (_connectingLiveQuote != null) {
    await _connectingLiveQuote;
    return;
  }
  _connectingLiveQuote = _openLiveQuoteSocket();
  try {
    await _connectingLiveQuote;
  } finally {
    _connectingLiveQuote = null;
  }
}

Future<void> _openLiveQuoteSocket() async {
  final socket = await WebSocket.connect(endpoint).timeout(timeout);
  _liveQuoteSocket = socket;
  _liveQuoteController ??= StreamController<LiveQuoteSnapshot>.broadcast();
  unawaited(_listenLiveQuoteSocket(socket));
}
```

```dart
Future<void> _listenLiveQuoteSocket(WebSocket socket) async {
  try {
    await for (final raw in socket.timeout(timeout)) {
      if (raw is! String) continue;
      final decoded = jsonDecode(raw);
      if (decoded is List) {
        for (final item in decoded.whereType<Map>()) {
          final snapshot =
              _tryParseLiveQuoteSnapshot(Map<String, dynamic>.from(item));
          if (snapshot != null) {
            _liveQuoteController?.add(snapshot);
          }
        }
      } else if (decoded is Map<String, dynamic>) {
        final snapshot = _tryParseLiveQuoteSnapshot(
          Map<String, dynamic>.from(decoded),
        );
        if (snapshot != null) {
          _liveQuoteController?.add(snapshot);
        }
      }
    }
  } on TimeoutException {
    await _closeLiveQuoteSocket();
  }
}
```

Parser 最小版本：

```dart
LiveQuoteSnapshot? _tryParseLiveQuoteSnapshot(Map<String, dynamic> json) {
  final symbol = json['symbol'] as String?;
  final price = (json['price'] as num?)?.toDouble();
  if (symbol == null || price == null) {
    return null;
  }
  return LiveQuoteSnapshot(
    symbol: symbol,
    price: price,
    previousClose: (json['previousClose'] as num?)?.toDouble() ?? 0,
    open: (json['open'] as num?)?.toDouble() ?? 0,
    high: (json['high'] as num?)?.toDouble() ?? 0,
    low: (json['low'] as num?)?.toDouble() ?? 0,
    totalVolume: (json['totalVolume'] as num?)?.toInt() ?? 0,
    changePct: (json['changePct'] as num?)?.toDouble() ?? 0,
  );
}
```

- [ ] **Step 3: Run test to verify the gateway contract is now sufficient**

Run:

```powershell
E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart
```

Expected:
- FAIL only because the page still renders mock summary instead of `_liveQuote`

- [ ] **Step 4: Commit**

```powershell
git add E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart
git commit -m "feat: add live quote stream to flutter gateway"
```

### Task 3: 讓個股 header 直接顯示 live quote

**Files:**
- Modify: `E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart`
- Test: `E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart`

- [ ] **Step 1: Subscribe to live quote in initState**

在 `initState()` 中加入：

```dart
@override
void initState() {
  super.initState();
  _gateway = widget.gateway ?? WsPaperTradeGateway();
  _dailyBars = _mockDailyBars();
  _loadIntradayTrend();
  _subscribeQuoteDetail();
  _subscribeLiveQuote();
}

void _subscribeLiveQuote() {
  _liveQuoteSubscription =
      _gateway.subscribeLiveQuote(widget.symbol).listen((snapshot) {
    if (!mounted) {
      return;
    }
    setState(() {
      _liveQuote = snapshot;
    });
  });
}
```

- [ ] **Step 2: Replace mock summary rendering**

將 header 所需資料改由 `_liveQuote` 計算，不再依賴 `_mockSummary()`。

在頁面 class 中加入：

```dart
double? get _changeValue {
  final quote = _liveQuote;
  if (quote == null) return null;
  return quote.price - quote.previousClose;
}

String _formatPrice(double? value) => value == null ? '--' : value.toStringAsFixed(2);

String _formatSigned(double? value) {
  if (value == null) return '--';
  final prefix = value > 0 ? '+' : '';
  return '$prefix${value.toStringAsFixed(2)}';
}

String _formatPct(double? value) {
  if (value == null) return '--';
  final prefix = value > 0 ? '+' : '';
  return '$prefix${value.toStringAsFixed(2)}%';
}
```

將 `_StockDetailHeaderSection` 的輸入改為 live values：

```dart
_StockDetailHeaderSection(
  key: const Key('stock-detail-header'),
  symbol: widget.symbol,
  name: widget.name,
  lastPriceText: _formatPrice(_liveQuote?.price),
  changeText: _formatSigned(_changeValue),
  changePctText: _formatPct(_liveQuote?.changePct),
  openText: _formatPrice(_liveQuote?.open),
  highText: _formatPrice(_liveQuote?.high),
  lowText: _formatPrice(_liveQuote?.low),
  previousCloseText: _formatPrice(_liveQuote?.previousClose),
  volumeText: _liveQuote == null ? '--' : _liveQuote!.totalVolume.toString(),
  tone: _tone(_changeValue ?? 0),
)
```

Header widget 調整成單純顯示字串，不再吃 `_QuoteSummary`：

```dart
class _StockDetailHeaderSection extends StatelessWidget {
  const _StockDetailHeaderSection({
    super.key,
    required this.symbol,
    required this.name,
    required this.lastPriceText,
    required this.changeText,
    required this.changePctText,
    required this.openText,
    required this.highText,
    required this.lowText,
    required this.previousCloseText,
    required this.volumeText,
    required this.tone,
  });
```

- [ ] **Step 3: Dispose the subscription**

在 `dispose()` 補上：

```dart
@override
void dispose() {
  _liveQuoteSubscription?.cancel();
  _orderBookSubscription?.cancel();
  _tradeTapeSubscription?.cancel();
  unawaited(_gateway.unsubscribeQuoteDetail(widget.symbol));
  super.dispose();
}
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart
```

Expected:
- PASS

- [ ] **Step 5: Commit**

```powershell
git add E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart
git commit -m "feat: render stock detail header from live quotes"
```

### Task 4: Full Flutter verification

**Files:**
- Verify only: `E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart`
- Verify only: `E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart`
- Verify only: `E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart`

- [ ] **Step 1: Run full test suite**

Run:

```powershell
E:\tools\flutter\bin\flutter.bat test
```

Expected:
- `All tests passed!`

- [ ] **Step 2: Run analyzer**

Run:

```powershell
E:\tools\flutter\bin\flutter.bat analyze
```

Expected:
- `No issues found!`

- [ ] **Step 3: Commit verification-safe cleanups if needed**

If analyzer/test required tiny cleanup changes:

```powershell
git add E:\claude code test\flutter_app
git commit -m "chore: polish flutter stock detail live quote integration"
```

If no cleanup was needed, skip this commit.

- [ ] **Step 4: Manual verification note**

確認以下行為在 code review 中可被快速檢查：
- header 無 snapshot 時顯示 `--`
- 收到 snapshot 後即時價/漲跌/漲跌幅/開高低昨收量同步更新
- `走勢圖 / 五檔 / 明細 / 買賣` 原功能未退化


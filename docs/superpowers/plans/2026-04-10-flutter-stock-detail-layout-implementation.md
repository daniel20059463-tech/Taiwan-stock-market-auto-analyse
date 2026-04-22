# Flutter 個股詳細報價頁版面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 Flutter 個股詳細報價頁重排為四段式固定版面，包含 Header、主視覺功能切換區、五檔/分時明細雙欄，以及固定底部操作列。

**Architecture:** 保留既有 mock 資料與 K 線元件，只重做頁面容器與區塊分配。頁面以 `LayoutBuilder + Column` 為骨架，透過比例優先與最小高度保護控制各區塊高度，中段與下段內容不足時採內部捲動，不讓整頁變成長頁。

**Tech Stack:** Flutter、flutter_test、Material 3、既有 `StockKChartPanel`

---

### Task 1: 建立四段式頁面骨架與高度分配

**Files:**
- Modify: `flutter_app/lib/pages/stock_detail_quote_page.dart`
- Test: `flutter_app/test/stock_detail_quote_page_test.dart`

- [ ] **Step 1: 寫一個失敗測試，驗證頁面存在四個主要區塊**

```dart
testWidgets('個股詳細頁包含 Header、功能切換區、報價區與底部操作列', (tester) async {
  await tester.pumpWidget(
    const MaterialApp(
      home: StockDetailQuotePage(symbol: '2330', name: '台積電'),
    ),
  );

  expect(find.byKey(const Key('stock-detail-header')), findsOneWidget);
  expect(find.byKey(const Key('stock-detail-chart-tabs')), findsOneWidget);
  expect(find.byKey(const Key('stock-detail-quote-panels')), findsOneWidget);
  expect(find.byKey(const Key('stock-detail-action-bar')), findsOneWidget);
});
```

- [ ] **Step 2: 跑測試確認先失敗**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

Expected: FAIL，因為目前頁面尚未標記這四個新區塊

- [ ] **Step 3: 以最小改動重排頁面骨架**

實作重點：
- 用 `LayoutBuilder` 計算可用高度
- 建立四段高度 helper
- 產出：
  - `Key('stock-detail-header')`
  - `Key('stock-detail-chart-tabs')`
  - `Key('stock-detail-quote-panels')`
  - `Key('stock-detail-action-bar')`

- [ ] **Step 4: 重跑測試確認轉綠**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

Expected: PASS

### Task 2: 完成 Header 區與主視覺功能切換區

**Files:**
- Modify: `flutter_app/lib/pages/stock_detail_quote_page.dart`
- Test: `flutter_app/test/stock_detail_quote_page_test.dart`

- [ ] **Step 1: 寫失敗測試，驗證 Header 與 Tab 切換區內容**

```dart
testWidgets('Header 顯示成交價與基本欄位，主視覺區包含三個 tab', (tester) async {
  await tester.pumpWidget(
    const MaterialApp(
      home: StockDetailQuotePage(symbol: '2330', name: '台積電'),
    ),
  );

  expect(find.text('2330 台積電'), findsOneWidget);
  expect(find.text('504.00'), findsWidgets);
  expect(find.text('開'), findsOneWidget);
  expect(find.text('高'), findsOneWidget);
  expect(find.text('低'), findsOneWidget);
  expect(find.text('收'), findsOneWidget);
  expect(find.text('量'), findsOneWidget);
  expect(find.text('走勢圖'), findsOneWidget);
  expect(find.text('K線圖'), findsOneWidget);
  expect(find.text('技術指標'), findsOneWidget);
});
```

- [ ] **Step 2: 跑測試確認先失敗**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

Expected: FAIL，因為目前沒有新的 tab 結構與標準欄位標籤

- [ ] **Step 3: 實作 Header 與主視覺區**

實作重點：
- Header 第一列：名稱/代號、超大成交價、漲跌與漲跌幅
- Header 第二列：開高低收量
- 主視覺區上方 `TabBar`
- 主視覺區下方 `TabBarView`
  - 走勢圖：先用 placeholder 容器
  - K線圖：接既有 `StockKChartPanel`
  - 技術指標：先用 placeholder 容器

- [ ] **Step 4: 重跑測試確認轉綠**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

Expected: PASS

### Task 3: 完成下段報價區左右雙欄

**Files:**
- Modify: `flutter_app/lib/pages/stock_detail_quote_page.dart`
- Test: `flutter_app/test/stock_detail_quote_page_test.dart`

- [ ] **Step 1: 寫失敗測試，驗證五檔與分時明細各自存在**

```dart
testWidgets('下段報價區左右平分顯示最佳五檔與分時明細', (tester) async {
  await tester.pumpWidget(
    const MaterialApp(
      home: StockDetailQuotePage(symbol: '2330', name: '台積電'),
    ),
  );

  expect(find.text('最佳五檔'), findsOneWidget);
  expect(find.text('分時明細'), findsOneWidget);
  expect(find.text('賣1'), findsOneWidget);
  expect(find.text('買1'), findsOneWidget);
  expect(find.text('13:29:58'), findsOneWidget);
});
```

- [ ] **Step 2: 跑測試確認先失敗**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

Expected: FAIL，因為目前標題與結構不符合新規格

- [ ] **Step 3: 重寫報價區為左右各半**

實作重點：
- `Row` 中兩個 `Expanded`
- 左：`最佳五檔`
  - 上賣五檔、下買五檔
- 右：`分時明細`
  - `ListView` 顯示逐筆成交
- 兩側區塊各自可內部捲動

- [ ] **Step 4: 重跑測試確認轉綠**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

Expected: PASS

### Task 4: 完成底部操作列與整體驗證

**Files:**
- Modify: `flutter_app/lib/pages/stock_detail_quote_page.dart`
- Create: `flutter_app/test/stock_detail_quote_page_test.dart`

- [ ] **Step 1: 寫失敗測試，驗證底部操作列固定存在**

```dart
testWidgets('底部操作列顯示買進、賣出與常用操作 icon', (tester) async {
  await tester.pumpWidget(
    const MaterialApp(
      home: StockDetailQuotePage(symbol: '2330', name: '台積電'),
    ),
  );

  expect(find.text('買進'), findsOneWidget);
  expect(find.text('賣出'), findsOneWidget);
  expect(find.byIcon(Icons.star_border), findsOneWidget);
  expect(find.byIcon(Icons.notifications_none), findsOneWidget);
});
```

- [ ] **Step 2: 跑測試確認先失敗**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

Expected: FAIL，因為目前沒有新的 Action Bar

- [ ] **Step 3: 實作固定底部操作列**

實作重點：
- 左側：
  - 自選 icon
  - 警示 icon
- 右側：
  - 紅色 `買進`
  - 綠色 `賣出`
- 固定於頁面最下方

- [ ] **Step 4: 跑完整 Flutter 驗證**

Run:
- `E:\tools\flutter\bin\flutter.bat analyze`
- `E:\tools\flutter\bin\flutter.bat test`

Expected:
- `No issues found!`
- `All tests passed!`

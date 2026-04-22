# Flutter Watchlist Flash Cells Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將自選股 Data Grid 的閃爍動畫正式接入 `成交 / 漲跌 / 幅度%` 三個欄位，並維持其他欄位靜態。

**Architecture:** 先用 widget test 鎖定欄位責任，再以最小修改方式讓 `StockDataGrid` 只在三個即時價格欄位使用 `PriceFlashCell`。`PriceFlashCell` 只補足與正式表格一致的高度與邊框，不改動畫規則。

**Tech Stack:** Flutter、flutter_test、Material 3、自訂 StatefulWidget 動畫元件

---

### Task 1: 為閃爍欄位寫失敗測試

**Files:**
- Modify: `flutter_app/test/stock_data_grid_test.dart`
- Test: `flutter_app/test/stock_data_grid_test.dart`

- [ ] **Step 1: 寫一個新 widget test，驗證只有三個欄位使用 `PriceFlashCell`**

```dart
testWidgets('成交、漲跌、幅度欄位使用閃爍元件，其餘欄位維持靜態', (tester) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: StockDataGrid(
          stocks: [
            StockModel(
              symbol: '2330',
              name: '台積電',
              price: 780,
              change: 15,
              changeRate: 1.96,
              volume: 34500,
              high: 785,
              low: 765,
            ),
          ],
        ),
      ),
    ),
  );

  expect(find.byType(PriceFlashCell), findsNWidgets(3));
  expect(find.text('34500'), findsOneWidget);
  expect(find.text('785.00'), findsOneWidget);
  expect(find.text('765.00'), findsOneWidget);
});
```

- [ ] **Step 2: 跑測試確認它先失敗**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_data_grid_test.dart`

Expected: FAIL，因為目前 `StockDataGrid` 尚未使用 `PriceFlashCell`

### Task 2: 用最小修改讓測試轉綠

**Files:**
- Modify: `flutter_app/lib/widgets/stock_data_grid.dart`
- Modify: `flutter_app/lib/widgets/price_flash_cell.dart`
- Test: `flutter_app/test/stock_data_grid_test.dart`

- [ ] **Step 1: 在 `PriceFlashCell` 補高度與邊框參數，讓它能無縫替代正式表格 cell**

```dart
const PriceFlashCell({
  super.key,
  required this.numericValue,
  required this.displayText,
  required this.width,
  this.height = 52,
  this.textColor,
  this.alignment = Alignment.centerRight,
  this.decoration,
});
```

- [ ] **Step 2: 在 `StockDataGrid` 只將三個即時價格欄位改用 `PriceFlashCell`**

```dart
PriceFlashCell(
  numericValue: stock.price,
  displayText: stock.price.toStringAsFixed(2),
  width: dataCellWidth,
  height: rowHeight,
  textColor: _resolveTrendColor(stock),
  decoration: _cellDecoration,
)
```

其餘三欄維持：

```dart
_buildDataCell(stock.volume.toString(), width: dataCellWidth)
```

- [ ] **Step 3: 重跑單測確認轉綠**

Run: `E:\tools\flutter\bin\flutter.bat test test/stock_data_grid_test.dart`

Expected: PASS

### Task 3: 跑完整 Flutter 驗證

**Files:**
- Modify: `flutter_app/test/stock_data_grid_test.dart`
- Modify: `flutter_app/lib/widgets/stock_data_grid.dart`
- Modify: `flutter_app/lib/widgets/price_flash_cell.dart`

- [ ] **Step 1: 跑 Flutter analyze**

Run: `E:\tools\flutter\bin\flutter.bat analyze`

Expected: `No issues found!`

- [ ] **Step 2: 跑完整 Flutter tests**

Run: `E:\tools\flutter\bin\flutter.bat test`

Expected: `All tests passed!`

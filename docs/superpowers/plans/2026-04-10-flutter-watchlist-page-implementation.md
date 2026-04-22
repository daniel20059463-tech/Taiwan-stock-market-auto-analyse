# Flutter 自選股頁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一個深色模式、高資訊密度的 Flutter 自選股頁面，支援分組切換、固定左欄、右側可水平滑動報價欄位、列點擊跳轉，以及紅漲綠跌閃爍動畫。

**Architecture:** 採用自訂 Grid 結構而非 Flutter `DataTable`。頁面由群組 tabs、固定左欄與可水平滑動右欄組成，右側欄位透過共享 scroll controller 保持一致；單格報價更新閃爍由專用 cell 元件處理。

**Tech Stack:** Flutter、Dart、Material 3、AnimatedContainer / TweenAnimationBuilder、Navigator

---

### Task 1: 建立資料模型與頁面骨架

**Files:**
- Create: `flutter_app/lib/models/watchlist_quote_row.dart`
- Create: `flutter_app/lib/models/watchlist_group.dart`
- Create: `flutter_app/lib/pages/watchlist_page.dart`

- [ ] **Step 1: 建立資料模型**

```dart
class WatchlistQuoteRow {
  const WatchlistQuoteRow({
    required this.symbol,
    required this.name,
    required this.lastPrice,
    required this.change,
    required this.changePercent,
    required this.totalVolume,
    required this.high,
    required this.low,
  });

  final String symbol;
  final String name;
  final double lastPrice;
  final double change;
  final double changePercent;
  final int totalVolume;
  final double high;
  final double low;
}
```

```dart
import 'watchlist_quote_row.dart';

class WatchlistGroup {
  const WatchlistGroup({
    required this.id,
    required this.name,
    required this.items,
  });

  final String id;
  final String name;
  final List<WatchlistQuoteRow> items;
}
```

- [ ] **Step 2: 建立頁面骨架**

```dart
import 'package:flutter/material.dart';

class WatchlistPage extends StatelessWidget {
  const WatchlistPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: Color(0xFF0D0F14),
      body: SafeArea(
        child: Center(
          child: Text(
            '自選股頁施工中',
            style: TextStyle(color: Colors.white),
          ),
        ),
      ),
    );
  }
}
```

- [ ] **Step 3: 確認可編譯**

Run: `flutter analyze`
Expected: 無 error

- [ ] **Step 4: Commit**

```bash
git add flutter_app/lib/models/watchlist_quote_row.dart flutter_app/lib/models/watchlist_group.dart flutter_app/lib/pages/watchlist_page.dart
git commit -m "feat: add flutter watchlist page skeleton"
```

### Task 2: 建立分組 tabs 與頁面狀態

**Files:**
- Create: `flutter_app/lib/widgets/watchlist_group_tabs.dart`
- Modify: `flutter_app/lib/pages/watchlist_page.dart`

- [ ] **Step 1: 建立分組 tabs 元件**

```dart
import 'package:flutter/material.dart';

class WatchlistGroupTabs extends StatelessWidget {
  const WatchlistGroupTabs({
    super.key,
    required this.groups,
    required this.activeGroupId,
    required this.onChanged,
  });

  final List<(String id, String label)> groups;
  final String activeGroupId;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 44,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        itemBuilder: (context, index) {
          final group = groups[index];
          final selected = group.$1 == activeGroupId;
          return GestureDetector(
            onTap: () => onChanged(group.$1),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                color: selected ? const Color(0xFF1D2733) : const Color(0xFF141A22),
                border: Border.all(
                  color: selected ? const Color(0xFF2EB6FF) : const Color(0xFF2A313B),
                ),
              ),
              child: Center(
                child: Text(
                  group.$2,
                  style: TextStyle(
                    color: selected ? const Color(0xFF2EB6FF) : Colors.white,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
          );
        },
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemCount: groups.length,
      ),
    );
  }
}
```

- [ ] **Step 2: 將 tabs 接進頁面**

在 `WatchlistPage` 改成 `StatefulWidget`，並建立：

```dart
String activeGroupId = 'watch-1';
```

以及假資料：

```dart
final groups = [
  const ('watch-1', '自選一'),
  const ('watch-2', '自選二'),
];
```

- [ ] **Step 3: 驗證分組切換**

Run: `flutter run`
Expected: 頂部可看到 `自選一 / 自選二`

- [ ] **Step 4: Commit**

```bash
git add flutter_app/lib/widgets/watchlist_group_tabs.dart flutter_app/lib/pages/watchlist_page.dart
git commit -m "feat: add watchlist group tabs"
```

### Task 3: 建立固定左欄與可水平滑動報價欄

**Files:**
- Create: `flutter_app/lib/widgets/watchlist_grid.dart`
- Create: `flutter_app/lib/widgets/watchlist_row.dart`
- Modify: `flutter_app/lib/pages/watchlist_page.dart`

- [ ] **Step 1: 建立 Grid 容器**

`watchlist_grid.dart` 需包含：
- 表頭
- 左側固定名稱欄
- 右側水平滑動欄

右欄欄位固定為：

```dart
const columns = ['成交價', '漲跌', '幅度', '總量', '最高', '最低'];
```

- [ ] **Step 2: 建立單列元件**

`watchlist_row.dart` 需支援：
- 左側顯示 `name + symbol`
- 右側顯示 6 個欄位
- 點擊整列觸發 `onTap`

- [ ] **Step 3: 用共享 horizontal controller 做右側同步滑動**

Grid 內部應維持：

```dart
final ScrollController horizontalController = ScrollController();
```

並讓表頭與內容共用。

- [ ] **Step 4: 將 Grid 接進頁面**

頁面主體改為：

```dart
Expanded(
  child: WatchlistGrid(...),
)
```

- [ ] **Step 5: 驗證左右欄結構**

Run: `flutter run`
Expected:
- 左側名稱欄固定
- 右側欄位可水平滑動

- [ ] **Step 6: Commit**

```bash
git add flutter_app/lib/widgets/watchlist_grid.dart flutter_app/lib/widgets/watchlist_row.dart flutter_app/lib/pages/watchlist_page.dart
git commit -m "feat: add watchlist data grid layout"
```

### Task 4: 實作漲跌顏色與閃爍動畫

**Files:**
- Create: `flutter_app/lib/widgets/price_flash_cell.dart`
- Modify: `flutter_app/lib/widgets/watchlist_row.dart`

- [ ] **Step 1: 建立閃爍 cell**

`price_flash_cell.dart` 應包含：

```dart
class PriceFlashCell extends StatefulWidget {
  const PriceFlashCell({
    super.key,
    required this.value,
    required this.text,
    this.alignment = Alignment.centerRight,
  });

  final double value;
  final String text;
  final Alignment alignment;
}
```

更新邏輯：
- 新值 > 舊值：背景暫時紅色
- 新值 < 舊值：背景暫時綠色
- 約 400ms 淡回原背景

- [ ] **Step 2: 套用到報價欄位**

至少以下欄位使用 `PriceFlashCell`：
- 成交價
- 漲跌
- 幅度

- [ ] **Step 3: 套用台股顏色規則**

```dart
Color priceColor(double value) {
  if (value > 0) return const Color(0xFFFF4D4F);
  if (value < 0) return const Color(0xFF19C37D);
  return Colors.white;
}
```

- [ ] **Step 4: 驗證動畫**

Run: `flutter run`
Expected:
- 模擬資料更新時，漲閃紅、跌閃綠

- [ ] **Step 5: Commit**

```bash
git add flutter_app/lib/widgets/price_flash_cell.dart flutter_app/lib/widgets/watchlist_row.dart
git commit -m "feat: add quote flash animation"
```

### Task 5: 加入列點擊跳轉到個股詳細報價頁

**Files:**
- Create: `flutter_app/lib/pages/stock_detail_quote_page.dart`
- Modify: `flutter_app/lib/widgets/watchlist_row.dart`
- Modify: `flutter_app/lib/pages/watchlist_page.dart`

- [ ] **Step 1: 建立詳細頁占位版本**

```dart
class StockDetailQuotePage extends StatelessWidget {
  const StockDetailQuotePage({
    super.key,
    required this.symbol,
    required this.name,
  });

  final String symbol;
  final String name;
}
```

- [ ] **Step 2: 接入 Navigator.push**

當點擊 `WatchlistRow` 時：

```dart
Navigator.of(context).push(
  MaterialPageRoute(
    builder: (_) => StockDetailQuotePage(
      symbol: row.symbol,
      name: row.name,
    ),
  ),
);
```

- [ ] **Step 3: 驗證導頁**

Run: `flutter run`
Expected:
- 點擊任一列可跳到個股詳細報價頁

- [ ] **Step 4: Commit**

```bash
git add flutter_app/lib/pages/stock_detail_quote_page.dart flutter_app/lib/widgets/watchlist_row.dart flutter_app/lib/pages/watchlist_page.dart
git commit -m "feat: add watchlist row navigation"
```

### Task 6: 收尾與驗證

**Files:**
- Verify: `flutter_app/lib/models/watchlist_quote_row.dart`
- Verify: `flutter_app/lib/models/watchlist_group.dart`
- Verify: `flutter_app/lib/pages/watchlist_page.dart`
- Verify: `flutter_app/lib/pages/stock_detail_quote_page.dart`
- Verify: `flutter_app/lib/widgets/watchlist_group_tabs.dart`
- Verify: `flutter_app/lib/widgets/watchlist_grid.dart`
- Verify: `flutter_app/lib/widgets/watchlist_row.dart`
- Verify: `flutter_app/lib/widgets/price_flash_cell.dart`

- [ ] **Step 1: 跑靜態檢查**

Run: `flutter analyze`
Expected: 無 error

- [ ] **Step 2: 跑格式化**

Run: `dart format flutter_app/lib`
Expected: 全部格式化成功

- [ ] **Step 3: 手動驗證**

確認：
- 分組 tabs 可切換
- 左欄固定
- 右欄可左右滑動
- 點列可跳頁
- 漲跌閃爍正常
- 深色高密度排版可讀

- [ ] **Step 4: Commit**

```bash
git add flutter_app/lib
git commit -m "feat: implement flutter watchlist page"
```


# Flutter 自選股頁設計

日期：2026-04-10

## 目標

設計一個類似台股看盤 App 的「自選股」頁面，特性如下：

- 深色模式、高資訊密度
- 頂部有分組切換，例如「自選一」、「自選二」
- 表格左側固定顯示「商品名稱 / 代號」
- 右側欄位可水平滑動，包含：
  - 成交價
  - 漲跌
  - 幅度
  - 總量
  - 最高
  - 最低
- 點擊商品列可進入「個股詳細報價」頁
- 報價更新時，欄位背景短暫閃爍：
  - 上漲：紅色閃爍
  - 下跌：綠色閃爍

## 技術選型

- 框架：Flutter
- 狀態管理：先以頁面內 state 或簡單 provider 模式為主，不在第一版引入重量級架構
- 清單呈現：自訂 Grid，而非 `DataTable`
- 動畫：`AnimatedContainer` 或 `TweenAnimationBuilder`

## 為什麼不用 DataTable

Flutter 內建 `DataTable` 不適合這個場景，原因如下：

- 不容易做固定左欄
- 不容易做整塊右側欄位水平同步滑動
- 單格更新閃爍動畫控制較差
- 高密度金融表格的樣式自由度不足

因此第一版採用：

- 左側固定欄
- 右側水平可滑欄位
- 每列自訂 widget

## 頁面結構

### 1. 頂部分組列

元件：`WatchlistGroupTabs`

用途：

- 顯示自選群組
- 切換目前顯示的自選股清單

建議顯示：

- 自選一
- 自選二
- 自選三

行為：

- 點擊群組後更新下方列表
- 選中的群組使用高對比高亮

### 2. 表格主體

元件：`WatchlistGrid`

結構：

- 左側固定欄：`WatchlistFixedColumn`
- 右側可滑動欄：`WatchlistScrollableColumns`

#### 左側固定欄

欄位內容：

- 商品名稱
- 商品代號

特性：

- 不隨水平滑動移動
- 點擊整列可進入個股頁

#### 右側滑動欄

欄位順序：

- 成交價
- 漲跌
- 幅度
- 總量
- 最高
- 最低

特性：

- 整塊欄位可左右滑動
- 所有列共用同一個水平捲動位置

### 3. 單列元件

元件：`WatchlistRow`

包含：

- `WatchlistFixedCell`
- 多個 `WatchlistQuoteCell`

功能：

- 點擊整列觸發導頁
- 根據報價變動決定顏色與閃爍狀態

## 資料模型

```dart
class WatchlistQuoteRow {
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

群組模型：

```dart
class WatchlistGroup {
  final String id;
  final String name;
  final List<WatchlistQuoteRow> items;
}
```

## 動畫設計

元件：`PriceFlashCell`

行為：

- 若新值 > 舊值：背景閃紅
- 若新值 < 舊值：背景閃綠
- 若相同：不閃

動畫時長：

- 建議 300ms 到 500ms

實作方式：

- Cell 持有前一次數值
- 接收到新值時比較差異
- 更新暫時背景色
- 用動畫淡回原始背景

## 視覺規範

- 背景：深色
- 邊框：低對比細線
- 文字：高對比淺色
- 上漲：紅色
- 下跌：綠色
- 平盤：白色或黃色
- 數字：等寬字體，避免跳動
- 行高：緊湊，但仍保留可點擊性

## 導頁行為

點擊列後：

- 使用 `Navigator.push`
- 導向 `StockDetailQuotePage`
- 傳入：
  - `symbol`
  - `name`

## 第一版範圍

本次只做：

- 自選群組 tabs
- 固定左欄 + 右側水平滑動欄位
- 列點擊跳轉
- 報價漲跌顏色
- 報價更新閃爍動畫

本次不做：

- 群組管理
- 拖曳排序
- 欄位自訂顯示/隱藏
- 五檔、分時圖嵌入列表
- 後端即時資料接線

## 建議檔案拆分

- `watchlist_page.dart`
- `widgets/watchlist_group_tabs.dart`
- `widgets/watchlist_grid.dart`
- `widgets/watchlist_row.dart`
- `widgets/price_flash_cell.dart`
- `models/watchlist_quote_row.dart`


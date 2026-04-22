# Flutter 自選股報價閃爍動畫設計

日期：2026-04-10

## 目標

在 Flutter 自選股列表的正式版 `Data Grid` 中，替即時報價核心欄位加入短暫閃爍動畫：

- 成交
- 漲跌
- 幅度%

其餘欄位先維持靜態更新：

- 總量
- 最高
- 最低

此變更只作用於：

- `flutter_app/lib/widgets/stock_data_grid.dart`
- `flutter_app/lib/widgets/price_flash_cell.dart`

不變更頁面路由、資料模型欄位定義、Tabs、Top Bar 與其他頁面。

## 設計選項

### 方案 A：所有數值欄位都閃爍

優點：
- 實作一致
- 不需要區分欄位類型

缺點：
- `總量 / 最高 / 最低` 更新頻率高時會造成視覺噪音
- 對看盤者不友善，焦點會被大量次要資訊打散

### 方案 B：只讓核心即時欄位閃爍

閃爍欄位：
- 成交
- 漲跌
- 幅度%

非閃爍欄位：
- 總量
- 最高
- 最低

優點：
- 只強調最重要的價格變化
- 視覺噪音低
- 保留高密度看盤可讀性

缺點：
- 欄位行為不完全一致

### 推薦方案

採用 **方案 B**。

原因：
- 最符合股票看盤實務
- 不會讓整張表過度閃動
- 後續若要擴充，可再把 `總量` 納入

## 行為規格

### 觸發條件

當同一個 cell 的 `numericValue` 與前一次不同時：

- 新值 > 舊值：背景短暫閃紅
- 新值 < 舊值：背景短暫閃綠
- 新值 == 舊值：不閃爍

### 動畫規則

- 閃爍色：
  - 上漲：`AppColors.upRed` 的低透明度背景
  - 下跌：`AppColors.downGreen` 的低透明度背景
- 顯示時間：約 `420ms`
- 淡出時間：約 `220ms`
- 動畫完成後恢復透明背景

### 欄位套用規則

`StockDataGrid` 中：

- `成交`：使用 `PriceFlashCell`
- `漲跌`：使用 `PriceFlashCell`
- `幅度%`：使用 `PriceFlashCell`
- `總量 / 最高 / 最低`：維持一般靜態 `Container + Text`

## 元件邊界

### `PriceFlashCell`

責任：
- 比較新舊 `numericValue`
- 決定閃紅或閃綠
- 在動畫結束後清空背景

不負責：
- 決定欄位是否需要閃爍
- 整列資料格式化

### `StockDataGrid`

責任：
- 決定哪些欄位使用 `PriceFlashCell`
- 決定哪些欄位維持靜態 rendering
- 保持現有表格欄寬與對齊規格：
  - 左欄 `104`
  - 數值欄 `84`
  - 列高 `52`
  - 表頭高 `36`

## 測試策略

### 新增測試

在 Flutter widget test 中新增一個最小測試：

1. 先 render 一筆股票資料
2. 再用不同價格重建 widget
3. 驗證：
   - `成交` 欄會使用 `PriceFlashCell`
   - `總量` 欄不使用 `PriceFlashCell`

### 既有測試

保留並重跑：

- `flutter test test/stock_data_grid_test.dart`
- `flutter test`
- `flutter analyze`

## 不在本次範圍

- 不新增後端即時資料流
- 不改 `StockModel`
- 不把閃爍效果擴到個股頁
- 不做不同欄位不同動畫曲線
- 不做整列背景閃爍

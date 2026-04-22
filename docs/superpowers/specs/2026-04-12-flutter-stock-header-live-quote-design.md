# Flutter Stock Detail Header Live Quote Design

**Date:** 2026-04-12  
**Scope:** 將 [E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart](E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart) 上方 `成交價 / 漲跌 / 漲跌幅 / 開高低收量` 從頁內 mock 改成讀現有即時個股 tick/snapshot。

---

## Goal

讓 Flutter 個股詳細頁 header 的關鍵數值：

- 成交價
- 漲跌
- 漲跌幅
- 開
- 高
- 低
- 昨收
- 量

都直接來自現有 WebSocket 主資料流，而不是頁內 mock。

---

## Non-Goals

這一輪不做以下事情：

- 不擴充 `subscribe_quote_detail` 協議
- 不修改 `ORDER_BOOK_SNAPSHOT / TRADE_TAPE_SNAPSHOT` payload
- 不新增 HTTP API
- 不重做 Flutter 個股頁版面
- 不改 `走勢圖 / K線圖 / 技術指標` 的資料來源
- 不調整 Python 策略或模擬交易邏輯

---

## Design Summary

採用「直接吃現有 tick/snapshot」：

- Python 後端保持現有主行情推播不變
- Flutter 端在 `paper_trade_gateway.dart` 補一條主行情 quote stream
- `stock_detail_quote_page.dart` 進頁時訂閱該 symbol 的即時 quote snapshot
- Header 用 snapshot 覆蓋現有 mock summary

這樣可以讓：

- header 走主行情資料
- 五檔 / 逐筆 / 分時維持原有路徑

不用把 `quote_detail` 協議越做越大。

---

## Data Source

### Existing backend quote payload

目前 Python 主行情推播已包含單一 symbol 的標準化欄位，例如：

- `symbol`
- `price`
- `previousClose`
- `open`
- `high`
- `low`
- `totalVolume`
- `changePct`

這一輪直接重用這些欄位。

### Required Flutter-side view model

Flutter 端新增最小模型，例如：

- `LiveQuoteSnapshot`
  - `symbol`
  - `price`
  - `previousClose`
  - `open`
  - `high`
  - `low`
  - `totalVolume`
  - `changePct`

並提供衍生欄位：

- `changeValue = price - previousClose`

---

## Flutter Changes

### 1. Gateway

在 [E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart](E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart) 增加：

- `LiveQuoteSnapshot` model
- `Stream<LiveQuoteSnapshot> subscribeLiveQuote(String symbol)`

實作方式：

- 直接重用既有主 WebSocket 行情 payload
- 只挑出目標 `symbol`
- 轉成 `LiveQuoteSnapshot`

不新增新的 WebSocket 訊息型別。

### 2. Stock detail page

在 [E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart](E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart)：

- 移除 header mock summary 的固定假值
- 新增 `StreamSubscription<LiveQuoteSnapshot>` 或等價機制
- 進頁時訂閱當前 `symbol`
- 離頁時取消訂閱

header 顯示規則：

- 有資料時：顯示真實數值
- 尚未收到資料時：顯示 `--`

顏色規則：

- 漲：紅
- 跌：綠
- 平：黃或白

---

## UI Behavior

### With live snapshot

Header 依即時 snapshot 顯示：

- 股票名稱 / 代號：沿用頁面參數
- 成交價：`snapshot.price`
- 漲跌：`snapshot.price - snapshot.previousClose`
- 漲跌幅：`snapshot.changePct`
- 開：`snapshot.open`
- 高：`snapshot.high`
- 低：`snapshot.low`
- 收：`snapshot.previousClose`
- 量：`snapshot.totalVolume`

### Without live snapshot

顯示：

- 成交價：`--`
- 漲跌：`--`
- 漲跌幅：`--`
- 開高低收量：`--`

不再顯示任何 mock 數字。

---

## Testing Strategy

### Flutter tests

在 [E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart](E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart) 新增或調整測試：

1. 個股頁收到 `LiveQuoteSnapshot` 後，header 顯示正確數值
2. 未收到 snapshot 時，header 顯示 `--`
3. 不影響既有：
   - 分時線
   - 五檔
   - 逐筆
   - 手動模擬交易按鈕

### Verification

必須通過：

- `flutter test test/stock_detail_quote_page_test.dart`
- `flutter analyze`

---

## Acceptance Criteria

以下條件全部成立才算完成：

1. Header 不再依賴 mock summary
2. Header 全數值來自現有 tick/snapshot 主資料流
3. `quote_detail` 協議不變
4. 沒有即時資料時顯示 `--`
5. Flutter 測試與 analyze 全綠

---

## Recommendation

這一輪完成後，個股頁會形成清楚的資料邊界：

- Header：主行情 snapshot
- 分時線：session bars
- 五檔 / 逐筆：quote detail

這樣比把所有欄位都塞進 `quote_detail` 更乾淨，也更符合現有後端結構。

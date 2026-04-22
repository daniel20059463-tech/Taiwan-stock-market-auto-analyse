# Flutter 個股詳細頁 WebSocket 五檔與逐筆明細推播設計

日期：2026-04-12

## 目標

將 [E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart](E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart) 目前仍為 mock 的「最佳五檔」與「分時明細」接到既有 Python WebSocket 資料源，與目前已接好的分時線與手動模擬交易共用同一條連線模型。

第一版重點是：

- 使用既有 `ws://127.0.0.1:8765`
- 採用「推播型 + 完整快照」模式
- 僅在個股詳細頁開啟時訂閱單一 symbol
- 五檔與逐筆明細都由後端推完整快照
- Flutter 收到資料後直接覆蓋畫面狀態，不做本地重建撮合邏輯

## 範圍

### 要做

- Python 後端新增個股明細訂閱訊息：
  - `subscribe_quote_detail`
  - `unsubscribe_quote_detail`
- Python 後端新增推播訊息：
  - `ORDER_BOOK_SNAPSHOT`
  - `TRADE_TAPE_SNAPSHOT`
- Flutter `PaperTradeGateway` 擴充五檔與逐筆明細訂閱能力
- Flutter `stock_detail_quote_page.dart` 改為顯示真實快照資料
- 補 Python 與 Flutter 對應測試

### 不做

- 不改既有策略判斷、風控或自動交易邏輯
- 不做五檔增量 patch 協議
- 不做多 symbol 同時訂閱
- 不做真正交易所逐筆分類演算法重建；第一版直接吃後端提供的 `side`
- 不把五檔/逐筆資料推到其他頁面

## 資料流設計

### 1. Flutter 進入個股頁

Flutter 開啟個股詳細頁後：

1. 建立或取得 WebSocket 連線
2. 送出：

```json
{
  "type": "subscribe_quote_detail",
  "symbol": "2330"
}
```

3. 後端開始針對該連線推送：
   - `ORDER_BOOK_SNAPSHOT`
   - `TRADE_TAPE_SNAPSHOT`

### 2. Flutter 離開個股頁

Flutter 頁面 `dispose()` 時送出：

```json
{
  "type": "unsubscribe_quote_detail",
  "symbol": "2330"
}
```

後端停止對該連線推播該 symbol 的明細資料。

## WebSocket 協議

### 訂閱訊息

#### subscribe_quote_detail

```json
{
  "type": "subscribe_quote_detail",
  "symbol": "2330"
}
```

用途：要求後端開始推播單一股票的五檔與逐筆明細。

#### unsubscribe_quote_detail

```json
{
  "type": "unsubscribe_quote_detail",
  "symbol": "2330"
}
```

用途：停止推播單一股票的五檔與逐筆明細。

### 推播訊息

#### ORDER_BOOK_SNAPSHOT

```json
{
  "type": "ORDER_BOOK_SNAPSHOT",
  "symbol": "2330",
  "timestamp": 1775949000000,
  "asks": [
    { "level": 5, "price": 505.0, "volume": 198 },
    { "level": 4, "price": 504.0, "volume": 342 }
  ],
  "bids": [
    { "level": 1, "price": 500.0, "volume": 664 },
    { "level": 2, "price": 499.5, "volume": 710 }
  ]
}
```

規則：

- `asks` 固定最多 5 筆
- `bids` 固定最多 5 筆
- 每次推送都是完整快照
- Flutter 直接覆蓋顯示，不做 merge

#### TRADE_TAPE_SNAPSHOT

```json
{
  "type": "TRADE_TAPE_SNAPSHOT",
  "symbol": "2330",
  "timestamp": 1775949000000,
  "rows": [
    { "time": "13:29:58", "price": 504.0, "volume": 7, "side": "outer" },
    { "time": "13:29:41", "price": 503.0, "volume": 237, "side": "outer" },
    { "time": "13:28:54", "price": 502.0, "volume": 19, "side": "inner" }
  ]
}
```

規則：

- `rows` 固定為最新 N 筆，第一版 N=20
- `side` 可為：
  - `outer`
  - `inner`
  - `neutral`
- 每次推送都是完整快照
- Flutter 直接覆蓋顯示

## 後端設計

### Python Collector / Bridge

需要在 [E:\claude code test\run.py](E:\claude code test\run.py) 與 [E:\claude code test\sinopac_bridge.py](E:\claude code test\sinopac_bridge.py) 各自補上相同語意：

- 追蹤每個 websocket client 訂閱的 `quote detail symbol`
- 收到 `subscribe_quote_detail` 後：
  - 記錄該 client 訂閱的 symbol
  - 立即回一包當前完整快照
- 收到 `unsubscribe_quote_detail` 後：
  - 清除該 client 對該 symbol 的訂閱

### 快照來源

#### MockCollector

第一版由 MockCollector 直接根據內部價格狀態產生：

- 五檔快照：使用目前價格附近的模擬委買委賣階梯
- 逐筆明細：維護最新成交 ring buffer

#### SinopacCollector

第一版原則：

- 若 Shioaji 即時欄位不足以穩定取得完整五檔與逐筆明細，允許先以「近價模擬階梯 + tick 歷史 buffer」產生快照
- 協議先定死，後續再替換成更真實的來源

這樣做的理由是先讓 Flutter 端接線與畫面行為穩定，不阻塞整體架構。

## Flutter 端設計

### Gateway 擴充

[E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart](E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart)

新增：

- `OrderBookLevel`
- `OrderBookSnapshot`
- `TradeTapeRow`
- `TradeTapeSnapshot`
- `QuoteDetailStream`

`PaperTradeGateway` 介面新增：

- `Stream<OrderBookSnapshot> subscribeOrderBook(String symbol)`
- `Stream<TradeTapeSnapshot> subscribeTradeTape(String symbol)`
- `Future<void> unsubscribeQuoteDetail(String symbol)`

第一版允許 gateway 內部共用同一個 websocket 實例，但要保證：

- 重複開頁不會產生無限重複訂閱
- 離頁時會正確取消監聽

### 頁面狀態

[E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart](E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart)

新增頁面狀態：

- `_orderBook`
- `_tradeTapeRows`

頁面生命週期：

- `initState()` 訂閱五檔與逐筆明細 stream
- 收到快照即 `setState`
- `dispose()` 取消 stream subscription 並送 `unsubscribe_quote_detail`

### UI 顯示規則

#### 最佳五檔

- 資料完全來自 `ORDER_BOOK_SNAPSHOT`
- `ask` 顯示紅色
- `bid` 顯示綠色
- 無資料時顯示空狀態，不回退到 mock

#### 分時明細

- 資料完全來自 `TRADE_TAPE_SNAPSHOT`
- `outer` 顯示紅色
- `inner` 顯示綠色
- `neutral` 顯示平盤色
- 無資料時顯示空狀態，不回退到 mock

## 錯誤處理

- WebSocket 連線失敗：
  - 保留頁面骨架
  - 五檔與分時明細顯示「暫無即時資料」
- 訂閱成功但資料暫時為空：
  - 顯示空表，不顯示錯誤 SnackBar
- 訊息格式不符：
  - Gateway 忽略該筆訊息
  - 不讓頁面 crash

## 測試策略

### Python

- `run.py`：
  - 訂閱後能推 `ORDER_BOOK_SNAPSHOT`
  - 訂閱後能推 `TRADE_TAPE_SNAPSHOT`
  - 取消訂閱後停止推送
- `sinopac_bridge.py`：
  - 同樣驗證協議與推播格式

### Flutter

- `stock_detail_quote_page_test.dart`
  - 進頁後能顯示真實五檔與逐筆明細資料
  - `dispose()` 時會呼叫 unsubscribe
  - 空資料時顯示空狀態

## 驗收標準

- 個股詳細頁不再依賴 mock 五檔與 mock 分時明細
- Flutter 進頁後能收到並顯示同一條 WebSocket 推播的五檔與逐筆明細
- 離頁後會取消訂閱
- 不影響既有：
  - 分時線
  - K 線
  - 手動模擬交易
  - `PAPER_PORTFOLIO`

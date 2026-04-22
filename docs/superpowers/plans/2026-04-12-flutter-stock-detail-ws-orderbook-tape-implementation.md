# Flutter 個股詳細頁 WebSocket 五檔與逐筆明細推播實作計畫

日期：2026-04-12

## 目標

讓 [E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart](E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart) 的「最佳五檔」與「分時明細」改吃 Python WebSocket 推播，不再使用頁面內建 mock。

## 實作原則

- 先補測試，再寫實作
- 先打通 MockCollector 協議，再補 SinopacCollector
- Flutter 端只做快照覆蓋，不做增量拼裝
- 既有分時線與手動模擬交易不得回歸

## 任務拆分

### Task 1：定義並驗證 Python WebSocket 訂閱協議

**檔案**
- 修改：[E:\claude code test\test_run.py](E:\claude code test\test_run.py)
- 修改：[E:\claude code test\test_sinopac_bridge.py](E:\claude code test\test_sinopac_bridge.py)

**步驟**
- 新增 failing tests：
  - `subscribe_quote_detail` 後會收到 `ORDER_BOOK_SNAPSHOT`
  - `subscribe_quote_detail` 後會收到 `TRADE_TAPE_SNAPSHOT`
  - `unsubscribe_quote_detail` 後停止推送
- 先確認目前測試失敗原因是功能未實作，而不是測試本身錯誤

**驗證**
- `.\.venv\Scripts\python.exe -m pytest -q .\test_run.py -k quote_detail`
- `.\.venv\Scripts\python.exe -m pytest -q .\test_sinopac_bridge.py -k quote_detail`

### Task 2：在 MockCollector 與 SinopacCollector 實作推播

**檔案**
- 修改：[E:\claude code test\run.py](E:\claude code test\run.py)
- 修改：[E:\claude code test\sinopac_bridge.py](E:\claude code test\sinopac_bridge.py)

**步驟**
- 新增 websocket message handling：
  - `subscribe_quote_detail`
  - `unsubscribe_quote_detail`
- 維護 per-client symbol 訂閱狀態
- 新增快照建構 helper：
  - 五檔快照
  - 逐筆明細快照
- 訂閱成功後立即送第一次完整快照
- 後續在 tick 流中針對有訂閱的 client 持續推送

**驗證**
- 重跑 Task 1 的 Python 測試

### Task 3：擴充 Flutter gateway 與資料模型

**檔案**
- 修改：[E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart](E:\claude code test\flutter_app\lib\services\paper_trade_gateway.dart)
- 修改：[E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart](E:\claude code test\flutter_app\test\stock_detail_quote_page_test.dart)

**步驟**
- 新增 Flutter 資料模型：
  - `OrderBookLevel`
  - `OrderBookSnapshot`
  - `TradeTapeRow`
  - `TradeTapeSnapshot`
- 擴充 `PaperTradeGateway` 介面：
  - 訂閱五檔
  - 訂閱逐筆明細
  - 取消訂閱
- 先讓測試用 fake gateway 支援這些資料流
- 補 failing widget tests：
  - 有快照時頁面顯示真實資料
  - 無快照時顯示空狀態
  - 頁面 dispose 會呼叫 unsubscribe

**驗證**
- `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

### Task 4：接線個股詳細頁，移除五檔/逐筆 mock

**檔案**
- 修改：[E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart](E:\claude code test\flutter_app\lib\pages\stock_detail_quote_page.dart)

**步驟**
- 在 `initState()` 訂閱五檔與逐筆明細
- 在 `dispose()` 取消 stream subscription 並送 unsubscribe
- 讓 `_OrderBookPanel` 與 `_TimeAndSalesPanel` 直接吃 gateway 資料
- 移除 `_orderBookLevels()` 與 `_tradeTapeRows()` 作為頁面資料來源
- 保持現有：
  - 分時線
  - K 線
  - 買進/賣出操作列

**驗證**
- `E:\tools\flutter\bin\flutter.bat test test/stock_detail_quote_page_test.dart`

### Task 5：完整驗證

**Python**
- `.\.venv\Scripts\python.exe -m pytest -q`
- `.\.venv\Scripts\python.exe -m py_compile auto_trader.py run.py sinopac_bridge.py`

**Flutter**
- `E:\tools\flutter\bin\flutter.bat analyze`
- `E:\tools\flutter\bin\flutter.bat test`

## 完成定義

符合以下條件才算完成：

- Python WebSocket 已支援個股頁五檔與逐筆明細訂閱/取消訂閱
- Flutter 個股詳細頁已不再依賴 mock 五檔與 mock 分時明細
- 五檔與分時明細可隨推播更新
- 既有測試與新增測試全部通過

# AutoTrader 薄切重構與單一路徑啟動設計

> 日期：2026-04-05
> 主題：在不改變策略邏輯與參數的前提下，拆分 `auto_trader.py` 並收斂 `main.py / run.py` 的啟動責任

## 目標

在完全不改變交易條件、分數公式、進出場規則、風控參數與通知語意的前提下：

1. 將 `auto_trader.py` 從 God Object 收斂為較薄的協調器
2. 把市場狀態、持倉帳本、決策報告、盤後日報等副作用與資料責任拆到專責模組
3. 將 `main.py` 明確定義為唯一正式的 supervisor 啟動路徑
4. 將 `run.py` 降為 runtime wiring / 相容入口，不再承擔第二套生命週期管理

## 非目標

這次重構明確不做以下事情：

- 不調整任何策略參數或閥值
- 不改變做多 / 做空 / 出場 / 風控邏輯
- 不新增新功能
- 不改動前端顯示邏輯
- 不重寫 `AutoTrader` 成完全不同的架構

## 設計原則

1. 行為不變
   - 所有輸入 payload 在相同測試條件下，交易決策結果、回放資料、日報觸發結果都必須維持一致。

2. 薄切，不大翻修
   - 第一輪不做大型抽象化，不建立過多新層級。
   - 僅將資料狀態與副作用提取到明確模組。

3. `AutoTrader` 保留協調器角色
   - `AutoTrader` 仍然保留 `on_tick()` 主控制流與策略順序。
   - 但其內部不再直接維護所有資料細節與輸出組裝。

4. 啟動路徑單一真相來源
   - `main.py` 是正式 supervisor 啟動入口。
   - `run.py` 僅保留 runtime 組裝與相容用途，不再承擔另一套獨立生命週期設計。

## 模組拆分

### 1. `trading/market_state.py`

責任：

- 管理 tick -> 1 分 K 的聚合
- 管理開盤價、最新價、session high/low、volume history
- 提供 ATR / 均量 / 漲跌幅計算所需的市場狀態讀取

包含：

- `CandleBar`
- 目前在 `AutoTrader` 中負責：
  - `_update_candle`
  - `_calc_atr`
  - `_avg_volume`
  - 與 K 棒 / 量能 / 市場價格記憶體有關的欄位

不包含：

- 是否買入 / 放空 / 出場的判斷
- 任何通知、副作用

### 2. `trading/positions.py`

責任：

- 管理 `PaperPosition`
- 管理 `TradeRecord`
- 管理持倉新增、平倉、未實現損益計算、帳本快照輸出

包含：

- `PaperPosition`
- `TradeRecord`
- `get_portfolio_snapshot()` 所需的持倉與交易快照資料組裝

不包含：

- 何時進出場的策略判斷
- 決策報告文字與多空辯論內容

### 3. `trading/decision_reports.py`

責任：

- 管理 `DecisionFactor`
- 管理 `DecisionReport`
- 管理多角色分析與多空辯論結果輸出到 replay/front-end 的格式組裝

包含：

- `DecisionFactor`
- `DecisionReport`
- `to_dict()`
- 報告歷史累積與序列化所需輔助

不包含：

- 新聞分析本身
- 技術分析本身
- 何時應產生哪一種決策的規則

### 4. `trading/reporting.py`

責任：

- 管理盤後日報的觸發與節流
- 管理 EOD 報告 task 狀態
- 管理日報 payload 準備與呼叫 `daily_reporter`

這個模組必須持有自己的節流狀態，不由 `AutoTrader` 保存細節。

明確規則：

- `last_eod_report_date`
- `eod_report_task`
- `eod_report_delay_seconds`

由 `trading/reporting.py` 內部保存與判斷。

`AutoTrader` 只負責在適當時間呼叫：

- `schedule_eod_report(...)`
- `cancel_pending_report(...)`
- `build_daily_report_payload(...)`

也就是：

- `AutoTrader` 知道何時應該觸發報告
- `reporting` 模組知道如何避免重複觸發與如何保存節流狀態

這條邊界是固定的，不可再把節流旗標黏回 `AutoTrader`。

## `AutoTrader` 保留責任

重構後的 `AutoTrader` 保留：

- `on_tick()` 主流程
- 做多 / 放空 / 出場評估流程順序
- 風控與 analyst 呼叫順序
- 發送通知與持久化流程的 orchestration

`AutoTrader` 不再直接保有過多資料細節，只持有：

- market state service
- positions service
- decision report service
- reporting service
- risk manager
- sentiment filter
- daily reporter
- multi analyst components

## 啟動路徑收斂

### `main.py`

正式責任：

- `AppSupervisor`
- 生命週期狀態機
- sentinel 監控
- graceful shutdown
- fail-closed 行為

### `run.py`

收斂後責任：

- runtime component wiring
- collector / bridge / mock runtime 建立
- 提供可被 `main.py` 呼叫的組裝函式
- 保留相容入口，但不應再自行定義另一套 supervisor 行為

明確方向：

- `main.py` 呼叫 `run.py` 暴露的 runtime builder
- `run.py` 不再是與 `main.py` 平行競爭的主入口設計

## 預期檔案變動

新增：

- `trading/__init__.py`
- `trading/market_state.py`
- `trading/positions.py`
- `trading/decision_reports.py`
- `trading/reporting.py`

修改：

- `auto_trader.py`
- `main.py`
- `run.py`
- 相關測試檔

## 測試策略

這次重構的測試目標不是增加功能，而是保證行為不變。

### 必須保留並通過

- 現有 `AutoTrader` 相關測試
- 做多 / 做空 / EOD / DecisionReport 測試
- 日報與回放測試
- `main.py` / `run.py` 啟動路徑測試

### 建議新增

1. `market_state` 單元測試
   - tick 聚合為 1 分 K 不變
   - ATR / volume 平均值不變

2. `positions` 單元測試
   - long / short 未實現損益計算不變
   - 快照輸出結構不變

3. `reporting` 單元測試
   - 同一交易日不重複發送 EOD 報告
   - pending report task 可取消

4. `main/run` 結構測試
   - 正式 supervisor 路徑只由 `main.py` 承擔
   - `run.py` builder 可被 `main.py` 調用

## 風險與控制

### 風險 1：重構時改到交易邏輯

控制：

- 先抽資料與副作用，再搬決策程式碼
- 全程以既有測試鎖住
- 新測試只驗證結構與輸出一致性

### 風險 2：拆分後狀態同步錯誤

控制：

- 狀態只允許單一模組持有
- `market_state`、`positions`、`reporting` 各自擁有自己的狀態
- `AutoTrader` 不再同時複製保存同一份狀態

### 風險 3：`run.py` / `main.py` 收斂時破壞桌面版或測試入口

控制：

- 保留相容入口
- 先將 builder 抽出，再收斂主入口責任
- 以現有整合測試與桌面打包驗證

## 驗收標準

1. `auto_trader.py` 顯著縮小，且資料/副作用責任已搬出
2. `AutoTrader` 仍保留相同策略邏輯與決策順序
3. 現有策略相關測試全部綠燈
4. `main.py` 成為唯一正式 supervisor 路徑
5. `run.py` 僅保留 runtime wiring / 相容入口責任
6. 重構後桌面打包與前後端核心測試仍能通過


# 每日自動運行 SOP

這份文件是 Taiwan Alpha Radar 目前的固定日常流程說明。目的只有三件事：

1. 開盤前把策略需要的籌碼資料補齊。
2. 開盤時自動啟動 live runtime。
3. 開盤後快速驗證 websocket、可見集、五檔、逐筆是否正常。

## 每日固定時序

平日排程目前固定如下：

1. `08:50:50` 執行籌碼 refresh
2. `08:58:58` 執行開盤前啟動器
3. `09:06:06` 執行 live smoke

對應 Windows Task Scheduler 任務：

1. `TaiwanAlphaRadarFlowRefresh`
2. `TaiwanAlphaRadarStartAtOpen`
3. `TaiwanAlphaRadarLiveSmoke`

## 每個任務實際做什麼

### 1. 籌碼 refresh

任務：
- `TaiwanAlphaRadarFlowRefresh`

入口腳本：
- [run_institutional_flow_refresh.ps1](E:\claude code test\scripts\run_institutional_flow_refresh.ps1)
- [refresh_institutional_flow_cache.py](E:\claude code test\scripts\refresh_institutional_flow_cache.py)

核心行為：
- 讀取官方 TWSE / TPEX 籌碼資料
- 寫入本地 flow cache
- `retail_flow_swing` 模式下，寫入「前一個開市日」的 key

成功判斷：
- log 中有 JSON 輸出
- `row_count > 0`
- `cache_write = true`

範例成功輸出：

```json
{"trade_date":"2026-04-21","row_count":1868,"sample_symbols":["1802","3231","0050","1303","2324"],"cache_write":true}
```

### 2. 開盤前啟動器

任務：
- `TaiwanAlphaRadarStartAtOpen`

入口腳本：
- [start_run_at_open.ps1](E:\claude code test\scripts\start_run_at_open.ps1)
- [run.py](E:\claude code test\run.py)

核心行為：
- 平日 08:58 先被 Task Scheduler 叫起來
- 腳本自己再次確認今天是否為台股開市日
- 等到 `09:00` 後啟動 `run.py`
- 若 `run.py` 已存在，則不重複開第二份

成功判斷：
- [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log) 有 `started run.py pid=...`
- `127.0.0.1:8765` 有 listening
- `run_live_*.err.log` 中出現 `Collector running on ws://127.0.0.1:8765`

### 3. Live smoke

任務：
- `TaiwanAlphaRadarLiveSmoke`

入口腳本：
- [run_visible_quote_detail_smoke.ps1](E:\claude code test\scripts\run_visible_quote_detail_smoke.ps1)
- [visible_quote_detail_smoke.py](E:\claude code test\scripts\visible_quote_detail_smoke.py)

核心行為：
- 連線到本機 websocket
- 設定 visible symbols
- 訂閱單一測試股的詳細報價
- 檢查 quote / 五檔 / 逐筆

成功判斷：
- log JSON 內同時滿足：
  - `got_quote = true`
  - `got_order_book = true`
  - `got_trade_tape = true`

## 每天先看哪裡

如果你只想最快確認今天有沒有正常跑，優先順序如下：

1. Task Scheduler 三個任務是不是 `Ready`
2. [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log)
3. 最新的 `run_live_*.err.log`
4. 最新的 `institutional_flow_refresh_*.log`
5. 最新的 `visible_quote_detail_smoke_*.log`

## Log 對照表

開盤啟動器：
- [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log)

live runtime：
- `E:\claude code test\logs\run_live_*.out.log`
- `E:\claude code test\logs\run_live_*.err.log`

籌碼 refresh：
- `E:\claude code test\logs\institutional_flow_refresh_*.log`

smoke：
- `E:\claude code test\logs\visible_quote_detail_smoke_*.log`

前端 dev server：
- `E:\claude code test\logs\vite_*.out.log`
- `E:\claude code test\logs\vite_*.err.log`

## 常見異常與第一檢查點

### 情況 A：今天完全沒啟動

先看：

1. `TaiwanAlphaRadarStartAtOpen` 任務是否還在
2. [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log) 是否有新紀錄
3. `run.py` 路徑是否仍為 `E:\claude code test\run.py`

常見原因：
- Task Scheduler 任務被刪掉
- `run.py` 路徑變了
- Python 虛擬環境路徑變了

### 情況 B：8765 沒有 listening

先看：

1. 最新的 `run_live_*.err.log`
2. [run.py](E:\claude code test\run.py)
3. [start_run_at_open.ps1](E:\claude code test\scripts\start_run_at_open.ps1)

常見原因：
- `run.py` 啟動後立即 crash
- `.env` 缺值
- collector 初始化失敗

### 情況 C：策略沒出單

先分兩層看：

1. runtime 有沒有正常跑
2. 策略本身今天是否真的沒有觸發條件

先看：

1. 最新 `run_live_*.err.log` 是否有 `AutoTrader.on_tick error`
2. websocket 的 `PAPER_PORTFOLIO` 是否有 `todayTrades`
3. 籌碼 refresh 是否有成功寫入今天要用的 trade date

注意：
- 「沒出單」不等於系統壞掉
- 但如果 log 有 runtime error，就不能把它解讀成策略判斷結果

### 情況 D：前端顯示已連線但資料是空的

先看：

1. backend 的 `8765` 是否 listening
2. smoke 是否通過
3. `run_live_*.err.log` 是否真的有 tick 流進來

判讀原則：
- 如果 smoke fail，先修 backend 或 websocket
- 如果 smoke pass 但前端空，問題多半在前端 store / 合併邏輯 / bar cache

## 建議的每日檢查順序

每天如果要人工快速掃一次，順序固定照這個：

1. 看 Task Scheduler 三個任務還在不在
2. 09:00 後看 [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log)
3. 看最新 `run_live_*.err.log` 是否有 runtime error
4. 看最新 `visible_quote_detail_smoke_*.log` 是否三項都 pass
5. 盤中再看 `PAPER_PORTFOLIO` 是否已有成交

## 目前相關檔案

排程安裝腳本：
- [install_daily_flow_refresh_task.ps1](E:\claude code test\scripts\install_daily_flow_refresh_task.ps1)
- [install_daily_start_task.ps1](E:\claude code test\scripts\install_daily_start_task.ps1)
- [install_daily_smoke_task.ps1](E:\claude code test\scripts\install_daily_smoke_task.ps1)

執行腳本：
- [run_institutional_flow_refresh.ps1](E:\claude code test\scripts\run_institutional_flow_refresh.ps1)
- [start_run_at_open.ps1](E:\claude code test\scripts\start_run_at_open.ps1)
- [run_visible_quote_detail_smoke.ps1](E:\claude code test\scripts\run_visible_quote_detail_smoke.ps1)

Python 入口：
- [refresh_institutional_flow_cache.py](E:\claude code test\scripts\refresh_institutional_flow_cache.py)
- [visible_quote_detail_smoke.py](E:\claude code test\scripts\visible_quote_detail_smoke.py)
- [run.py](E:\claude code test\run.py)

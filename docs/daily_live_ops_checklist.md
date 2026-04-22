# 每日值班 Checklist

這份只保留每日最短檢查步驟，不解釋原理。要看完整流程與排錯說明，請看：

- [daily_live_ops_sop.md](E:\claude code test\docs\daily_live_ops_sop.md)

## 每日必看

### 開盤前 08:55 前

確認三個排程任務存在且狀態為 `Ready`：

1. `TaiwanAlphaRadarFlowRefresh`
2. `TaiwanAlphaRadarStartAtOpen`
3. `TaiwanAlphaRadarLiveSmoke`

### 09:00 後

1. 看 [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log)
2. 確認有 `started run.py pid=...`
3. 確認 `127.0.0.1:8765` 正在 listening

### 09:10 前

1. 看最新 `visible_quote_detail_smoke_*.log`
2. 確認：
   - `got_quote = true`
   - `got_order_book = true`
   - `got_trade_tape = true`

### 盤中

1. 看最新 `run_live_*.err.log`
2. 確認沒有持續出現 `AutoTrader.on_tick error`
3. 看 `PAPER_PORTFOLIO` 是否已有 `todayTrades`

## 異常時先做什麼

### 沒啟動

1. 看 `TaiwanAlphaRadarStartAtOpen`
2. 看 [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log)
3. 看最新 `run_live_*.err.log`

### 8765 沒開

1. 看最新 `run_live_*.err.log`
2. 看 [run.py](E:\claude code test\run.py)
3. 看 [start_run_at_open.ps1](E:\claude code test\scripts\start_run_at_open.ps1)

### 前端已連線但資料空

1. 先看 smoke 有沒有 pass
2. 再看 backend `8765` 是否 listening
3. 最後才看前端 store / cache / 合併邏輯

### 沒出單

1. 先確認 runtime 沒報錯
2. 再確認籌碼 refresh 成功
3. 最後才判斷今天是否真的沒有策略訊號

## 每日關鍵檔案

排程：

- [install_daily_flow_refresh_task.ps1](E:\claude code test\scripts\install_daily_flow_refresh_task.ps1)
- [install_daily_start_task.ps1](E:\claude code test\scripts\install_daily_start_task.ps1)
- [install_daily_smoke_task.ps1](E:\claude code test\scripts\install_daily_smoke_task.ps1)

log：

- [start_run_at_open.log](E:\claude code test\logs\start_run_at_open.log)
- `E:\claude code test\logs\institutional_flow_refresh_*.log`
- `E:\claude code test\logs\run_live_*.err.log`
- `E:\claude code test\logs\visible_quote_detail_smoke_*.log`

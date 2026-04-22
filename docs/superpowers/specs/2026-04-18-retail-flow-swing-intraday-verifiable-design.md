# Retail Flow Swing Intraday-Verifiable Design

日期：2026-04-18  
狀態：Approved

## 1. 目標

把現有 `retail_flow_swing` 做成「盤中可驗證版本」：  
盤前用官方 `TWSE + TPEX` 籌碼資料建立候選，盤中再用價格與量能條件把候選從 `watch` 推進到 `ready_to_buy`，並在條件成立時自動送出 `paper trade`。

這一版的重點不是最佳化報酬，而是讓以下鏈路在盤中能真實驗證：

- 籌碼資料 prime 成功
- 候選池非空
- 單一股票在盤中進入 `watch`
- 單一股票在盤中進入 `ready_to_buy`
- `ready_to_buy` 後真的送出 `PAPER_TRADE_RESULT`

## 2. 範圍

納入：

- `retail_flow_strategy.py` 的盤中可驗證條件
- `auto_trader.py` swing 模式進場 / 出場路徑
- 啟動時官方籌碼 cache prime
- 盤中 smoke 驗證需要的狀態與日志

不納入：

- 主力資料回歸
- 盤中即時法人流向
- 報酬優化與參數搜尋
- 新 UI

## 3. 核心策略

### 3.1 盤前候選

來源：

- `TWSE T86`
- `TPEX dailyTrade`

第一版採 `外資 + 投信` 評分，`major_net_buy` 保留欄位但不計分。

基本條件：

- 外資淨買超 > 0
- 投信淨買超 > 0
- 投信連續買超 `>= 2` 天

### 3.2 盤中狀態

候選股票在盤中會落在三種狀態之一：

- `skip`
- `watch`
- `ready_to_buy`

判斷邏輯：

- 籌碼分數 <= 0：`skip`
- 最近漲幅過熱：`skip`
- 投信連買天數 < 2：`watch`
- 已站上 `10 日線` 且量能確認：`ready_to_buy`
- 其餘：`watch`

### 3.3 `ready_to_buy` 硬條件

- `flow_score > 0`
- `consecutive_trust_days >= 2`
- 價格站上 `10 日線`
- 量能高於近 `5` 日均量確認
- 近期漲幅不可過熱，避免追高

### 3.4 自動 paper trade

當股票首次進入 `ready_to_buy` 時：

- 自動送出 `paper buy`
- 仍沿用現有風控與持倉流程
- 不改手動 `paper_trade` 協議

## 4. 出場

維持既有 swing 出場邏輯：

- 硬停損
- 跌破 `10 日線`
- 籌碼轉弱
- 持有超過 `10` 天

## 5. 驗證目標

盤中驗證至少要能回答這四件事：

- 今天是否成功 prime 官方籌碼 cache
- 候選股票是否能進入 `watch`
- 候選股票是否能進入 `ready_to_buy`
- 自動 `paper trade` 是否真的送出且回 `ok`

## 6. 檔案邊界

- `institutional_flow_provider.py`
  - 官方籌碼資料抓取
- `institutional_flow_cache.py`
  - 當日 cache 存取
- `retail_flow_strategy.py`
  - `flow_score / watch / ready_to_buy / exit`
- `auto_trader.py`
  - swing 模式盤中進出場執行
- `run.py`
  - 啟動時 prime cache

## 7. 測試

至少覆蓋：

- 投信連買 < 2 天時不可 `ready_to_buy`
- 條件全滿足時進入 `ready_to_buy`
- `ready_to_buy` 時會走到自動 paper trade
- cache prime 後可對指定 symbol 正確取回 flow row


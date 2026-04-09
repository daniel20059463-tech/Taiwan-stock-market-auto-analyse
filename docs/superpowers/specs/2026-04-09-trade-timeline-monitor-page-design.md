# 交易時間線監控頁設計

## 目標

新增一個獨立頁面，讓桌面 App 使用者在盤中與收盤後，能直接查看「今天 / 最近 7 天」的成交與平倉時間線。第一版只吃現有 `replayTrades / recentTrades`，不建立新的監控事件流，不改後端交易邏輯。

頁面重點是交易事件可讀性，不是健康儀表板。系統健康狀態最多只作為輔助資訊，不作為主視覺。

## 非目標

以下內容不在這一輪範圍內：

- 不新增獨立的 collector / analyzer / auto_trader 事件流
- 不新增收盤驗證摘要卡
- 不改 `AutoTrader` 的交易行為、策略參數、EOD 規則
- 不新增 Telegram 通知
- 不重做 Dashboard 首頁排版

## 現有基礎

目前系統已具備足夠資料來源：

- 後端 [E:\claude code test\auto_trader.py](E:\claude code test\auto_trader.py) 的 `get_portfolio_snapshot()` 會回傳：
  - `recentTrades`
  - `recentDecisions`
  - `positions`
  - `PAPER_PORTFOLIO`
- 前端 [E:\claude code test\src\store.ts](E:\claude code test\src\store.ts) 已維護：
  - `portfolio`
  - `replayTrades`
  - `replayDecisions`
- 目前已有回放頁 [E:\claude code test\src\pages\TradeReplay.tsx](E:\claude code test\src\pages\TradeReplay.tsx)，可作為共用 decision detail 顯示邏輯的參考

因此第一版可直接從 store 派生交易時間線，不必動後端。

## 使用者體驗

新增一個獨立頁面，例如：

- 路由：`/monitor`
- 導航名稱：`交易監控`

頁面結構採單頁雙視角：

### 上方控制列

- 時間範圍切換：
  - `今天`
  - `最近 7 天`
- 事件類型切換：
  - `全部`
  - `只看成交`
  - `只看平倉`
- 搜尋框：
  - 支援股票代碼
  - 支援中文名稱

### 左側主區：交易時間線

時間線只顯示下列交易動作：

- `BUY`
- `SELL`
- `SHORT`
- `COVER`

排序方式：

- 預設最新在上
- 同一時間時維持原始順序

每筆事件卡至少顯示：

- 時間
- 股票代碼 + 中文名稱
- 動作
- 價格
- 張數
- 淨損益
- 原因

### 右側詳情區

點選左側事件後，右側顯示該筆交易詳情。資料直接取自 trade 與其對應的 `decisionReport`。

顯示欄位：

- 最終理由
- 支持因素
- 反對因素
- 多方論點
- 空方論點
- 裁決結果
- 風險旗標

若該交易沒有完整 `decisionReport`，顯示降級版詳情，不讓頁面空白或報錯。

## 資料來源與資料流

### 單一資料來源

頁面資料來源採以下優先序：

1. `replayTrades`
2. 若不足，再補 `portfolio.recentTrades`

理由：

- `replayTrades` 是跨重整保留的回放資料
- `recentTrades` 是目前 session 的即時補充

### 資料彙整規則

頁面會建立一個前端派生 view model，不直接把 store 原始資料綁進畫面。

建議新增一個輕量 selector/helper，負責：

- 合併 `replayTrades` 與 `recentTrades`
- 去重
- 依日期範圍過濾
- 依 `BUY/SELL/SHORT/COVER` 分類
- 依 symbol/name 搜尋
- 產生顯示用 label 與顏色

這樣頁面元件只負責 render，不負責資料清洗。

## 日期與過濾規則

### 今天

- 以 `Asia/Taipei` 自然日計算
- 只顯示當天交易

### 最近 7 天

- 以 `Asia/Taipei` 計算最近 7 個自然日
- 包含今天

### 事件類型切換

- `全部`：顯示 `BUY / SELL / SHORT / COVER`
- `只看成交`：顯示 `BUY / SHORT`
- `只看平倉`：顯示 `SELL / COVER`

## 路由與殼層整合

需更新：

- [E:\claude code test\src\App.tsx](E:\claude code test\src\App.tsx)
- [E:\claude code test\src\components\AppShell.tsx](E:\claude code test\src\components\AppShell.tsx)

新增：

- [E:\claude code test\src\pages\TradeMonitor.tsx](E:\claude code test\src\pages\TradeMonitor.tsx)

若現有導航文案仍有亂碼，本輪只修和新增頁面直接相關的文案，不做整站文案總清理。

## 視覺與版面方向

沿用目前桌面 App 的深色、硬邊框交易台風格，不引入新的 UI 語言。

頁面版型：

- 左 60%：時間線列表
- 右 40%：詳情卡

在窄螢幕下可退化為上下排列，但桌面版優先維持左右欄。

時間線本身應固定高度並可內部捲動，不把整頁撐長。

## 錯誤處理與空狀態

### 無資料

當前範圍內無交易時，左側顯示：

- `此範圍內沒有可顯示的成交或平倉事件。`

右側顯示：

- `請先從左側選擇一筆交易。`

### 缺少 decisionReport

若某筆交易沒有 `decisionReport`：

- 詳情區仍顯示基本交易資料
- 其餘欄位顯示 `無決策報告`

### 名稱查不到

若 symbol 在 instruments 裡找不到名稱：

- 顯示代碼本身
- 名稱欄位顯示 `未知標的`

## 測試策略

第一版至少補以下前端測試：

1. 路由與導航
- 新頁面能從路由進入
- 側欄顯示 `交易監控`

2. 時間線資料來源
- `replayTrades` 優先
- `portfolio.recentTrades` 可補資料

3. 篩選與搜尋
- `今天 / 最近 7 天`
- `全部 / 只看成交 / 只看平倉`
- symbol/name 搜尋

4. 詳情顯示
- 點選事件後右側顯示對應資料
- 缺少 `decisionReport` 時顯示降級內容

5. 空狀態
- 指定日期範圍沒有交易時顯示正確空狀態

## 驗收標準

完成後應滿足：

- 桌面 App 側欄有 `交易監控` 頁
- 頁面能顯示 `今天 / 最近 7 天` 的 `BUY/SELL/SHORT/COVER` 時間線
- 可依成交/平倉與 symbol/name 篩選
- 點事件能看詳情
- 不新增後端事件流
- 不改交易邏輯
- 前端測試與 build 通過

## 風險與控制

### 風險 1：資料重複

`replayTrades` 與 `recentTrades` 可能重複。

控制：

- 在 selector/helper 層做去重

### 風險 2：decisionReport 缺失

舊資料可能沒有完整報告。

控制：

- 詳情頁採降級顯示

### 風險 3：頁面複雜度上升

若直接把 TradeReplay 的全部內容搬過來，頁面會過重。

控制：

- 這一頁只做交易時間線與單筆細節
- 不混進績效分析與收盤驗證

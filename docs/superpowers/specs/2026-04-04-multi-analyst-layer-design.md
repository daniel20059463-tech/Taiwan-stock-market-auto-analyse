# Multi-Analyst Layer Design

**Goal**

在不拖慢台股盤中模擬交易主路徑的前提下，吸收 TradingAgents 的核心優勢，為現有系統加入「多角色分析層」，讓每筆候選交易都能先經過多觀點評估，再由決策層整合成可回放、可檢討的 `DecisionReport`。

**Scope**

本設計只涵蓋盤中規則化 analyst 與其資料結構、整合流程、前後端資料契約，不包含真正的 LLM 多代理編排，也不包含盤後自然語言長篇報告生成。盤後 LLM 補充報告會作為下一個子專案。

## 1. Current Context

目前系統已具備以下能力：

- [E:\claude code test\run.py](E:\claude code test\run.py) / [E:\claude code test\sinopac_bridge.py](E:\claude code test\sinopac_bridge.py) 提供台股行情與 websocket bridge。
- [E:\claude code test\analyzer.py](E:\claude code test\analyzer.py) 透過 shared memory 分析新聞，輸出 sentiment / keywords。
- [E:\claude code test\sentiment_filter.py](E:\claude code test\sentiment_filter.py) 提供盤中情緒阻擋條件。
- [E:\claude code test\auto_trader.py](E:\claude code test\auto_trader.py) 根據 tick、K 棒、風控與輿情條件產生模擬交易。
- [E:\claude code test\src\pages\TradeReplay.tsx](E:\claude code test\src\pages\TradeReplay.tsx) 現在已能顯示結構化 `DecisionReport`。

目前的缺點是：雖然已有 `DecisionReport`，但其判斷仍然偏向單一路徑決策，尚未拆成多觀點分析，也無法自然表達多空對立理由與風控觀點之間的衝突。

## 2. Product Intent

新的多角色分析層要達到三件事：

1. 盤中維持低延遲，不依賴 LLM。
2. 讓每筆候選交易有清楚的多觀點輸入，而不是只有單一結論。
3. 為盤後回放與未來 LLM 報告建立穩定資料基礎。

因此採用「混合型多角色」方案：

- 盤中：規則化 analyst，快速產出結構化觀點。
- 盤後：未來再用 LLM 將結構化資料轉成自然語言研究報告。

## 3. Architecture

新增一層 `multi_analyst` 分析模組，放在 [E:\claude code test\auto_trader.py](E:\claude code test\auto_trader.py) 前的決策準備階段。資料流如下：

1. 市場資料與新聞分析結果進入 `AutoTrader`。
2. `AutoTrader` 呼叫多個 analyst，取得各自的 `AnalystView`。
3. `DecisionComposer` 將 analyst views 整合成 `DecisionBundle`。
4. `DecisionBundle` 再映射成現有的 `DecisionReport`。
5. `DecisionReport` 綁到 `TradeRecord`、skip decision、portfolio snapshot 與 replay store。

這樣不需要重寫前端主要資料流，也不會破壞現有 websocket 契約，只需擴充。

## 4. New Components

### 4.1 AnalystView

新增統一的 analyst 輸出物件，欄位如下：

- `agent_name`
- `stance`
  - `bullish`
  - `bearish`
  - `neutral`
  - `blocking`
- `score`
- `summary`
- `supporting_factors`
- `opposing_factors`
- `blocking`
- `metadata`

其用途是讓不同 analyst 的輸出可以並排比較，並作為 `DecisionBundle` 的輸入。

### 4.2 DecisionBundle

新增整合後的決策物件，欄位如下：

- `symbol`
- `ts`
- `views`
- `bull_case`
- `bear_case`
- `risk_case`
- `final_decision`
- `confidence`
- `order_intent`

`DecisionBundle` 是盤中規則層的最終抽象，下一層才會再轉成使用者可讀的 `DecisionReport`。

### 4.3 NewsAnalyst

輸入：

- analyzer sentiment
- keywords
- article_id
- deadline / validity

輸出：

- 新聞方向
- 新聞強度
- 時效性
- 支持或反對理由

第一版只依賴現有 analyzer / sentiment 結果，不新增外部模型。

### 4.4 SentimentAnalyst

輸入：

- [E:\claude code test\sentiment_filter.py](E:\claude code test\sentiment_filter.py) 的 score 與 blocking 狀態

輸出：

- 情緒方向
- 情緒分數
- 是否阻擋
- 支持或反對理由

### 4.5 TechnicalAnalyst

輸入：

- 漲跌幅
- 1 分 K
- MA5 / MA20 / MA60
- 量能確認
- 是否接近日高 / 日低

輸出：

- 技術方向
- 技術確認分數
- 支持與反對理由

### 4.6 RiskAnalyst

輸入：

- [E:\claude code test\risk_manager.py](E:\claude code test\risk_manager.py) 的風控狀態
- 持倉數
- 單筆風險
- 日內 / 週內停用狀態

輸出：

- 是否允許新單
- 風控旗標
- 風險懲罰分數
- 阻擋理由

### 4.7 DecisionComposer

整合所有 `AnalystView` 並產出：

- `bull_case`
- `bear_case`
- `risk_case`
- `final_decision`
- `confidence`
- `DecisionReport`

第一版 composer 為規則化邏輯，不引入 LLM。

## 5. Integration Plan

### 5.1 Backend Integration

後端會優先從 [E:\claude code test\auto_trader.py](E:\claude code test\auto_trader.py) 整合。

整合點：

- `_evaluate_buy`
- `_check_exit`
- `_paper_buy`
- `_paper_sell`
- skip decision recording

原本直接在 `AutoTrader` 內部組裝 `DecisionReport` 的邏輯，將逐步收斂為：

1. 先收集 analyst views
2. 再由 composer 產生 decision bundle
3. 最後映射成 `DecisionReport`

### 5.2 Frontend Integration

前端不新增新的主資料來源，而是沿用現有 `recentTrades` / `recentDecisions`。

受影響檔案：

- [E:\claude code test\src\types\market.ts](E:\claude code test\src\types\market.ts)
- [E:\claude code test\src\store.ts](E:\claude code test\src\store.ts)
- [E:\claude code test\src\pages\TradeReplay.tsx](E:\claude code test\src\pages\TradeReplay.tsx)
- [E:\claude code test\src\pages\Performance.tsx](E:\claude code test\src\pages\Performance.tsx)
- [E:\claude code test\src\pages\StrategyWorkbench.tsx](E:\claude code test\src\pages\StrategyWorkbench.tsx)

第一版前端重點：

- 回放頁顯示 analyst-based decision report
- 績效頁可讀取更細的決策來源資料
- 作戰台後續可顯示多角色分數卡

## 6. Non-Goals

這一版不做：

- LangGraph 或完整 agent orchestration
- 即時 LLM 多回合辯論
- 大型 prompt-based 投資結論生成
- 跨多策略的 agent marketplace

這些屬於更後期的研究型能力，不是目前盤中低延遲主路徑的優先項。

## 7. Testing Strategy

### Backend

- 新增 analyst unit tests
- 新增 composer unit tests
- 驗證 buy / sell / skip 都會產生正確 analyst-derived `DecisionReport`
- 驗證風控阻擋、情緒阻擋、量能不足等情況的多角色輸出

### Frontend

- 驗證 replay page 能顯示多角色決策報告
- 驗證 store 能保存擴充後的 decision data
- 驗證 performance/workbench 不會因新增欄位而壞掉

### Full Verification

- `npm test`
- `npm run build`
- `pytest -q`
- `python -m py_compile ...`

## 8. Recommended Delivery Order

1. 新增 `AnalystView` / `DecisionBundle` 型別與純函式 helper
2. 實作 `TechnicalAnalyst` 與 `RiskAnalyst`
3. 實作 `NewsAnalyst` 與 `SentimentAnalyst`
4. 實作 `DecisionComposer`
5. 將 `AutoTrader` 目前的 decision report 組裝邏輯替換為多角色版本
6. 擴充前端 replay / performance 顯示
7. 跑整套回歸與 build 驗證

## 9. Why This Is the Right Next Step

這個設計不會強迫系統全面改寫，卻能直接吸收 TradingAgents 最有價值的核心能力：

- 多觀點分析
- 多空對立理由
- 更強的可解釋性
- 為未來盤後 LLM 報告建立基礎

它比直接硬上 LLM agent orchestration 更穩、更快，也更符合你目前「台股即時模擬交易平台」的產品方向。

# Telegram 盤後日報設計

## 目標

在台股模擬交易系統中新增一個「盤後 LLM 日報」能力。系統會在收盤後、模擬交易結束且資料穩定一段時間後，自動整理當日交易結果、挑選重點交易、呼叫 LLM 產生自然語言總結，最後直接透過 Telegram 推送給使用者。

這份日報的定位是：

- 以「整日交易總結」為主
- 以「單筆重點檢討」為輔
- 優先在手機上好讀
- 失敗時仍有結構化 fallback，不讓日報整份消失

## 範圍

這一版只做：

- 收盤後延遲觸發的日報流程
- 當日重點交易挑選
- 兩階段 LLM 報告生成
- Telegram 直接推送
- LLM 失敗時的模板 fallback
- 測試與驗證

這一版不做：

- UI 頁面版的盤後報告
- 週報 / 月報
- 多策略比較
- 多代理長篇研究報告
- 盤中即時 LLM 解釋

## 現況背景

目前系統已有這些能力：

- [E:\claude code test\auto_trader.py](E:\claude code test\auto_trader.py)
  已能產生 `DecisionReport`，並包含支持理由、反對理由、多方觀點、空方觀點、風控觀點，以及多空辯論層的 `bullArgument / bearArgument / refereeVerdict / debateWinner`。
- [E:\claude code test\src\pages\TradeReplay.tsx](E:\claude code test\src\pages\TradeReplay.tsx)
  已能顯示完整決策證據鏈。
- [E:\claude code test\notifier.py](E:\claude code test\notifier.py)
  已負責 Telegram 出站通知、限流與降級。

這代表盤後日報不需要重做資料蒐集基礎，而是可以直接站在現有 `DecisionReport` 與 `recentTrades` 之上。

## 設計方向

### 推薦做法：兩階段型

這一版採用「兩階段 LLM」：

1. 先從當日交易中挑出 2 到 5 筆最值得檢討的交易
2. 逐筆生成簡短交易檢討
3. 再將整體績效摘要與重點交易短評交給第二次 LLM，生成一則完整 Telegram 日報

這樣做的好處是：

- 比單次總結更有洞察
- 比多角色長報告更輕量
- 輸出長度較容易控制
- 比較符合 Telegram 閱讀場景

## 架構

新增一個獨立模組：

- [E:\claude code test\daily_reporter.py](E:\claude code test\daily_reporter.py)

它負責：

1. 蒐集當日交易與績效摘要
2. 挑選重點交易
3. 準備 LLM 輸入 payload
4. 呼叫 LLM 生成報告
5. 發送給 [E:\claude code test\notifier.py](E:\claude code test\notifier.py)

這樣可以避免把 [E:\claude code test\auto_trader.py](E:\claude code test\auto_trader.py) 撐得更複雜，並維持模組邊界清楚。

## 觸發時機

日報不會在收盤瞬間送出，而是遵循以下條件：

1. 已經進入 EOD 流程
2. 所有模擬部位都已平倉
3. `recentTrades` / `recentDecisions` 已穩定
4. 再延後 3 到 5 分鐘
5. 然後開始日報生成

這樣可以降低以下問題：

- 最後幾筆交易尚未落帳
- EOD 平倉還沒完成
- Telegram 通知與日報同時競爭資源

## 資料輸入

### 整日摘要

日報生成前，先整理一份結構化摘要：

- 日期
- 總交易數
- 勝率
- 已實現損益
- 未實現損益
- 總損益
- 是否觸發日內風控 / 週風控
- 今日最佳交易
- 今日最差交易

### 重點交易候選

再從當日交易中挑出 2 到 5 筆重點檢討標的。排序依據建議如下：

1. 絕對損益最大
2. 決策信心與最終結果落差大
3. 被風控攔截或 skip 的重要訊號
4. `debateWinner` 與最終結果明顯背離

每筆重點交易輸入內容包含：

- `DecisionReport`
- 多方 / 空方 / 風控觀點
- 多空辯論結果
- 最終成交結果
- 最終損益

## 兩階段 LLM 流程

### 第一階段：單筆檢討

對每筆重點交易呼叫一次 LLM，輸出短評。重點是回答：

- 這筆交易當時為什麼做
- 多方論點與空方論點哪邊較合理
- 風控是否應該更早介入
- 這筆交易做對或做錯的主因是什麼

輸出格式要求：

- 2 到 4 句中文
- 聚焦交易本身
- 不要冗長鋪陳

### 第二階段：全日總結

將整日摘要與重點交易短評交給第二次 LLM，輸出 Telegram 日報。內容結構如下：

1. 今日總結
2. 交易表現摘要
3. 今日最好交易
4. 今日最差交易
5. 重點檢討 2 到 3 筆
6. 明日觀察建議

輸出要求：

- 使用自然中文
- 長度控制在 Telegram 易讀範圍
- 避免過度官腔或重複
- 以「你今天做得怎麼樣」的角度來寫

## Telegram 訊息格式

Telegram 最終推送建議採單則訊息，格式像：

- `盤後日報｜2026-04-04`
- 今日損益 / 勝率 / 交易數
- 今日最佳交易
- 今日最差交易
- 重點交易檢討
- 明日觀察

訊息長度必須受控，若超過 Telegram 長度上限，需套用既有截斷規則。

## Fallback 策略

若 LLM 呼叫失敗、timeout、回傳空內容，系統不能直接放棄日報，而要退回模板版摘要。

fallback 至少包含：

- 日期
- 總交易數
- 勝率
- 已實現損益
- 今日最佳交易
- 今日最差交易
- 重點交易簡表

這樣即使 LLM 服務異常，使用者仍會收到有價值的日報。

## 與既有模組整合

### AutoTrader

[E:\claude code test\auto_trader.py](E:\claude code test\auto_trader.py) 不直接負責生成日報，只需提供：

- `recentTrades`
- `recentDecisions`
- `riskStatus`
- `portfolio snapshot`

### Notifier

[E:\claude code test\notifier.py](E:\claude code test\notifier.py) 繼續作為唯一 Telegram 發送出口。日報也必須走同一個通知管道，這樣可以沿用：

- rate limit
- backoff
- 降級聚合

### Main / Supervisor

盤後日報應由 supervisor 或 runtime 排程觸發，但不應阻塞盤中主流程。即使日報生成失敗，也不能影響隔日啟動。

## 測試策略

### 後端測試

- 測試重點交易挑選器
- 測試單筆交易短評 prompt payload
- 測試全日總結 prompt payload
- 測試 LLM 成功路徑
- 測試 LLM 失敗時 fallback 路徑
- 測試 Telegram 發送內容不超限

### 整合測試

- 模擬一個有多筆成交與 skip decision 的日內 session
- 斷言收盤後延遲流程會觸發日報
- 斷言最後會產生 Telegram 輸出
- 斷言失敗時仍有 fallback 摘要

## 驗證

實作完成後需至少執行：

- `npm test`
- `npm run build`
- `pytest -q`
- `python -m py_compile run.py sinopac_bridge.py notifier.py analyzer.py auto_trader.py main.py daily_reporter.py`

## 推薦實作順序

1. 新增 `daily_reporter.py`
2. 實作整日摘要整理器
3. 實作重點交易挑選器
4. 實作兩階段 LLM prompt builder
5. 實作 Telegram 發送整合
6. 補 fallback 模板摘要
7. 補 pytest 與整合測試
8. 跑完整驗證

## 為什麼這是正確的下一步

你現在的系統已經有：

- 結構化決策報告
- 多角色分析
- 多空辯論
- 交易回放

下一步最值得補的，不是再加更多盤中視覺，而是把這些資料轉成「你每天真的會看的盤後總結」。這會把系統從單純模擬交易平台，往真正的研究型交易工作台推進一大步。

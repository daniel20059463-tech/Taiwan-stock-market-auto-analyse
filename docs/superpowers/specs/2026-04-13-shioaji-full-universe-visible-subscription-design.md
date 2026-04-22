# Shioaji 全市場股票池與可見集高頻訂閱設計

**目標**

讓前端類群股與 `全部` 視圖可涵蓋台股 `上市 + 上櫃普通股` 全量股票，但只對目前畫面需要的股票做高頻即時報價訂閱，避免全市場高頻推流拖垮後端、WebSocket 與前端 worker。

---

## 範圍

本設計只處理：

- 啟動時從永豐 / Shioaji 動態建立完整股票池
- 以前後端協作方式維護「可見集高頻訂閱」
- 讓前端類群股可以依完整股票池顯示與篩選

本設計不處理：

- ETF / 權證 / 興櫃 / 指數 / 期權
- 類股主題策略調參
- 自選股持久化
- 排行榜演算法重構

---

## 問題定義

目前前端類群股與行情表的資料來源有兩個瓶頸：

1. 後端股票池只來自靜態 `DEFAULT_TW_SYMBOLS`，實際只覆蓋約百檔
2. 前端類群股分類高度依賴手寫 `Set` 與少量 sector code，無法覆蓋全市場

因此即使前端增加很多類群 tab，也只是對少量股票做前端篩選，不是真正的全市場類群股。

---

## 設計決策

### 決策 1：股票池改為 Shioaji 動態載入

啟動 collector 前，由後端直接向 Shioaji contracts 取得完整 `上市 + 上櫃普通股` 清單。

保留欄位：

- `symbol`
- `name`
- `market`
- `sector`
- `previousClose`
- `averageVolume`（若可得，否則合理預估）

排除：

- ETF
- 權證
- 興櫃
- 指數
- 期權
- 明顯不可交易或無效標的

### 決策 2：即時報價採「全量清單 + 可見集高頻訂閱」

不是全市場股票一起開高頻推流，而是：

- 全市場股票 metadata 全量載入
- 真正高頻即時只追蹤可見集

可見集定義：

- 當前選中的類群股列表
- 報價表目前實際渲染 / 可見區的股票
- 當前選中的單一股票
- 排序前 N 名（第一版固定 N=60）

### 決策 3：前端類群股主分類改為依 metadata 自動分群

前端主分類優先依後端 `market / sector` 生成與篩選，不再只靠前端手寫集合。

保留手寫主題群分類作為補充：

- `AI概念`
- `ABF載板`
- `CoWoS封裝`
- `伺服器AI`
- `低軌衛星`
- `CPO光通`
- `高股息`

這些主題群仍可透過 `Set` 做額外映射，但不再承擔全市場主分類的責任。

---

## 架構

### 後端

#### `run.py`

- 啟動時不再以 `DEFAULT_TW_SYMBOLS` 當主 universe
- 若使用 Sinopac collector，先動態抓完整股票池
- 只在 mock 模式下才 fallback 到靜態 universe

#### `sinopac_bridge.py`

新增兩類能力：

1. 動態股票池載入
2. 可見集高頻訂閱管理

collector 需維護：

- `all_instruments`: 全市場股票 metadata
- `visible_symbols`: 當前高頻訂閱股票集合

新增 WebSocket / worker 控制訊息：

- `set_visible_symbols`

行為：

- 收到新 visible set 時，對 Shioaji 調整 tick/bidask 訂閱
- 第一版只保證單一可見集，不處理多 client 各自不同 universe

### 前端

#### `data.worker.ts`

新增輸入：

- `SET_VISIBLE_SYMBOLS`

worker 收到後轉成後端 WebSocket 訊息：

```json
{
  "type": "set_visible_symbols",
  "symbols": ["2330", "2317", "..."]
}
```

#### `QuoteTable.tsx`

- 改成依完整股票池與分類 metadata 篩選
- 不再只吃目前少量 universe
- 保留主題群分類，但讓一般類股依 sector 自動映射

#### `Dashboard.tsx`

- 切換類群股時更新 visible set
- 選取股票時將該股票強制加入 visible set

---

## 類群股策略

### 一般分類

第一版採兩層分類：

- `全部`
- `上市`
- `上櫃`
- 各 sector 對應類股

### 主題分類

保留現有前端主題群：

- `AI概念`
- `ABF載板`
- `CoWoS封裝`
- `伺服器AI`
- `低軌衛星`
- `CPO光通`
- `高股息`

若股票同時屬於主題群與一般類股，允許重複出現在不同分類。

---

## 可見集規則

第一版規則：

1. 目前選中的類群股排序前 60 檔
2. 目前選中的股票
3. 當前報價表實際已渲染區塊內的股票（若能容易取得）

去重後形成最終 visible set。

若前端暫時無法準確拿到 viewport，可先採：

- 選中類群股前 60 檔
- 選中股票

這是第一版可接受退化。

---

## 錯誤處理

### 股票池載入失敗

- 記錄 warning
- fallback 到 `DEFAULT_TW_SYMBOLS`
- 前端照常啟動

### 可見集更新失敗

- 保留上一版 visible set
- 不讓前端中斷
- 在後端 log 記錄訂閱更新失敗原因

### 某些股票 metadata 不完整

- 若缺 `name`，退回 `symbol`
- 若缺 `sector`，歸類到 `其他`
- 若缺 `previousClose / averageVolume`，做合理預估

---

## 測試策略

### Python

新增 / 擴充：

- `test_sinopac_bridge.py`
- `test_run.py`

需要覆蓋：

1. 載入 universe 時能正確排除非普通股
2. 股票池載入失敗時 fallback 到靜態 universe
3. `set_visible_symbols` 會更新 collector 高頻訂閱集合
4. 重複送相同 visible set 不會重複做昂貴操作

### 前端

新增 / 擴充：

- `src/components/QuoteTable.test.tsx`
- `src/components/Dashboard.test.tsx`
- `src/workers/data.worker.test.ts`（若目前有對應測試慣例）

需要覆蓋：

1. 類群股可依完整 metadata 做篩選
2. 切換分類時會送出 `SET_VISIBLE_SYMBOLS`
3. 選取股票時該股票會被併入 visible set

---

## 驗收標準

完成後需滿足：

1. `全部` 類群股不再只顯示 133 檔靜態股票
2. 類群股可涵蓋 `上市 + 上櫃普通股`
3. 系統不會對全市場股票全部開高頻訂閱
4. 切換類群股後，可見集會同步更新
5. 前端表格與主圖仍保持流暢可用


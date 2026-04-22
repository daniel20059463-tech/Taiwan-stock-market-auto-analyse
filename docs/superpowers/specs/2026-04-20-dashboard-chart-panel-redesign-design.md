# Dashboard Chart Panel Redesign Design

## Goal

將 Dashboard 首頁右側主圖表卡改成台股看盤風格的深色技術圖面板，支援 `日線 / 週K / 月K` 三種模式，並維持底部成交量副圖與明確空狀態提示。

## Scope

本次只修改 Dashboard 右側主圖表卡。

納入範圍：

- 頂部工具列樣式與文案
- `日線 / 週K / 月K` 三模式切換
- MA 圖例列顯示規則
- 主圖與成交量副圖的視覺與資料綁定
- 無選股 / 無資料的覆蓋提示
- 對應前端測試

不納入範圍：

- 左側自選股清單
- 持倉、帳務、其他資訊卡
- 新增後端 API
- 修改策略、交易、推播流程

## Existing Context

目前圖表主要集中在 `src/components/Dashboard.tsx`，已使用 `lightweight-charts` 建立：

- 主圖 chart
- 成交量 histogram 副圖
- line series
- candlestick series
- MA line series

目前模式是 `live / history`，不符合此次需求。資料來源已存在兩條：

- `sessionCache` / `liveTick`：盤中 session 與即時 tick
- `historyCache`：歷史 K 線資料

因此本次不新增後端資料協定，改以前端重組資料與調整 UI 為主。

## UI Structure

### 1. 頂部工具列

- 高度固定 `34px`
- 背景色 `#101419`
- 左側：
  - 股票代號，白色粗體
  - 週期標籤，灰色小字，例如 `日線`
- 右側：
  - `日線`
  - `週K`
  - `月K`
- active 狀態：
  - 高亮邊框
  - 字色較亮
  - 非 active 維持深色底與灰字

### 2. MA 圖例列

- 高度固定 `26px`
- 只在 `週K / 月K` 顯示
- 顯示三個文字標籤：
  - `MA5`：黃
  - `MA10`：藍
  - `MA20`：紫
- `日線` 模式完全隱藏，不保留空白

### 3. 主圖表區

- 整體深色主題
- 背景接近黑色
- 格線為深灰色
- 保留主圖 + 成交量副圖的上下結構

#### 日線模式

- 使用藍色平滑折線
- 折線下方使用由上而下的漸層填色
- 底部顯示成交量長條圖
- 不顯示 K 棒
- 不顯示 MA 線

#### 週K / 月K 模式

- 使用紅漲綠跌的 candlestick
- 疊加三條 MA 線：
  - `MA5`
  - `MA10`
  - `MA20`
- 底部顯示成交量長條圖

## Data Rules

### Mode Mapping

將既有 `live / history` 模式改為：

- `daily`
- `weekly`
- `monthly`

### 日線資料

優先順序如下：

1. `sessionCache` 中當日 session candles
2. `selectedRow.candles`
3. `liveTick.activeCandle` 所代表的最新盤中 bar

日線模式只使用盤中或當日資料，不回退成歷史日 K。

### 週K / 月K 資料

- 基礎資料來源為 `historyCache` 中的歷史日 K
- 在前端以日 K 聚合為週 K 或月 K
- 聚合規則：
  - `open` 取第一根
  - `close` 取最後一根
  - `high` 取最大值
  - `low` 取最小值
  - `volume` 累加
- 週 K 以日曆週聚合
- 月 K 以年-月聚合

### 均線規則

- `週K / 月K` 顯示 `MA5 / MA10 / MA20`
- `日線` 不顯示任何 MA 線，也不顯示 MA 圖例

## Empty States

覆蓋提示文案固定如下：

- 未選股票：`選取股票後顯示圖表`
- 日線無資料：`尚無當日資料`
- K 棒無資料：`尚無K線資料`

覆蓋提示顯示在主圖表區中央，成交量區不獨立顯示另一份提示。

## Visual Details

- 工具列背景：`#101419`
- 面板背景：近黑色
- 格線：深灰
- 日線：
  - 線色：亮藍
  - 區域填色：藍色半透明漸層
- K 棒：
  - 漲：紅
  - 跌：綠
- MA 顏色：
  - `MA5`：黃
  - `MA10`：藍
  - `MA20`：紫

## Component Boundaries

### `src/components/Dashboard.tsx`

主要修改檔案，負責：

- 新的 chart mode state
- 週期切換 UI
- MA 圖例列
- 圖表資料選擇與聚合
- 圖表 series 顯示控制
- 空狀態 overlay

### `src/components/Dashboard.test.tsx`

更新測試，覆蓋：

- 三個週期按鈕存在
- `日線` 隱藏 MA 圖例
- `週K / 月K` 顯示 MA 圖例
- 空狀態提示正確

## Implementation Notes

- 不新增新頁面或新元件檔，先在 `Dashboard.tsx` 內完成
- 若現有亂碼文案干擾測試，可一併清理與圖表卡直接相關的文案
- 不處理左側清單或其他卡片的中文全面整理，避免超出範圍

## Verification

- `npm run typecheck`
- `npm run build`
- `src/components/Dashboard.test.tsx`

## Scope Check

此 spec 只覆蓋單一子系統：Dashboard 右側圖表卡。範圍足夠聚焦，可直接進入單一 implementation plan。

# 台股模擬交易系統放空 / 回補（最小入侵）設計

日期：2026-04-04

## 目標

在不重構 `AutoTrader` 主架構的前提下，補上第一版可用的台股日內放空 / 回補能力，讓系統能對「利空新聞確認 + 技術轉弱」的標的建立空方模擬部位，並在停損、停利或收盤時回補。

這一版的核心原則是：

- 採用最小入侵方案，直接在現有 `AutoTrader` 補齊空方四個方法
- 不做大規模抽象化
- 先累積真實回放與交易樣本，再評估是否進行第二階段多空共用重構

## 為什麼不先重構

目前 `AutoTrader` 類別才剛清掉一份舊版 `_evaluate_buy` 死碼，代表類別邊界與責任仍在收斂中。若此時直接做多空抽象化，風險是把現有複雜度包進更深的抽象層，讓後續除錯更困難。

因此第一版明確採用：

- 先把空方能力做出來
- 用測試鎖住多空核心行為
- 等交易邏輯、風控與回放資料都穩定後，再考慮第二階段抽象化

## 範圍

### 納入

1. 補上空方四個方法
   - `_evaluate_short`
   - `_paper_short`
   - `_check_short_exit`
   - `_paper_cover`

2. 讓 `on_tick()` 在既有做多流程旁，能評估空方進場機會

3. 讓 `DecisionReport`、`TradeRecord`、回放資料、盤後日報都能正確記錄 `short / cover`

4. 收盤時若仍有空方部位，必須和多方一樣強制平倉

5. 補 pytest 驗證：
   - 空方進場
   - 空方停損
   - 空方停利
   - EOD 強制回補
   - `DecisionReport` 與回放資料結構

### 不納入

- 空方追蹤停利
- 借券成本、融券保證金、券源限制等真實券商規則
- 多空共用抽象層重構
- UI 大改版

## 第一版空方進場條件

空方採用「利空新聞確認 + 技術轉弱」的混合條件：

- `sentiment_score < -0.25`
- 盤中跌幅 `<= -1.5%`
- 成交量放大，通過既有 `volume confirmed`
- 風控放行
  - 持倉數未超上限
  - 未觸發 `weekly halt`
  - 未觸發日內停機

### 為什麼用 -1.5%

此策略不是純追空動能，而是先有利空新聞與負向輿情支撐，再由盤中弱勢確認。因此不需要等到跌幅完全展開到 `-2%` 甚至更深才允許進場。

`-1.5%` 的定位是：

- 比一般波動更有弱勢辨識度
- 又不會像純動能追空那樣太晚進場

## 第一版空方出場條件

第一版採對稱型，不做空方追蹤停利：

- 停損回補
- 停利回補
- 收盤強制回補

### 為什麼不先做空方追蹤停利

台股常見「跌停打開後瞬間反彈，再續跌」的盤中型態。若一開始就加空方追蹤停利，容易在短暫急彈時被洗出，導致：

- 先在反彈中回補
- 又錯過後續主要跌段

因此第一版先用固定停損 / 停利，比較穩定，也更容易 debug。

## 資料模型

### 持倉

資料模型只做一處實質變動：

- `PaperPosition` 新增 `side: "long" | "short"`

其餘欄位延用既有：

- `entry_price`
- `shares`
- `stop_price`
- `target_price`
- `entry_ts`
- `peak_price`
- `trail_stop_price`

第一版雖然不使用空方追蹤停利，但保留既有欄位，不另外拆新型別。

### 成交紀錄

`TradeRecord` 不新增欄位，只擴充合法值：

- 空方進場使用 `action="SHORT"`
- 空方回補使用 `action="COVER"`

### 決策報告

`DecisionReport` 不新增欄位，只擴充合法值：

- 放空進場使用 `decision_type="short"`
- 空方平倉使用 `decision_type="cover"`

並維持既有欄位：

- `bull_case`
- `bear_case`
- `risk_case`
- `bull_argument`
- `bear_argument`
- `referee_verdict`
- `debate_winner`

## 模組變更

### `auto_trader.py`

#### 1. `on_tick()`

現況：

- 持倉存在時，檢查多方出場
- 無持倉時，符合條件才 `_evaluate_buy()`

改為：

```python
if symbol in self._positions and self._positions[symbol].side == "long":
    await self._check_exit(symbol, price, ts_ms)
elif symbol in self._positions and self._positions[symbol].side == "short":
    await self._check_short_exit(symbol, price, ts_ms)
elif symbol not in self._positions:
    if opening_or_momentum_long_condition:
        await self._evaluate_buy(symbol, price, change_pct, ts_ms, payload)
    if short_condition:
        await self._evaluate_short(symbol, price, change_pct, ts_ms, payload)
```

同一標的不能同時有多空。

第一版明確採用：

- 多方與空方共用同一個 `self._positions` dict
- 用 `PaperPosition.side` 區分方向

不新增 `self._short_positions`，因為共用同一個 dict 能天然保證：

- 同一標的同一時間只能有一種方向
- `on_tick()` 分支更簡單
- EOD flatten、回放、帳本彙總邏輯都比較一致

#### 2. `_evaluate_short()`

功能：

- 根據負向情緒、跌幅、量能、風控條件，決定是否建立空方部位
- 失敗時也要留下 `skip` 類型 `DecisionReport`

輸出：

- 若進場，產生 `decision_type="short"` 的 `DecisionReport`
- 若略過，也要保留結構化理由

#### 3. `_paper_short()`

功能：

- 建立 `side="short"` 的 `PaperPosition`
- 寫入 `SHORT` 類型 `TradeRecord`
- 發送模擬交易通知

#### 4. `_check_short_exit()`

功能：

- 若價格反向上漲到停損價，回補
- 若價格下跌到停利價，回補

第一版不使用空方 trail stop。

#### 5. `_paper_cover()`

功能：

- 結束空方部位
- 計算空方損益
- 寫入 `COVER` 類型 `TradeRecord`
- 生成 `decision_type="cover"` 的 `DecisionReport`
- 發送回補通知

#### 6. `_close_all_eod()`

需同時支援：

- 多方用 `SELL`
- 空方用 `COVER`

收盤平倉後，盤後日報與回放都必須正確顯示空方交易。

### `risk_manager.py`

第一版不新增獨立空方風控規則，沿用現有：

- 最大持倉數
- 日損上限
- 五日損失上限
- 單筆部位上限

但需確認 `can_buy()` 這類命名不會阻礙空方進場。第一版可接受：

- 保留現有 `can_buy()`，由空方暫時共用

若之後行為開始分歧，再拆成更中性的 `can_open_position()`。

### `multi_analyst.py`

不改架構，只讓既有分析層在 `decision_type="short" / "cover"` 時輸出更合理的空方敘述。

## 損益邏輯

多方：

- `SELL pnl = (sell_price - entry_price) * shares - costs`

空方：

- `COVER pnl = (entry_price - cover_price) * shares - costs`

也就是空方價格跌越多，損益越高。

需特別確認 `risk_manager.calc_net_pnl()` 目前簽名是否適合直接重用。若其內部邏輯寫死為多方方向，第一版允許在 `auto_trader.py` 內包一層空方專用損益計算，不強迫先改 `risk_manager.py` 介面。

交易成本第一版仍沿用現有 round-trip cost 模型，不額外加入融券費用。

## 回放與績效

### 回放頁

需能顯示：

- `SHORT` 進場
- `COVER` 出場
- 空方的支持理由 / 反對理由 / 裁決

### 績效頁

第一版不重做整頁，但至少要確保：

- `SHORT` / `COVER` 交易不會被排除
- 當日損益與勝率能納入空方結果

## 測試策略

新增或擴充 pytest：

1. 空方進場成功
   - sentiment 負向
   - 跌幅 <= -1.5%
   - volume confirmed
   - risk allowed
   - 產生 `short` 決策與 `SHORT` 成交

2. 空方因情緒不足被略過
   - 留下 `skip` 決策報告

3. 空方停損回補
   - 價格上漲到 stop
   - 產生 `COVER`

4. 空方停利回補
   - 價格下跌到 target
   - 產生 `COVER`

5. EOD 強制回補
   - 空方部位在 13:25 後被平掉

6. 回放資料與 `DecisionReport` 正確
   - `decision_type="short"` / `"cover"`
   - `action="SHORT"` / `"COVER"`

## 驗收標準

1. 系統能在盤中對符合條件的利空標的建立空方模擬部位
2. 空方部位能在停損、停利、收盤三種情況下回補
3. 不會留倉過夜
4. 回放頁與盤後日報能看到空方交易
5. 既有多方測試不得回歸失敗

## 第二階段（這次不做）

等多空樣本累積後，再考慮：

- 多空共用進出場抽象層
- 空方追蹤停利
- 空方專屬風控
- 更完整的空方績效歸因

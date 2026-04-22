# Market Calendar Yearly Data Design

日期：2026-04-18  
狀態：Approved

## 1. 目標

把交易日曆從單一年份硬寫資料，擴成可按年份分檔載入的結構。  
第一步先保持 `2026` 可用，並預留 `2027` 資料檔骨架，讓後續官方日曆公告後只需補資料，不需再改 loader 邏輯。

## 2. 設計原則

- 日曆屬於資料，不是策略邏輯
- loader 只負責：
  - 找檔
  - 讀檔
  - 判斷日期是否為已確認開市日
- 若年份資料不存在或日期不在白名單：
  - 一律視為不可自動啟動

## 3. 資料結構

每年一檔：

- `data/market_calendar/twse_open_dates_2026.json`
- `data/market_calendar/twse_open_dates_2027.json`

格式固定：

```json
{
  "exchange": "TWSE",
  "timezone": "Asia/Taipei",
  "source_note": "...",
  "open_dates": ["YYYY-MM-DD"]
}
```

`2027` 在官方未公告前可以先是空白骨架：

```json
{
  "exchange": "TWSE",
  "timezone": "Asia/Taipei",
  "source_note": "Placeholder until official 2027 TWSE trading calendar is published.",
  "open_dates": []
}
```

## 4. Loader 行為

`market_calendar.py` 改成：

- 依日期年份決定讀哪一個 json
- 用快取避免重複讀檔
- 缺檔或空白資料時回 `False`

## 5. 與現有系統整合

- `run.py`
  - 啟動前用 loader 檢查今天是否可啟動 live engine
- `auto_trader.py`
  - `_is_trading_hours()` 除時間外，也檢查當日是否為已確認開市日

## 6. 驗證

至少覆蓋：

- 2026 已知開市日回 `True`
- 2026 已知休市日回 `False`
- 2027 未公告日期在空白骨架下回 `False`
- 年份切換時 loader 會讀對檔案


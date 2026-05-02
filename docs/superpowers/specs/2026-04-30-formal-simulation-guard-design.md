# Formal Simulation Guard Design

## Goal

讓明天的正式模擬只在「100 萬本金、永豐 live feed、正式盤後日報」三個條件同時成立時執行；若任一條件不成立，系統應明確中止或拒絕送正式 Telegram。

## Scope

- 新增一個正式模擬 preflight 檢查入口。
- 在 runtime 啟動時強制檢查正式模擬條件。
- 在日報送出前驗證 payload 來源，避免任何測試 payload 送到正式 chat。

## Non-Goals

- 不重寫交易策略。
- 不處理 Shioaji `contract_not_found` 的完整資料品質問題。
- 不新增第二個測試 chat。

## Design

### 1. Preflight

新增 `formal_simulation.py`，集中檢查：

- `SINOPAC_MOCK=false`
- `ACCOUNT_CAPITAL` 未設定時視為 `1_000_000`，若有設定則必須等於 `1_000_000`
- Telegram bot token / chat id 存在且可通過 `getMe` / `getChat`
- sector rotation cache 存在，且最新日期等於預期上一個開市日

提供：

- `run_formal_simulation_preflight(...) -> FormalSimulationPreflightResult`
- CLI 腳本 `scripts/run_formal_simulation_preflight.py`

### 2. Runtime guard

在 `run.py` 啟動 live runtime 時執行 preflight。

- `SINOPAC_MOCK=true` 時不執行正式模擬 guard
- `SINOPAC_MOCK=false` 時 preflight 失敗就直接中止啟動
- log 要清楚列出失敗原因

### 3. Daily report source guard

正式 Telegram 日報必須只接受真實 EOD payload。

- `build_daily_report_payload(...)` 補 `source="runtime_eod"`
- `DailyReporter.build_and_send(...)` 預設要求 `source == "runtime_eod"`
- 非 `runtime_eod` payload 若嘗試送出，直接拋錯

這能避免測試腳本或人工 payload 送進正式 chat。

## Testing

- `formal_simulation.py` 單元測試：
  - 100 萬本金通過
  - mock 模式失敗
  - stale sector cache 失敗
  - Telegram 驗證失敗
- `daily_reporter.py` 單元測試：
  - `runtime_eod` payload 可送
  - 非 `runtime_eod` payload 被拒絕
- `run.py` / `runtime_bootstrap` 整合測試：
  - live mode preflight fail 時拒絕啟動

## Success Criteria

- 正式 live runtime 在條件不符時不會啟動。
- 正式 Telegram chat 不再接受測試日報。
- 明天開盤前可手動跑一次 preflight，得到明確 PASS/FAIL 結果。

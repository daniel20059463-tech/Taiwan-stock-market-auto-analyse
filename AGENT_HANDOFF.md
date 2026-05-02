# AGENT_HANDOFF

最後更新時間：
- `2026-04-28 接手：Claude Code`

目前主責 agent：
- `Claude Code`

目前分支：
- `main`

目前 commit：
- `d04ecf2`

工作模式：
- `盤中穩定度修正`
- `sector rotation / swing strategy integration`
- `paper trading live monitoring`

**1. 當前目標**
- 提高 `Sinopac/Shioaji` live feed 的穩定度，特別是 `Token is expired` 後的恢復能力。
- 讓 `sector rotation` 真正可用於 `retail_flow_swing` 的 live runtime。
- 維持 paper trade 可持續運行，直到下一次 `401` 發生時能觀察自動恢復行為。

完成條件：
- `8765` 持續提供行情。
- `sector_rotation_signals.json` 可正常驅動策略。
- 下一次 `Token is expired` 發生後，log 要能看到 reconnect 成功，不再只是卡死。

**2. 本輪不做的事**
- 不做前端 UI 調整。
- 不做回測報表整理。
- 不做 PostgreSQL 正式落盤修復。
- 不做策略大改版，只做 live 穩定度與 sector gate 必要修正。

**3. 目前狀態**
- 已完成：
  - 修好 `sector_data.py`，不再單點依賴失效的 TPEX openapi。
  - `full_sector_map.json` 已可用 Shioaji universe 補齊到 `1966` 檔。
  - `build_sector_rotation_signals.py` 已能成功產出 `2026-04-27` 的 signals。
  - `runtime_bootstrap.py` 的 sector cache stale 判定已改成符合 swing 的 T+1 邏輯。
  - `sector_rotation_state_machine.py` 已做一輪門檻校準。
  - `sinopac_bridge.py` 已補：
    - token expired helper
    - auth probe
    - sync watchdog thread
  - `test_sinopac_bridge.py` 全綠。
  - paper trade 目前已有 1 筆部位：`2344`
  - **[Claude Code 新增]** 修復 Shioaji Max Subscriptions Exceeded 根本原因：
    - `sinopac_bridge.py` line 215：`visible_symbols` 改為從 `set()` 啟動，不再全量訂閱 1959 支
    - 啟動時呼叫 `auto_trader.get_required_symbols()` 取得 watchlist + 持倉，只訂閱實際需要的股票
    - `auto_trader.py`：`__init__` 末尾主動呼叫 `_build_preopen_watchlist()`，確保 bridge 啟動時已有 watchlist
    - `auto_trader.py`：新增 `get_required_symbols()` 方法回傳 watchlist + open positions
    - `test_sinopac_bridge.py`、42 passed
- 進行中：
  - 等待下一次真實 `401 / Token is expired` 事件，驗證新 reconnect 鏈是否真的接住。
- 阻塞中：
  - 尚未取得「live 401 後 reconnect 成功」的實際 log 證據。
  - `trade_tape` 之前有 rows=0 的退化現象，這輪沒有優先處理。

**4. 關鍵檔案**
- 主要修改檔案：
  - [sector_data.py](E:\claude code test\sector_data.py)
  - [runtime_bootstrap.py](E:\claude code test\runtime_bootstrap.py)
  - [sinopac_bridge.py](E:\claude code test\sinopac_bridge.py)
  - [sector_rotation_state_machine.py](E:\claude code test\sector_rotation_state_machine.py)
  - [scripts/build_sector_rotation_signals.py](E:\claude code test\scripts\build_sector_rotation_signals.py)
- 相關測試：
  - [tests/test_sector_data.py](E:\claude code test\tests\test_sector_data.py)
  - [tests/test_runtime_bootstrap.py](E:\claude code test\tests\test_runtime_bootstrap.py)
  - [tests/test_sector_rotation_state_machine.py](E:\claude code test\tests\test_sector_rotation_state_machine.py)
  - [test_sinopac_bridge.py](E:\claude code test\test_sinopac_bridge.py)
- 相關資料：
  - [data/full_sector_map.json](E:\claude code test\data\full_sector_map.json)
  - [data/sector_rotation_signals.json](E:\claude code test\data\sector_rotation_signals.json)
  - [data/paper_positions.json](E:\claude code test\data\paper_positions.json)

**5. 已驗證內容**
- 指令：
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_sector_data.py tests\test_sector_rotation_signal_builder.py tests\test_sector_rotation_signal_cache.py tests\test_sector_rotation_state_machine.py tests\test_sector_rotation_strategy_integration.py tests\test_runtime_bootstrap.py
.\.venv\Scripts\python.exe -m pytest -q test_sinopac_bridge.py
.\.venv\Scripts\python.exe .\scripts\build_sector_rotation_signals.py --trade-date 2026-04-27 --output .\data\sector_rotation_signals.json
```
- 結果：
  - `sector / runtime / state machine` 相關測試：`19 passed`
  - `sinopac_bridge`：`39 passed`
  - `2026-04-27` sector signals：可成功產出

**6. 尚未驗證內容**
- 尚未拿到新 session 在 `Token is expired` 發生後，自動 reconnect 成功的 live log 證據。
- 尚未重新驗證 `trade_tape` 是否恢復穩定。
- 尚未重新驗證 `lastNonEntryReasons` 是否已明顯降低 `sector_state_watch` 比例。

**7. 已知風險**
- 風險 1：
  - 現象：`Token is expired` 仍會在 live log 出現。
  - 影響：行情可能停更，策略可能卡在退化狀態。
  - 暫時處理：已補 callback + auth probe + sync watchdog，但仍待 live 事件驗證。
- 風險 2：
  - 現象：`paper position` 正式 DB 落盤仍失敗，會 fallback 到本機檔案。
  - 影響：缺少正式 DB persistence。
  - 暫時處理：使用 [data/paper_positions.json](E:\claude code test\data\paper_positions.json) 本機快照恢復。
- 風險 3：
  - 現象：最新 sector state 分布仍偏保守。
  - 影響：策略可能出單偏少。
  - 暫時處理：已做第一輪校準，但未進一步大幅放寬。

**8. 下一步**
1. 持續監看最新 live log，等下一次 `Token is expired`。
2. 確認 log 內是否出現：
   - `Auth probe detected expired token`
   - `Shioaji reconnect completed after auth probe expiry`
   - 或 `永豐 API 重新連線成功（sync watchdog）`
3. 若沒有出現，就回頭檢查：
   - [sinopac_bridge.py](E:\claude code test\sinopac_bridge.py)
   - 最新 [`run_live_*.err.log`](E:\claude code test\logs)

**9. 若另一台 agent 要接手**
- 接手前先讀：
  - [AGENT_HANDOFF.md](E:\claude code test\AGENT_HANDOFF.md)
  - [data/sector_rotation_signals.json](E:\claude code test\data\sector_rotation_signals.json)
  - 最新 `run_live_*.err.log`
- 接手前先確認：
```powershell
git status --short
git branch --show-current
git rev-parse --short HEAD
```
- 不要直接動：
  - [auto_trader.py](E:\claude code test\auto_trader.py) 的策略核心，除非是明確要改 entry/exit 邏輯
  - 前端檔案，除非需求轉向 UI

**10. 盤中 / live 類專案額外欄位**
- 今日交易日狀態：
  - `open`
- 後端狀態：
  - `8765 listening = true`
- 前端狀態：
  - 未驗證，不作為本輪目標
- 最新 runtime log：
  - [run_live_20260428_104229.err.log](E:\claude code test\logs\run_live_20260428_104229.err.log)
- 最新 paper 狀態：
  - `positions = 1`
  - `symbol = 2344`
  - `entryPrice = 94.99`
  - `recentTrades = []`

**11. 更新規則**
- 每完成一個可驗證步驟就更新這份檔案。
- 若切換目標，例如從 live feed 穩定度轉回回測或 UI，必須先改這份檔案。
- 以這份檔案 + 最新 commit + 最新 log 為交接依據，不以聊天紀錄為準。

# 專案說明

台股自動交易系統，策略核心為 `retail_flow_swing`，整合籌碼分析、sector rotation、風控機制與回測框架。

---

## 🔄 Agent 工作分配區

> **規則：開始任何工作前，先讀這個區塊。若目標模組已有人佔用，等對方完成並清除後再開始。**
> 完成後請將自己的紀錄移除，並執行 `git commit` 留下紀錄。

### 目前佔用中

| Agent | 負責模組 / 檔案 | 任務描述 | 開始時間 |
|-------|----------------|----------|----------|
| _(空) | _(空)_ | _(空)_ | _(空)_ |

### 使用方式

1. **開始前**：在表格新增一行，填入你的 agent 名稱、負責的檔案、任務描述、時間
2. **進行中**：不要動其他 agent 佔用的檔案
3. **完成後**：移除自己那行，執行 `git commit` 讓另一台 agent 可以 `git pull` 拿到最新狀態

### 範例

| Agent | 負責模組 / 檔案 | 任務描述 | 開始時間 |
|-------|----------------|----------|----------|
| Claude Code | `risk_manager.py` | 調整最大回撤閾值邏輯 | 2026-04-28 14:00 |
| Codex | `strategy_tuner.py` | 優化參數搜尋範圍 | 2026-04-28 14:05 |

---

## 核心模組對照

| 模組 | 主要檔案 |
|------|---------|
| 策略核心 | `retail_flow_strategy.py`, `strategy_runtime.py` |
| 風控 | `risk_manager.py` |
| 回測 | `backtest.py`, `run_backtest.py`, `strategy_tuner.py` |
| 籌碼資料 | `institutional_flow_provider.py`, `daily_price_cache.py` |
| Sector Rotation | `sector_rotation_state_machine.py`, `sector_rotation_signal_builder.py`, `sector_rotation_signal_cache.py` |
| 出場判斷 | `swing_exit_judge.py` |
| 下單橋接 | `sinopac_bridge.py`, `auto_trader.py` |
| 報告 | `daily_reporter.py`, `trading/reporting.py` |
| 前端 | `src/components/`, `src/store.ts` |

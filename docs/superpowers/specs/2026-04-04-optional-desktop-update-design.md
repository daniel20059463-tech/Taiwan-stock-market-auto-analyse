# 桌面版可選擇更新提示設計

> 日期：2026-04-04
> 主題：Windows 桌面 App 啟動時檢查 GitHub Releases 新版本，提示使用者可選擇更新或稍後再說

## 目標

當使用者打開桌面 App 時，系統在背景檢查 GitHub Releases 是否存在新版本。如果有新版，主畫面顯示更新提示，不阻塞使用者操作，並提供「立即更新」與「稍後再說」兩個選項。

## 設計原則

1. 主畫面先開，不因更新檢查阻塞。
2. 更新提示是可選的，不強迫立刻更新。
3. 使用者本次選擇「稍後再說」後，本次啟動不再重複提醒。
4. 使用者選擇「立即更新」時，交由 Tauri v2 updater 從 GitHub Releases 下載並啟動安裝流程。
5. 若更新檢查失敗，主畫面維持正常，不跳錯誤對話框，只記錄狀態供 UI 需要時顯示。

## 技術方案

採用 Tauri v2 官方 updater plugin，更新來源使用 GitHub Releases。

### 後端（Tauri）

需要在 `src-tauri/tauri.conf.json` 與 `src-tauri/src/main.rs` 加入 updater plugin 設定：
- 啟用 updater plugin
- 設定更新端點（GitHub Releases JSON / latest endpoint）
- 設定 Windows 安裝器模式為 `basicUi`
- 允許前端呼叫 updater 相關 API

### 前端

新增桌面更新橋接與提示元件：
- `src/desktopUpdater.ts`
- `src/components/DesktopUpdateBanner.tsx`

前端會在桌面環境下：
1. 啟動後背景檢查更新
2. 若有新版，顯示提示列
3. 點擊「立即更新」後進行下載與安裝
4. 點擊「稍後再說」後，本次啟動隱藏提示

### UI 行為

提示列文案使用全中文：
- 標題：`發現新版本`
- 內容：`目前版本 0.x.x，可更新為 0.y.y。你可以現在更新，或稍後再說。`
- 按鈕：`立即更新`、`稍後再說`

安裝期間可顯示：
- `正在下載更新…`
- `下載完成，準備安裝…`

若檢查失敗：
- 不彈錯
- 可選擇只在開發者狀態區顯示 `更新檢查失敗`

## 狀態模型

前端新增更新狀態：
- `idle`
- `checking`
- `available`
- `downloading`
- `installing`
- `upToDate`
- `error`
- `dismissed`

需要包含欄位：
- `currentVersion`
- `availableVersion`
- `notes`
- `status`
- `message`

## GitHub Releases 依賴

此功能正式可用的前提：
1. 專案已有 GitHub repository
2. 每次桌面版發版會建立 GitHub Release
3. Release 內包含 Tauri updater 所需產物與 metadata
4. 對應 public key 已配置進 Tauri updater 設定

若目前尚未建立 GitHub Releases 發版流程，第一版可先完成：
- UI 提示元件
- 本地 updater API 串接
- 設定骨架

等 GitHub Release 流程就緒後再正式啟用。

## 錯誤處理

1. GitHub 無法連線
   - 不阻塞 App
   - 更新狀態設為 `error`

2. 查無新版本
   - 更新狀態設為 `upToDate`
   - 不顯示提示列

3. 下載失敗
   - 保留主畫面
   - 提示 `更新下載失敗，請稍後再試`

4. 安裝觸發失敗
   - 顯示 `更新安裝失敗`
   - 不關閉主畫面

## 測試策略

### 前端測試
- 桌面環境且有新版時，顯示更新提示
- 點擊「稍後再說」後隱藏提示
- 點擊「立即更新」後進入 downloading / installing 狀態
- 非桌面環境不顯示提示
- 無新版時不顯示提示

### 端對端驗證
- `npm test`
- `npm run build`
- `npm run desktop:package`

## 驗收標準

1. 桌面 App 啟動時可自動檢查更新
2. 若有新版，主畫面顯示中文更新提示
3. 使用者可選擇立即更新或稍後再說
4. 選擇稍後再說後，本次啟動不再重複提示
5. 選擇立即更新後，能觸發 Tauri updater 安裝流程
6. 無新版或更新檢查失敗時，不影響 App 正常使用

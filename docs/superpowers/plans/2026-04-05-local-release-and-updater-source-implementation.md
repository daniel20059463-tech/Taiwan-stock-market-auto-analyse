# 本機 GitHub Release 與 Updater 來源實作計畫

> 日期：2026-04-05
> 對應 spec：`docs/superpowers/specs/2026-04-05-local-release-and-updater-source-design.md`

## 目標

完成以下能力：

1. 桌面版 updater 改為讀正式 GitHub Releases `latest.json`
2. 本機可用腳本完成：
   - 檢查前提
   - 打包桌面版
   - 產生 `latest.json`
   - 建立 draft release
   - 上傳資產
   - 發佈正式 release
3. 缺少必要金鑰或產物時，腳本安全中止
4. 若 draft 建立後流程失敗，會清除 draft release 與 tag

## 任務分解

### 1. 固化 updater 設定

- 更新 `src-tauri/tauri.conf.json`
  - endpoint 指向正式 GitHub Releases `latest.json`
  - `bundle.createUpdaterArtifacts = true`
  - pubkey 改成明確 placeholder，供 release 腳本在打包前注入

### 2. 修正 updater 文案與狀態字串

- 修正 `src-tauri/src/updater.rs`
- 修正 `src/desktopUpdater.ts`
- 修正 `src/components/DesktopUpdateBanner.tsx`
- 目標是避免更新提示與錯誤訊息出現亂碼

### 3. release 腳本

- 新增 `scripts/release_desktop.ps1`
- 腳本負責：
  - 驗證 `gh auth status`
  - 驗證 repo 可存取
  - 驗證 target ref 存在於 GitHub
  - 驗證：
    - `TAURI_SIGNING_PRIVATE_KEY`
    - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
    - `TAURI_UPDATER_PUBLIC_KEY`
  - 暫時注入 updater pubkey 到 `tauri.conf.json`
  - 呼叫 `npm run desktop:package`
  - 檢查 `.msi`、`.exe`、`.nsis.zip`、`.nsis.zip.sig`
  - 組裝 `latest.json`
  - 建立 draft release
  - 上傳所有資產
  - 驗證資產齊全後 publish
  - 失敗時 cleanup draft release 與 tag

### 4. 驗證

- `npm test`
- `npm run build`
- `npm run desktop:package`
- `scripts/release_desktop.ps1 -DryRun`

## 實作順序

1. updater 設定與文案修正
2. release 腳本
3. dry-run 驗證
4. 若環境允許，再做真實 release 驗證

## 已知風險

- 若 `TAURI_UPDATER_PUBLIC_KEY` 未配置，無法產生可用 updater build
- 若尚未在本機生成 updater artifact，需先依實際產物檔名驗證腳本假設
- 若 GitHub repo 尚無對應 target ref，release 腳本會安全中止

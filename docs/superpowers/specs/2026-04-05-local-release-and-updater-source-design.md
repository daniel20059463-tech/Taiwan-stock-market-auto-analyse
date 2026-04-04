# 本機自動發 GitHub Release 與桌面版更新來源設計

> 日期：2026-04-05
> 主題：本機打包完成後，自動建立正式 GitHub Release，並作為桌面 App 更新來源

## 目標

讓 Windows 桌面版在本機完成打包後，自動建立正式 GitHub Release，並將安裝包與 updater 所需 metadata 一併上傳到 `daniel20059463-tech/Taiwan-stock-market-auto-analyse`。

桌面 App 啟動時即可從該 repo 的 Releases 檢查新版本，並提示使用者可選擇更新或稍後再說。

## 產品行為

1. 開發者在本機執行 release 腳本。
2. 腳本先檢查 GitHub 登入、updater 簽章環境變數與版本前提。
3. 腳本讀取 Tauri 版本號並組成 tag，例如 `v0.1.0`。
4. 腳本確認 GitHub 尚未存在相同 tag / release。
5. 腳本完成桌面打包，產出安裝包與 updater 簽章素材。
6. 腳本自行組裝 `latest.json`。
7. 腳本先建立 draft Release，上傳所有資產成功後再 publish 成正式 Release。
8. 腳本上傳：
   - `.msi`
   - `.exe`
   - updater metadata（例如 `latest.json`）
   - 對應簽章檔
9. 使用者下次打開桌面 App 時，會從 GitHub Releases 檢查是否有新版。

## 單一真相來源

版本號統一來自：
- `src-tauri/tauri.conf.json` 的 `version`

GitHub tag 格式統一為：
- `v<version>`
- 例如 `v0.1.0`

## GitHub Repository

正式更新來源固定為：
- `daniel20059463-tech/Taiwan-stock-market-auto-analyse`

桌面 App 使用的固定 updater endpoint 為：
- `https://github.com/daniel20059463-tech/Taiwan-stock-market-auto-analyse/releases/latest/download/latest.json`

## 技術方案

### 1. Tauri updater 設定

`src-tauri/tauri.conf.json` 的 updater endpoint 改成正式 repo 路徑，不再使用 placeholder：
- `https://github.com/daniel20059463-tech/Taiwan-stock-market-auto-analyse/releases/latest/download/latest.json`

同時需配置：
- updater public key
- `bundle.createUpdaterArtifacts = true`

### 2. updater 素材與 latest.json 組裝

Tauri Windows 打包會產出 updater 需要的簽章素材，但不會自動替本機 release 流程組出可直接上傳到 GitHub Releases 的 `latest.json`。這一段由 release 腳本負責。

第一版固定使用這台機器實際觀察到的 Tauri v2 Windows updater artifact 作為更新包來源。

說明：
- 一般安裝資產仍會保留並上傳：
  - `src-tauri/target/release/bundle/msi/Taiwan Alpha Radar_<version>_x64_en-US.msi`
  - `src-tauri/target/release/bundle/nsis/Taiwan Alpha Radar_<version>_x64-setup.exe`
- 這個工具鏈在啟用 updater 產物後，實際可用的 updater 資產為：
  - `src-tauri/target/release/bundle/nsis/Taiwan Alpha Radar_<version>_x64-setup.exe`
  - `src-tauri/target/release/bundle/nsis/Taiwan Alpha Radar_<version>_x64-setup.exe.sig`
- 因此 `latest.json` 的 `url` 應指向 `.exe`，`signature` 則來自 `.exe.sig`。
- 若未產出 `.exe.sig`，腳本必須中止。

腳本需要使用以下產物：
- `src-tauri/target/release/bundle/nsis/Taiwan Alpha Radar_<version>_x64-setup.exe`
- `src-tauri/target/release/bundle/msi/Taiwan Alpha Radar_<version>_x64_en-US.msi`
- `src-tauri/target/release/bundle/nsis/Taiwan Alpha Radar_<version>_x64-setup.exe.sig`

腳本需自行產生 `latest.json`，格式明確如下：

```json
{
  "version": "v0.1.0",
  "notes": "Taiwan Alpha Radar v0.1.0",
  "pub_date": "2026-04-05T00:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "signature": "<.sig file content>",
      "url": "https://github.com/daniel20059463-tech/Taiwan-stock-market-auto-analyse/releases/download/v0.1.0/Taiwan%20Alpha%20Radar_0.1.0_x64-setup.exe"
    }
  }
}
```

必要欄位：
- `version`
- `platforms.windows-x86_64.url`
- `platforms.windows-x86_64.signature`

腳本在組裝 `url` 時必須做 URL encoding，不可直接拼接含空格檔名。

### 3. 本機 release 腳本

新增腳本，例如：
- `scripts/release_desktop.ps1`

職責：
- 檢查 `gh auth status`
- 在打包前檢查：
  - `TAURI_SIGNING_PRIVATE_KEY`
  - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- 讀版本號
- 生成 tag `vX.Y.Z`
- 檢查 GitHub 預設分支是否已存在對應遠端來源
- 執行 `npm run desktop:package`
- 檢查 `.exe`、`.msi`、`.exe.sig`
- 組裝 `latest.json`
- 建立 draft GitHub Release
- 上傳資產
- 驗證資產完整後 publish 為正式 Release

### 4. Git 與來源前提

此 release 流程不負責幫本機程式碼自動 push 到 GitHub。

前提是：
- 遠端 repo 的預設分支已經包含這次要對外宣告的版本內容，或
- 腳本明確指定一個已存在於 GitHub 的 target ref

若無法確認 target ref 已存在於 GitHub，腳本必須中止，不可建立 release。

### 5. Release 命名與內容

第一版採固定簡潔格式：
- title: `v0.1.0`
- notes: 簡短模板，包含版本、建置時間與主要資產

先不做自動 changelog 摘要。

## 必要防呆

腳本必須在下列情況中止：

1. `gh` 未登入
2. repo 不可存取
3. 同版號 tag 已存在
4. `TAURI_SIGNING_PRIVATE_KEY` 或 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` 未設定（打包前）
5. `.msi`、`.exe`、`.exe.sig` 缺失
6. `latest.json` 組裝失敗
7. target ref 不存在於 GitHub

若流程在建立 draft Release 後、publish 前失敗：
- 腳本必須刪除該 draft Release，避免留下空殼或半套資產
- 腳本必須一併刪除對應 Git tag（例如 `v0.1.0`），避免下次執行卡在「同版號 tag 已存在」
- 不允許留下已存在 tag 但資產不完整的正式 Release

## 驗收標準

1. 本機可一鍵完成桌面打包與 GitHub Release 發佈
2. Release 使用 tag `v<version>`
3. Release 內包含安裝包與 updater metadata
4. 桌面 App 啟動時可從該 GitHub repo 的固定 `latest.json` 檢查更新
5. 若版本已存在，腳本安全中止，不重複發佈
6. 若登入或資產不完整，腳本安全中止並顯示原因
7. 若上傳過程失敗，不留下不完整的正式 Release

## 測試與驗證

### 本機驗證
- `npm test`
- `npm run build`
- `npm run desktop:package`
- release 腳本 dry-run（若實作）

### 真實驗證
- 實際建立一個正式 GitHub Release
- 確認 repo Releases 可見資產
- 確認桌面 App 可讀取該 Release 的更新資訊

## 先不做的事

- GitHub Actions 自動發版
- 自動產生 changelog
- 週報/月報式 release notes
- 多平台安裝包
- Windows Authenticode / SmartScreen 程式碼簽章

use serde::Serialize;
use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateStatus {
    pub status: String,
    pub current_version: Option<String>,
    pub available_version: Option<String>,
    pub notes: Option<String>,
    pub message: Option<String>,
}

impl UpdateStatus {
    fn available(current_version: String, available_version: String, notes: Option<String>) -> Self {
        let message = format!(
            "目前版本 {}，可更新為 {}。你可以現在更新，或稍後再說。",
            current_version, available_version
        );

        Self {
            status: "available".into(),
            current_version: Some(current_version),
            available_version: Some(available_version),
            notes,
            message: Some(message),
        }
    }

    fn up_to_date(current_version: String) -> Self {
        Self {
            status: "upToDate".into(),
            current_version: Some(current_version),
            available_version: None,
            notes: None,
            message: None,
        }
    }

    fn installing(current_version: String, available_version: String) -> Self {
        Self {
            status: "installing".into(),
            current_version: Some(current_version),
            available_version: Some(available_version),
            notes: None,
            message: Some("更新下載完成，正在安裝新版。".into()),
        }
    }
}

#[tauri::command]
pub async fn check_for_update(app: AppHandle) -> Result<UpdateStatus, String> {
    let current_version = app.package_info().version.to_string();
    let updater = app
        .updater()
        .map_err(|error| format!("無法建立更新器：{error}"))?;

    let update = updater
        .check()
        .await
        .map_err(|error| format!("檢查更新失敗：{error}"))?;

    match update {
        Some(update) => Ok(UpdateStatus::available(
            current_version,
            update.version.to_string(),
            update.body.clone(),
        )),
        None => Ok(UpdateStatus::up_to_date(current_version)),
    }
}

#[tauri::command]
pub async fn install_update(app: AppHandle) -> Result<UpdateStatus, String> {
    let current_version = app.package_info().version.to_string();
    let updater = app
        .updater()
        .map_err(|error| format!("無法建立更新器：{error}"))?;

    let update = updater
        .check()
        .await
        .map_err(|error| format!("檢查更新失敗：{error}"))?;

    let Some(update) = update else {
        return Ok(UpdateStatus::up_to_date(current_version));
    };

    let available_version = update.version.to_string();

    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|error| format!("安裝更新失敗：{error}"))?;

    Ok(UpdateStatus::installing(current_version, available_version))
}

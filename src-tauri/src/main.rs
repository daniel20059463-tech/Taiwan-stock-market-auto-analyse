#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod updater;

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(backend::BackendState::default())
        .invoke_handler(tauri::generate_handler![
            backend::start_backend,
            backend::stop_backend,
            backend::restart_backend,
            backend::backend_status,
            updater::check_for_update,
            updater::install_update
        ])
        .setup(|app| {
            let _ = backend::try_start_backend(&app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            let _ = backend::try_stop_backend(app_handle);
        }
    });
}

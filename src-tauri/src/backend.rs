use serde::Serialize;
use std::{
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
};
use tauri::{process, AppHandle, Manager, State};

#[derive(Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BackendPhase {
    Idle,
    Starting,
    Running,
    Error,
}

#[derive(Clone, Serialize)]
pub struct BackendStatus {
    pub phase: BackendPhase,
    pub message: String,
}

impl BackendStatus {
    fn idle(message: impl Into<String>) -> Self {
        Self {
            phase: BackendPhase::Idle,
            message: message.into(),
        }
    }

    fn starting(message: impl Into<String>) -> Self {
        Self {
            phase: BackendPhase::Starting,
            message: message.into(),
        }
    }

    fn running(message: impl Into<String>) -> Self {
        Self {
            phase: BackendPhase::Running,
            message: message.into(),
        }
    }

    fn error(message: impl Into<String>) -> Self {
        Self {
            phase: BackendPhase::Error,
            message: message.into(),
        }
    }
}

#[derive(Default)]
pub struct BackendState {
    inner: Mutex<BackendManager>,
}

#[derive(Default)]
struct BackendManager {
    child: Option<Child>,
    status: Option<BackendStatus>,
}

enum BackendLaunchTarget {
    DevPython {
        script_dir: PathBuf,
        program: String,
        args: Vec<String>,
    },
    PackagedBinary {
        executable: PathBuf,
        working_dir: PathBuf,
    },
}

impl BackendManager {
    fn current_status(&mut self) -> BackendStatus {
        self.refresh_child_state();
        self.status
            .clone()
            .unwrap_or_else(|| BackendStatus::idle("Backend is not running"))
    }

    fn start(&mut self, app: &AppHandle) -> Result<BackendStatus, String> {
        self.refresh_child_state();
        if self.child.is_some() {
            return Ok(self.current_status());
        }

        self.status = Some(BackendStatus::starting("Starting desktop backend"));

        let target = match resolve_launch_target(app) {
            Ok(target) => target,
            Err(error) => {
                let status = BackendStatus::error(error);
                self.status = Some(status.clone());
                return Err(status.message);
            }
        };
        let mut command = match &target {
            BackendLaunchTarget::DevPython {
                script_dir,
                program,
                args,
            } => {
                let mut command = Command::new(program);
                command.current_dir(script_dir);
                command.args(args);
                command
            }
            BackendLaunchTarget::PackagedBinary {
                executable,
                working_dir,
            } => {
                let mut command = Command::new(executable);
                command.current_dir(working_dir);
                command
            }
        };

        command.stdin(Stdio::null());
        command.stdout(Stdio::null());
        command.stderr(Stdio::null());

        match command.spawn() {
            Ok(child) => {
                self.child = Some(child);
                let status = match target {
                    BackendLaunchTarget::DevPython { script_dir, .. } => {
                        BackendStatus::running(format!(
                            "Backend running via python desktop_backend.py in {}",
                            script_dir.display()
                        ))
                    }
                    BackendLaunchTarget::PackagedBinary { executable, .. } => {
                        BackendStatus::running(format!(
                            "Backend running from packaged binary {}",
                            executable.display()
                        ))
                    }
                };
                self.status = Some(status.clone());
                Ok(status)
            }
            Err(error) => {
                let status = BackendStatus::error(format!("Failed to start backend: {error}"));
                self.status = Some(status.clone());
                Err(status.message)
            }
        }
    }

    fn stop(&mut self) -> Result<BackendStatus, String> {
        self.refresh_child_state();

        let Some(mut child) = self.child.take() else {
            let status = BackendStatus::idle("Backend is not running");
            self.status = Some(status.clone());
            return Ok(status);
        };

        match child.kill() {
            Ok(()) => {
                let _ = child.wait();
                let status = BackendStatus::idle("Backend stopped");
                self.status = Some(status.clone());
                Ok(status)
            }
            Err(error) => {
                self.child = Some(child);
                let status = BackendStatus::error(format!("Failed to stop backend: {error}"));
                self.status = Some(status.clone());
                Err(status.message)
            }
        }
    }

    fn restart(&mut self, app: &AppHandle) -> Result<BackendStatus, String> {
        self.stop()?;
        self.start(app)
    }

    fn refresh_child_state(&mut self) {
        let mut next_status = None;

        if let Some(child) = self.child.as_mut() {
            match child.try_wait() {
                Ok(Some(exit_status)) => {
                    next_status = Some(if exit_status.success() {
                        BackendStatus::idle("Backend exited")
                    } else {
                        BackendStatus::error(format!("Backend exited with status {exit_status}"))
                    });
                }
                Ok(None) => {}
                Err(error) => {
                    next_status = Some(BackendStatus::error(format!(
                        "Failed to inspect backend status: {error}"
                    )));
                }
            }
        }

        if let Some(status) = next_status {
            self.child = None;
            self.status = Some(status);
        }
    }
}

fn resolve_launch_target(app: &AppHandle) -> Result<BackendLaunchTarget, String> {
    if cfg!(debug_assertions) {
        let project_root = resolve_project_root();
        return Ok(BackendLaunchTarget::DevPython {
            script_dir: project_root,
            program: "python".to_string(),
            args: vec!["desktop_backend.py".to_string()],
        });
    }

    let candidate = resolve_packaged_backend_path(app)?;
    let working_dir = resolve_packaged_working_dir(&candidate)?;

    if candidate.is_file() {
        return Ok(BackendLaunchTarget::PackagedBinary {
            executable: candidate,
            working_dir,
        });
    }

    Err(format!(
        "Packaged backend binary not found at {}",
        candidate.display()
    ))
}

fn resolve_project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri should live under the project root")
        .to_path_buf()
}

fn resolve_packaged_working_dir(candidate: &Path) -> Result<PathBuf, String> {
    let project_root = resolve_project_root();
    if project_root.join("run.py").is_file() {
        return Ok(project_root);
    }

    candidate
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| format!("Packaged backend path has no parent: {}", candidate.display()))
}

fn resolve_packaged_backend_path(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(resource_dir) = app.path().resource_dir() {
        return Ok(resolve_packaged_backend_path_from_dir(&resource_dir));
    }

    let current_binary =
        process::current_binary(&app.env()).map_err(|error| format!("Failed to resolve app binary: {error}"))?;
    let executable_dir = current_binary
        .parent()
        .ok_or_else(|| format!("App binary has no parent directory: {}", current_binary.display()))?;

    Ok(resolve_packaged_backend_path_from_dir(executable_dir))
}

fn resolve_packaged_backend_path_from_dir(base_dir: &Path) -> PathBuf {
    for candidate in backend_path_candidates(base_dir) {
        if candidate.is_file() {
            return candidate;
        }
    }

    backend_path_candidates(base_dir)
        .into_iter()
        .next()
        .unwrap_or_else(|| base_dir.join("desktop_backend.exe"))
}

fn backend_path_candidates(base_dir: &Path) -> Vec<PathBuf> {
    let triple_name = format!(
        "desktop_backend-{}.{}",
        backend_target_triple(),
        platform_backend_extension()
    );
    let plain_name = format!("desktop_backend.{}", platform_backend_extension());

    let mut candidates = Vec::new();
    let is_resources_dir = base_dir
        .file_name()
        .and_then(|name| name.to_str())
        .map(|name| name.eq_ignore_ascii_case("resources"))
        .unwrap_or(false);

    if is_resources_dir {
        candidates.push(base_dir.join("backend").join(&triple_name));
        candidates.push(base_dir.join("backend").join(&plain_name));
        if let Some(parent) = base_dir.parent() {
            candidates.push(parent.join(&plain_name));
            candidates.push(parent.join(&triple_name));
            candidates.push(parent.join("backend").join(&triple_name));
            candidates.push(parent.join("backend").join(&plain_name));
        }
    } else {
        candidates.push(base_dir.join(&plain_name));
        candidates.push(base_dir.join(&triple_name));
        candidates.push(base_dir.join("backend").join(&triple_name));
        candidates.push(base_dir.join("backend").join(&plain_name));
        candidates.push(base_dir.join("resources").join("backend").join(&triple_name));
        candidates.push(base_dir.join("resources").join("backend").join(&plain_name));
        candidates.push(base_dir.join("resources").join(&plain_name));
    }

    candidates
}

fn platform_backend_extension() -> &'static str {
    #[cfg(target_os = "windows")]
    {
        "exe"
    }
    #[cfg(not(target_os = "windows"))]
    {
        ""
    }
}

fn backend_target_triple() -> &'static str {
    #[cfg(all(target_os = "windows", target_arch = "x86_64"))]
    {
        "x86_64-pc-windows-msvc"
    }
    #[cfg(all(target_os = "windows", target_arch = "x86"))]
    {
        "i686-pc-windows-msvc"
    }
    #[cfg(all(target_os = "windows", target_arch = "aarch64"))]
    {
        "aarch64-pc-windows-msvc"
    }
    #[cfg(not(target_os = "windows"))]
    {
        "unknown-target"
    }
}

pub fn try_start_backend(app: &AppHandle) -> Result<BackendStatus, String> {
    let state: State<'_, BackendState> = app.state();
    let mut manager = state
        .inner
        .lock()
        .map_err(|_| "Backend state lock poisoned".to_string())?;
    manager.start(app)
}

pub fn try_stop_backend(app: &AppHandle) -> Result<BackendStatus, String> {
    let state: State<'_, BackendState> = app.state();
    let mut manager = state
        .inner
        .lock()
        .map_err(|_| "Backend state lock poisoned".to_string())?;
    manager.stop()
}

#[tauri::command]
pub fn start_backend(app: AppHandle, state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let mut manager = state
        .inner
        .lock()
        .map_err(|_| "Backend state lock poisoned".to_string())?;
    manager.start(&app)
}

#[tauri::command]
pub fn stop_backend(state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let mut manager = state
        .inner
        .lock()
        .map_err(|_| "Backend state lock poisoned".to_string())?;
    manager.stop()
}

#[tauri::command]
pub fn restart_backend(app: AppHandle, state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let mut manager = state
        .inner
        .lock()
        .map_err(|_| "Backend state lock poisoned".to_string())?;
    manager.restart(&app)
}

#[tauri::command]
pub fn backend_status(state: State<'_, BackendState>) -> Result<BackendStatus, String> {
    let mut manager = state
        .inner
        .lock()
        .map_err(|_| "Backend state lock poisoned".to_string())?;
    Ok(manager.current_status())
}

#[cfg(test)]
mod tests {
    use super::{resolve_packaged_backend_path_from_dir, resolve_packaged_working_dir};
    use std::{
        fs,
        path::PathBuf,
        time::{SystemTime, UNIX_EPOCH},
    };

    fn temp_case_dir(name: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("taiwan_alpha_radar_{name}_{unique}"));
        fs::create_dir_all(&dir).expect("create temp case dir");
        dir
    }

    #[test]
    fn resolves_installed_backend_from_root_layout() {
        let base = temp_case_dir("root_layout");
        fs::write(base.join("desktop_backend.exe"), b"binary").expect("write backend");
        let path = resolve_packaged_backend_path_from_dir(&base);

        assert_eq!(path, base.join("desktop_backend.exe"));
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn prefers_resource_subdirectory_when_present() {
        let root = temp_case_dir("resources_layout");
        let base = root.join("resources");
        let backend_dir = base.join("backend");
        fs::create_dir_all(&backend_dir).expect("create backend dir");
        let expected = backend_dir.join("desktop_backend-x86_64-pc-windows-msvc.exe");
        fs::write(&expected, b"binary").expect("write triple backend");
        let path = resolve_packaged_backend_path_from_dir(&base);

        assert_eq!(path, expected);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn packaged_backend_prefers_project_root_as_working_dir() {
        let base = temp_case_dir("working_dir");
        let candidate = base.join("desktop_backend.exe");
        fs::write(&candidate, b"binary").expect("write backend");

        let working_dir = resolve_packaged_working_dir(&candidate).expect("resolve working dir");

        assert_eq!(working_dir, super::resolve_project_root());
        let _ = fs::remove_dir_all(base);
    }
}

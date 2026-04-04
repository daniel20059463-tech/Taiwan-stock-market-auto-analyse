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
    let working_dir = candidate
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| format!("Packaged backend path has no parent: {}", candidate.display()))?;

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

fn resolve_packaged_backend_path(app: &AppHandle) -> Result<PathBuf, String> {
    let relative_path = PathBuf::from(format!(
        "{}-{}.{}",
        BACKEND_BUNDLE_STEM,
        backend_target_triple(),
        platform_backend_extension()
    ));

    if let Ok(resource_dir) = app.path().resource_dir() {
        return Ok(resource_dir.join(&relative_path));
    }

    let current_binary =
        process::current_binary(&app.env()).map_err(|error| format!("Failed to resolve app binary: {error}"))?;
    let executable_dir = current_binary
        .parent()
        .ok_or_else(|| format!("App binary has no parent directory: {}", current_binary.display()))?;

    Ok(executable_dir.join(relative_path))
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

const BACKEND_BUNDLE_STEM: &str = "backend/desktop_backend";

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

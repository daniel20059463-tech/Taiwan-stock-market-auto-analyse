[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail-Step {
    param([string]$Message)
    throw $Message
}

function Get-RequiredCommand {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) {
        Fail-Step "$Name was not found on PATH. $InstallHint"
    }

    return $command.Source
}

function Find-CommandWithFallback {
    param(
        [string]$Name,
        [string]$FallbackDirectory
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        return $command.Source
    }

    $fallbackPath = Join-Path $FallbackDirectory $Name
    if (Test-Path $fallbackPath) {
        return $fallbackPath
    }

    return $null
}

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    Write-Host "$FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Test-PythonModule {
    param(
        [string]$PythonPath,
        [string[]]$PythonArgs,
        [string]$ModuleName
    )

    & $PythonPath @PythonArgs -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)"
    return $LASTEXITCODE -eq 0
}

function Test-MsvcToolchain {
    if (Get-Command cl.exe -ErrorAction SilentlyContinue) {
        return $true
    }

    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $installPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($LASTEXITCODE -eq 0 -and $installPath) {
            return $true
        }
    }

    return $false
}

function Test-IsAdministrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RustTargetTriple {
    param([string]$RustcPath)

    if ($RustcPath) {
        $hostLine = & $RustcPath -vV 2>$null | Where-Object { $_ -like 'host:*' } | Select-Object -First 1
        if ($LASTEXITCODE -eq 0 -and $hostLine) {
            return ($hostLine -replace '^host:\s*', '').Trim()
        }
    }

    if ([Environment]::Is64BitOperatingSystem) {
        return "x86_64-pc-windows-msvc"
    }

    return "i686-pc-windows-msvc"
}

function Get-EnvironmentValue {
    param([string]$Name)

    if (Get-Item -Path "Env:$Name" -ErrorAction SilentlyContinue) {
        return (Get-Item -Path "Env:$Name").Value
    }

    $userValue = [Environment]::GetEnvironmentVariable($Name, "User")
    if ($userValue) {
        return $userValue
    }

    return $null
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $projectRoot "src-tauri\backend"
$desktopBackendScript = Join-Path $projectRoot "desktop_backend.py"
$desktopBackendExe = Join-Path $backendDir "desktop_backend.exe"
$pyInstallerCacheDir = Join-Path $projectRoot ".pyinstaller"
$pyInstallerWorkDir = Join-Path $pyInstallerCacheDir "build"
$cargoBinDir = Join-Path $env:USERPROFILE ".cargo\bin"
$cargoPath = Find-CommandWithFallback -Name "cargo.exe" -FallbackDirectory $cargoBinDir
$rustcPath = Find-CommandWithFallback -Name "rustc.exe" -FallbackDirectory $cargoBinDir

Write-Step "Preflight checks"
Set-Location $projectRoot

$tauriSigningPrivateKey = Get-EnvironmentValue -Name "TAURI_SIGNING_PRIVATE_KEY"
$tauriSigningPrivateKeyPassword = Get-EnvironmentValue -Name "TAURI_SIGNING_PRIVATE_KEY_PASSWORD"
$tauriUpdaterPublicKey = Get-EnvironmentValue -Name "TAURI_UPDATER_PUBLIC_KEY"

if ($tauriSigningPrivateKey) {
    $env:TAURI_SIGNING_PRIVATE_KEY = $tauriSigningPrivateKey
}

if ($tauriSigningPrivateKeyPassword) {
    $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = $tauriSigningPrivateKeyPassword
}

if ($tauriUpdaterPublicKey) {
    $env:TAURI_UPDATER_PUBLIC_KEY = $tauriUpdaterPublicKey
}

if (-not $tauriSigningPrivateKey) {
    Write-Warning "TAURI_SIGNING_PRIVATE_KEY not set. Release builds that generate updater artifacts will fail until it is configured."
}

if (-not $tauriSigningPrivateKeyPassword) {
    Write-Warning "TAURI_SIGNING_PRIVATE_KEY_PASSWORD not set. Add it before signing updater artifacts."
}

if (-not $tauriUpdaterPublicKey) {
    Write-Warning "TAURI_UPDATER_PUBLIC_KEY not set. The release script must inject a real updater public key before publishing updater-enabled builds."
}

$npmPath = Get-RequiredCommand -Name "npm.cmd" -InstallHint "Install Node.js and make sure npm is available."

if (($cargoPath -or $rustcPath) -and (Test-Path $cargoBinDir)) {
    $pathEntries = @($env:PATH -split ';' | Where-Object { $_ })
    if ($pathEntries -notcontains $cargoBinDir) {
        $env:PATH = "$cargoBinDir;$env:PATH"
    }
}

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonArgs = @()

if (-not (Test-Path $pythonPath)) {
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pyLauncher) {
        $pythonPath = $pyLauncher.Source
        $pythonArgs = @("-3")
    } else {
        $pythonPath = Get-RequiredCommand -Name "python.exe" -InstallHint "Install Python 3.11+ or create .venv before packaging."
    }
}

& $pythonPath @pythonArgs -c "import sys; print(sys.executable); print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) {
    Fail-Step "Python is installed but could not be executed."
}

$requiredModules = @(
    @{
        Module = "PyInstaller"
        Hint = "Install backend packaging dependencies with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`."
    }
    @{
        Module = "dotenv"
        Hint = "Install backend runtime dependencies with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`."
    }
)

foreach ($requiredModule in $requiredModules) {
    if (-not (Test-PythonModule -PythonPath $pythonPath -PythonArgs $pythonArgs -ModuleName $requiredModule.Module)) {
        Fail-Step "Python module '$($requiredModule.Module)' is missing. $($requiredModule.Hint)"
    }
}

if (-not (Test-Path $desktopBackendScript)) {
    Fail-Step "desktop_backend.py was not found at $desktopBackendScript."
}

if (-not (Test-MsvcToolchain)) {
    if (-not (Test-IsAdministrator)) {
        Write-Warning "MSVC Build Tools were not detected, and this shell is not elevated. Installing Visual Studio Build Tools usually requires approving a UAC prompt or running PowerShell as Administrator."
    } else {
        Write-Warning "MSVC Build Tools were not detected. Frontend build and backend exe packaging can still run, but Tauri bundling will fail until the C++ toolchain is installed."
    }
}

if (-not $cargoPath) {
    Write-Warning "cargo.exe was not found on PATH or in $cargoBinDir. Frontend build and backend exe packaging can still run, but Tauri bundling will fail until Rust is installed via rustup."
}

if (-not $rustcPath) {
    Write-Warning "rustc.exe was not found on PATH or in $cargoBinDir. Tauri bundling will fail until the Rust toolchain is installed."
}

$targetTriple = Get-RustTargetTriple -RustcPath $rustcPath
$tauriBackendExe = Join-Path $backendDir ("desktop_backend-{0}.exe" -f $targetTriple)

Write-Step "Building frontend"
Invoke-CheckedCommand -FilePath $npmPath -Arguments @("run", "build") -FailureMessage "Frontend build failed"

Write-Step "Packaging Python backend"
New-Item -ItemType Directory -Force -Path $backendDir | Out-Null
New-Item -ItemType Directory -Force -Path $pyInstallerWorkDir | Out-Null

if (Test-Path $desktopBackendExe) {
    Remove-Item -LiteralPath $desktopBackendExe -Force
}

if (Test-Path $tauriBackendExe) {
    Remove-Item -LiteralPath $tauriBackendExe -Force
}

Invoke-CheckedCommand -FilePath $pythonPath -Arguments ($pythonArgs + @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "desktop_backend",
    "--distpath", $backendDir,
    "--workpath", $pyInstallerWorkDir,
    "--specpath", $pyInstallerCacheDir,
    "--paths", $projectRoot,
    "--hidden-import", "run",
    "--hidden-import", "sinopac_bridge",
    "--hidden-import", "auto_trader",
    $desktopBackendScript
)) -FailureMessage "PyInstaller backend packaging failed"

if (-not (Test-Path $desktopBackendExe)) {
    Fail-Step "PyInstaller completed but $desktopBackendExe was not created."
}

Copy-Item -LiteralPath $desktopBackendExe -Destination $tauriBackendExe -Force

if (-not (Test-Path $tauriBackendExe)) {
    Fail-Step "Tauri external binary copy failed: $tauriBackendExe was not created."
}

if (-not (Test-MsvcToolchain)) {
    if (-not (Test-IsAdministrator)) {
        Fail-Step "MSVC Build Tools are required for tauri build. Rerun the Build Tools installer from an elevated PowerShell or approve the UAC prompt, then rerun this script."
    }

    Fail-Step "MSVC Build Tools are required for tauri build. Install the Visual Studio C++ build tools, then rerun this script."
}

if (-not $cargoPath) {
    Fail-Step "cargo.exe is required for tauri build. Install Rust with rustup, then rerun this script."
}

if (-not $rustcPath) {
    Fail-Step "rustc.exe is required for tauri build. Install Rust with rustup, then rerun this script."
}

Write-Step "Running tauri build"
Invoke-CheckedCommand -FilePath $npmPath -Arguments @("run", "desktop:build") -FailureMessage "tauri build failed"

Write-Step "Desktop packaging finished"
Write-Host "Created backend executable at $desktopBackendExe" -ForegroundColor Green
Write-Host "Created Tauri resource executable at $tauriBackendExe" -ForegroundColor Green

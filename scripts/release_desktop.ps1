[CmdletBinding()]
param(
    [string]$Repo = "daniel20059463-tech/Taiwan-stock-market-auto-analyse",
    [string]$TargetRef,
    [switch]$DryRun
)

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

function Invoke-GhProcess {
    param(
        [string]$GhPath,
        [string[]]$Arguments
    )

    $escapedArguments = $Arguments | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"' + ($_ -replace '"', '\"') + '"'
        } else {
            $_
        }
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $GhPath
    $psi.Arguments = ($escapedArguments -join ' ')
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()

    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        StdOut = $stdout
        StdErr = $stderr
    }
}

function Invoke-GitHubJson {
    param(
        [string]$GhPath,
        [string]$Endpoint
    )

    $result = Invoke-GhProcess -GhPath $GhPath -Arguments @("api", $Endpoint)
    if ($result.ExitCode -ne 0) {
        return $null
    }

    if (-not $result.StdOut) {
        return $null
    }

    return $result.StdOut | ConvertFrom-Json
}

function Test-GitHubApiSuccess {
    param(
        [string]$GhPath,
        [string]$Endpoint
    )

    $result = Invoke-GhProcess -GhPath $GhPath -Arguments @("api", $Endpoint)
    return $result.ExitCode -eq 0
}

function Get-RequiredArtifact {
    param(
        [string]$Directory,
        [string]$Filter,
        [string]$Label
    )

    $artifact = Get-ChildItem -Path $Directory -File -Filter $Filter -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $artifact) {
        Fail-Step "$Label was not found under $Directory using filter $Filter."
    }

    return $artifact
}

function New-LatestJson {
    param(
        [string]$VersionTag,
        [string]$ReleaseUrl,
        [string]$Signature,
        [string]$OutputPath
    )

    $payload = [ordered]@{
        version = $VersionTag
        notes = "Taiwan Alpha Radar $VersionTag"
        pub_date = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        platforms = [ordered]@{
            "windows-x86_64" = [ordered]@{
                signature = $Signature
                url = $ReleaseUrl
            }
        }
    }

    $json = $payload | ConvertTo-Json -Depth 8
    Set-Content -LiteralPath $OutputPath -Value $json -Encoding utf8
}

function Get-GitHubAssetName {
    param([string]$FileName)
    return $FileName -replace ' ', '.'
}

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Content
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$tauriConfigPath = Join-Path $projectRoot "src-tauri\tauri.conf.json"
$packageScriptPath = Join-Path $projectRoot "scripts\package_desktop.ps1"
$ghPath = "E:\gh.exe"

if (-not (Test-Path $ghPath)) {
    Fail-Step "gh CLI was not found at $ghPath."
}

if (-not (Test-Path $tauriConfigPath)) {
    Fail-Step "tauri.conf.json was not found at $tauriConfigPath."
}

if (-not (Test-Path $packageScriptPath)) {
    Fail-Step "package_desktop.ps1 was not found at $packageScriptPath."
}

Set-Location $projectRoot

$releaseCreated = $false
$releasePublished = $false
$remoteTagCreated = $false
$localTagCreated = $false
$restoreConfig = $null
$tempDir = $null
$tag = $null

try {
    Write-Step "Preflight checks"

    Invoke-CheckedCommand -FilePath $ghPath -Arguments @("auth", "status") -FailureMessage "gh auth status failed"

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
        Fail-Step "TAURI_SIGNING_PRIVATE_KEY is required before packaging updater artifacts."
    }

    if (-not $tauriSigningPrivateKeyPassword) {
        Fail-Step "TAURI_SIGNING_PRIVATE_KEY_PASSWORD is required before packaging updater artifacts."
    }

    if (-not $tauriUpdaterPublicKey) {
        Fail-Step "TAURI_UPDATER_PUBLIC_KEY is required so the packaged app can verify downloaded updates."
    }

    $repoInfo = Invoke-GitHubJson -GhPath $ghPath -Endpoint "repos/$Repo"
    if (-not $repoInfo) {
        Fail-Step "Repository $Repo is not accessible with the current gh session."
    }

    if (-not $TargetRef) {
        $TargetRef = [string]$repoInfo.default_branch
    }

    if (-not $TargetRef) {
        Fail-Step "Unable to determine target ref for release creation."
    }

    if (-not (Test-GitHubApiSuccess -GhPath $ghPath -Endpoint "repos/$Repo/commits/$TargetRef")) {
        Fail-Step "Target ref '$TargetRef' does not exist on GitHub for $Repo."
    }

    $tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
    $version = [string]$tauriConfig.version
    if (-not $version) {
        Fail-Step "Unable to read version from $tauriConfigPath."
    }

    $tag = "v$version"

    if (Test-GitHubApiSuccess -GhPath $ghPath -Endpoint "repos/$Repo/releases/tags/$tag") {
        Fail-Step "Release $tag already exists on GitHub."
    }

    if (Test-GitHubApiSuccess -GhPath $ghPath -Endpoint "repos/$Repo/git/ref/tags/$tag") {
        Fail-Step "Tag $tag already exists on GitHub."
    }

    $localTagExists = [string]::Join("", @(& git tag --list $tag))
    $localTagExists = $localTagExists.Trim()
    if ($localTagExists) {
        Fail-Step "Local tag $tag already exists."
    }

    Write-Step "Injecting updater configuration for release build"

    $restoreConfig = Get-Content -LiteralPath $tauriConfigPath -Raw
    $tauriConfig.plugins.updater.endpoints = @(
        "https://github.com/daniel20059463-tech/Taiwan-stock-market-auto-analyse/releases/latest/download/latest.json"
    )
    $tauriConfig.plugins.updater.pubkey = $tauriUpdaterPublicKey.Trim()

    if (-not $tauriConfig.bundle) {
        $tauriConfig | Add-Member -NotePropertyName bundle -NotePropertyValue ([ordered]@{})
    }
    if (-not ($tauriConfig.bundle.PSObject.Properties.Name -contains "createUpdaterArtifacts")) {
        $tauriConfig.bundle | Add-Member -NotePropertyName createUpdaterArtifacts -NotePropertyValue $true
    } else {
        $tauriConfig.bundle.createUpdaterArtifacts = $true
    }

    $updatedConfigJson = $tauriConfig | ConvertTo-Json -Depth 32
    Write-Utf8NoBomFile -Path $tauriConfigPath -Content $updatedConfigJson

    Write-Step "Packaging desktop application"
    Invoke-CheckedCommand -FilePath "powershell.exe" -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $packageScriptPath
    ) -FailureMessage "Desktop packaging failed"

    Write-Step "Resolving release artifacts"
    $bundleRoot = Join-Path $projectRoot "src-tauri\target\release\bundle"
    $nsisDir = Join-Path $bundleRoot "nsis"
    $msiDir = Join-Path $bundleRoot "msi"

    $installerExe = Get-RequiredArtifact -Directory $nsisDir -Filter ("Taiwan Alpha Radar_{0}_x64-setup.exe" -f $version) -Label "NSIS installer"
    $installerMsi = Get-RequiredArtifact -Directory $msiDir -Filter ("Taiwan Alpha Radar_{0}_x64_en-US.msi" -f $version) -Label "MSI installer"
    $updaterArtifact = Get-RequiredArtifact -Directory $nsisDir -Filter ("Taiwan Alpha Radar_{0}_x64-setup.exe" -f $version) -Label "Updater artifact"
    $updaterSig = Get-RequiredArtifact -Directory $nsisDir -Filter ("Taiwan Alpha Radar_{0}_x64-setup.exe.sig" -f $version) -Label "Updater signature"

    $tempDir = Join-Path $projectRoot (".release\tmp-{0}" -f ([guid]::NewGuid().ToString("N")))
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

    $latestJsonPath = Join-Path $tempDir "latest.json"
    $releaseNotesPath = Join-Path $tempDir "release-notes.md"

    $githubUpdaterAssetName = Get-GitHubAssetName -FileName $updaterArtifact.Name
    $encodedUpdaterName = [System.Uri]::EscapeDataString($githubUpdaterAssetName)
    $releaseAssetUrl = "https://github.com/$Repo/releases/download/$tag/$encodedUpdaterName"
    $signature = (Get-Content -LiteralPath $updaterSig.FullName -Raw).Trim()

    if (-not $signature) {
        Fail-Step "Updater signature file $($updaterSig.FullName) is empty."
    }

    New-LatestJson -VersionTag $tag -ReleaseUrl $releaseAssetUrl -Signature $signature -OutputPath $latestJsonPath

    $releaseNotes = @"
# Taiwan Alpha Radar $tag

- 版本：$version
- 建置時間（UTC）：$([DateTime]::UtcNow.ToString("yyyy-MM-dd HH:mm:ss"))
- 主要資產：
  - $($installerExe.Name)
  - $($installerMsi.Name)
  - $($updaterArtifact.Name)
  - latest.json
"@
    Set-Content -LiteralPath $releaseNotesPath -Value $releaseNotes -Encoding utf8

    if ($DryRun) {
        Write-Step "Dry run completed"
        Write-Host "Target ref: $TargetRef" -ForegroundColor Green
        Write-Host "Release tag: $tag" -ForegroundColor Green
        Write-Host "Installer: $($installerExe.FullName)" -ForegroundColor Green
        Write-Host "MSI: $($installerMsi.FullName)" -ForegroundColor Green
        Write-Host "Updater artifact: $($updaterArtifact.FullName)" -ForegroundColor Green
        Write-Host "Updater sig: $($updaterSig.FullName)" -ForegroundColor Green
        Write-Host "latest.json: $latestJsonPath" -ForegroundColor Green
        return
    }

    Write-Step "Creating and pushing release tag"
    Invoke-CheckedCommand -FilePath "git" -Arguments @("tag", $tag, $TargetRef) -FailureMessage "Creating local release tag failed"
    $localTagCreated = $true
    Invoke-CheckedCommand -FilePath "git" -Arguments @("push", "origin", "refs/tags/$tag") -FailureMessage "Pushing release tag failed"
    $remoteTagCreated = $true

    Write-Step "Creating draft GitHub release"
    Invoke-CheckedCommand -FilePath $ghPath -Arguments @(
        "release", "create", $tag,
        "--repo", $Repo,
        "--draft",
        "--title", $tag,
        "--notes-file", $releaseNotesPath
    ) -FailureMessage "Creating draft release failed"
    $releaseCreated = $true

    Write-Step "Uploading release assets"
    $assetPaths = @(
        $installerExe.FullName,
        $installerMsi.FullName,
        $updaterArtifact.FullName,
        $updaterSig.FullName,
        $latestJsonPath
    ) | Select-Object -Unique

    $uploadArguments = @("release", "upload", $tag) + $assetPaths + @("--repo", $Repo)
    Invoke-CheckedCommand -FilePath $ghPath -Arguments $uploadArguments -FailureMessage "Uploading release assets failed"

    Write-Step "Verifying draft release assets"
    $releaseView = & $ghPath release view $tag --repo $Repo --json isDraft,assets,url
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "Unable to inspect draft release after upload."
    }

    $releaseJson = $releaseView | ConvertFrom-Json
    $uploadedNames = @($releaseJson.assets | ForEach-Object { $_.name })
    $expectedNames = @(
        (Get-GitHubAssetName -FileName $installerExe.Name),
        (Get-GitHubAssetName -FileName $installerMsi.Name),
        (Get-GitHubAssetName -FileName $updaterArtifact.Name),
        (Get-GitHubAssetName -FileName $updaterSig.Name),
        "latest.json"
    ) | Select-Object -Unique

    foreach ($expectedName in $expectedNames) {
        if ($uploadedNames -notcontains $expectedName) {
            Fail-Step "Draft release is missing asset $expectedName."
        }
    }

    Write-Step "Publishing release"
    Invoke-CheckedCommand -FilePath $ghPath -Arguments @(
        "release", "edit", $tag,
        "--repo", $Repo,
        "--draft=false"
    ) -FailureMessage "Publishing draft release failed"
    $releasePublished = $true

    Write-Step "Release published"
    Write-Host "Published $tag to $Repo" -ForegroundColor Green
}
catch {
    $errorMessage = $_.Exception.Message

    if ($releaseCreated -and -not $releasePublished -and $tag) {
        Write-Warning "Release flow failed after draft creation. Cleaning up draft release and tag $tag."
        & $ghPath release delete $tag --repo $Repo --cleanup-tag --yes *> $null
    } elseif ($remoteTagCreated -and $tag) {
        Write-Warning "Release flow failed after tag creation. Cleaning up tag $tag."
        & git push origin ":refs/tags/$tag" *> $null
    }

    if ($localTagCreated -and $tag) {
        & git tag -d $tag *> $null
    }

    throw $errorMessage
}
finally {
    if ($restoreConfig -ne $null) {
        Write-Utf8NoBomFile -Path $tauriConfigPath -Content $restoreConfig
    }

    if ($tempDir -and (Test-Path $tempDir)) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}

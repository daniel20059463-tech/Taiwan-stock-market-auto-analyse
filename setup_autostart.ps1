# Taiwan Alpha Radar - Autostart Setup Script
# No administrator required

$vbsFile = "E:\claude code test\launch_silent.vbs"
$startupFolder = [System.Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "Taiwan Alpha Radar.lnk"

if (-not (Test-Path $vbsFile)) {
    Write-Host "ERROR: Cannot find $vbsFile" -ForegroundColor Red
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$vbsFile`""
$shortcut.WorkingDirectory = "E:\claude code test"
$shortcut.Description = "Taiwan Alpha Radar autostart"
$shortcut.Save()

Write-Host "Done! Shortcut created at:" -ForegroundColor Green
Write-Host "  $shortcutPath" -ForegroundColor Cyan
Write-Host "The app will auto-start silently on next login." -ForegroundColor Cyan
Write-Host ""
Write-Host "To remove: Delete the shortcut at the path above."

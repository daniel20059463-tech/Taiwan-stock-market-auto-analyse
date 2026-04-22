$ErrorActionPreference = "Stop"

$workspace = "E:\claude code test"
$python = "E:\claude code test\.venv\Scripts\python.exe"
$script = "E:\claude code test\scripts\visible_quote_detail_smoke.py"
$logDir = "E:\claude code test\logs"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "visible_quote_detail_smoke_$timestamp.log"

Set-Location $workspace

& $python $script *>&1 | Tee-Object -FilePath $logFile
exit $LASTEXITCODE

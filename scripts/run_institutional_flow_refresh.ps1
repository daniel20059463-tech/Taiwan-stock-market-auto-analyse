$ErrorActionPreference = "Stop"

$workspace = "E:\claude code test"
$python = "E:\claude code test\.venv\Scripts\python.exe"
$flowScript = "E:\claude code test\scripts\refresh_institutional_flow_cache.py"
$sectorScript = "E:\claude code test\scripts\build_sector_rotation_signals.py"
$logDir = "E:\claude code test\logs"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "institutional_flow_refresh_$timestamp.log"

Set-Location $workspace

# Step 1: 更新籌碼快取 (flow_cache.json)
Write-Output "[$(Get-Date -Format 'HH:mm:ss')] Step 1: Refreshing institutional flow cache..." | Tee-Object -FilePath $logFile -Append
& $python $flowScript *>&1 | Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] ERROR: Flow cache refresh failed (exit $LASTEXITCODE)" | Tee-Object -FilePath $logFile -Append
    exit $LASTEXITCODE
}

# Step 2: 重建 Sector Rotation 信號快取 (sector_rotation_signals.json)
# 自動從 flow_cache.json 取最新交易日
$tradeDate = & $python -c "
from pathlib import Path
import sys
sys.path.insert(0, r'$workspace')
from institutional_flow_cache import InstitutionalFlowCache
c = InstitutionalFlowCache()
c.load(r'$workspace\data\flow_cache.json')
dates = c.available_dates()
print(dates[-1] if dates else '')
" 2>$null

if (-not $tradeDate) {
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] WARNING: Could not determine trade date from flow cache; skipping sector signals" | Tee-Object -FilePath $logFile -Append
    exit 0
}

Write-Output "[$(Get-Date -Format 'HH:mm:ss')] Step 2: Rebuilding sector rotation signals for $tradeDate..." | Tee-Object -FilePath $logFile -Append
& $python $sectorScript --trade-date $tradeDate *>&1 | Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-Output "[$(Get-Date -Format 'HH:mm:ss')] WARNING: Sector rotation signals build failed (exit $LASTEXITCODE)" | Tee-Object -FilePath $logFile -Append
    # 非致命：flow cache 已更新，sector signals 失敗只是 preflight warning
    exit 0
}

Write-Output "[$(Get-Date -Format 'HH:mm:ss')] Done." | Tee-Object -FilePath $logFile -Append
exit 0

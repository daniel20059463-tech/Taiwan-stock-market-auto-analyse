$ErrorActionPreference = "Stop"

$workspace = "E:\claude code test"
$python = "E:\claude code test\.venv\Scripts\python.exe"
$runScript = "E:\claude code test\run.py"
$logDir = "E:\claude code test\logs"

. "$PSScriptRoot\start_run_at_open.lib.ps1"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-LauncherLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"), $Message
    Add-Content -Path (Join-Path $logDir "start_run_at_open.log") -Value $line
}

function Get-RunPyProcess {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "run.py" } |
        Select-Object -First 1
}

function Stop-RunPyProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [uint32]$RootPid
    )

    $processes = @(Get-CimInstance Win32_Process)
    $byParent = @{}
    foreach ($proc in $processes) {
        $parentKey = [string]$proc.ParentProcessId
        if (-not $byParent.ContainsKey($parentKey)) {
            $byParent[$parentKey] = New-Object System.Collections.Generic.List[object]
        }
        $byParent[$parentKey].Add($proc)
    }

    $toStop = New-Object System.Collections.Generic.List[uint32]
    $stack = New-Object System.Collections.Generic.Stack[uint32]
    $stack.Push($RootPid)

    while ($stack.Count -gt 0) {
        $pid = $stack.Pop()
        $toStop.Add($pid)
        $children = $byParent[[string]$pid]
        if ($children) {
            foreach ($child in $children) {
                $stack.Push([uint32]$child.ProcessId)
            }
        }
    }

    foreach ($pid in ($toStop | Sort-Object -Descending)) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
}

Set-Location $workspace

$now = Get-Date
$target = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day -Hour 9 -Minute 0 -Second 0
if ($now -ge $target) {
    $target = $now
}

Write-LauncherLog "launcher started; target=$($target.ToString('yyyy-MM-dd HH:mm:ss zzz'))"

while ((Get-Date) -lt $target) {
    Start-Sleep -Seconds 5
}

$isOpenDate = @'
from market_calendar import is_known_open_trading_date
print(is_known_open_trading_date("{0}"))
'@ -f (Get-Date -Format "yyyy-MM-dd")

$openResult = $isOpenDate | & $python -
if ("$openResult".Trim() -ne "True") {
    Write-LauncherLog "aborted: today is not an approved TWSE open date"
    exit 0
}

$existing = Get-RunPyProcess
if ($null -ne $existing) {
    $creationTime = $existing.CreationDate
    if (Test-IsStaleRunPyProcess -CreationTime $creationTime -Now (Get-Date)) {
        Write-LauncherLog "stale run.py detected pid=$($existing.ProcessId) created=$($creationTime.ToString('yyyy-MM-dd HH:mm:ss zzz')); stopping stale process tree"
        Stop-RunPyProcessTree -RootPid ([uint32]$existing.ProcessId)
        Start-Sleep -Seconds 2
        $existing = Get-RunPyProcess
    }
}

if ($null -ne $existing) {
    Write-LauncherLog "skipped: run.py already running pid=$($existing.ProcessId)"
    exit 0
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdout = Join-Path $logDir "run_live_$timestamp.out.log"
$stderr = Join-Path $logDir "run_live_$timestamp.err.log"

$process = Start-Process -FilePath $python -ArgumentList @("""$runScript""") -WorkingDirectory $workspace -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Write-LauncherLog "started run.py pid=$($process.Id) stdout=$stdout stderr=$stderr"

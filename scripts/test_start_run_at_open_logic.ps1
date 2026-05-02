$ErrorActionPreference = "Stop"

. "$PSScriptRoot\start_run_at_open.lib.ps1"

$now = [datetime]::Parse("2026-04-27T08:58:58+08:00")

$sameDay = [datetime]::Parse("2026-04-27T08:10:00+08:00")
if (Test-IsStaleRunPyProcess -CreationTime $sameDay -Now $now) {
    throw "same-day run.py process should not be stale"
}

$previousDay = [datetime]::Parse("2026-04-24T22:22:47+08:00")
if (-not (Test-IsStaleRunPyProcess -CreationTime $previousDay -Now $now)) {
    throw "previous-day run.py process should be stale"
}

Write-Output "OK"

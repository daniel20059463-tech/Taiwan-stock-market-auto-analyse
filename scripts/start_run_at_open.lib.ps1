$ErrorActionPreference = "Stop"

function Test-IsStaleRunPyProcess {
    param(
        [Parameter(Mandatory = $true)]
        [datetime]$CreationTime,

        [Parameter(Mandatory = $true)]
        [datetime]$Now
    )

    return $CreationTime.Date -lt $Now.Date
}

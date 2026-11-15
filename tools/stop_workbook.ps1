param([string]$Receipt)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Receipt)) { exit 0 }
$owned = Get-Content -LiteralPath $Receipt -Raw | ConvertFrom-Json
if (-not $owned.owned) { exit 0 }
$process = Get-Process -Id ([int]$owned.pid) -ErrorAction SilentlyContinue
if ($null -ne $process -and $process.ProcessName -eq 'EXCEL' -and
    $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $owned.started) {
    # Only the specific Excel instance created by this conversion can be stopped.
    Stop-Process -Id $process.Id -Force
}

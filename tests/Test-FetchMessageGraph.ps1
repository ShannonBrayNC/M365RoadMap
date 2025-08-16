<#
.SYNOPSIS
  E2E test harness for scripts/fetch_messages_graph.py

.DESCRIPTION
  - Ensures Graph env vars are populated by dot-sourcing Set-GraphEnv.ps1
  - Invokes fetch_messages_graph.py twice: CSV + JSON
  - Prints row counts and optional stats summary

.USAGE
  .\tests\Test-FetchMessageGraph.ps1
  .\tests\Test-FetchMessageGraph.ps1 -Since '2025-08-01' -Clouds 'Worldwide (Standard Multi-Tenant)','GCC' -ShowStats
  .\tests\Test-FetchMessageGraph.ps1 -NoGraph

.PARAMETER Title
  Basename for output files.

.PARAMETER Since
  ISO date lower bound (YYYY-MM-DD).

.PARAMETER Months
  Sliding window in months.

.PARAMETER Clouds
  One or more cloud labels (each becomes a --cloud flag). If omitted, defaults to Worldwide.

.PARAMETER SeedIds
  Optional comma-delimited public roadmap IDs to seed discovery.

.PARAMETER NoGraph
  Force public-only mode (passes --no-graph to the script).

.PARAMETER ShowStats
  Print fetch_stats.json (when CSV run is performed).

.PARAMETER ConfigPath
  Path to graph_config.json (defaults to ./graph_config.json if present).

.PARAMETER PythonExe
  Python executable to use (defaults to .\.venv\Scripts\python.exe if present, else 'python').

#>

[CmdletBinding()]
param(
  [string]$Title = "roadmap_report",
  [string]$Since,
  [int]$Months,
  [string[]]$Clouds,
  [string]$SeedIds,
  [switch]$NoGraph,
  [switch]$ShowStats,
  [string]$ConfigPath,
  [string]$PythonExe
)

# --- Repo roots
$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptDir = Join-Path $repoRoot "scripts"

# --- Pick python
if (-not $PythonExe) {
  $venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (Test-Path $venvPy) { $PythonExe = $venvPy } else { $PythonExe = "python" }
}

# --- Ensure Graph env
$setEnv = Join-Path $scriptDir "Set-GraphEnv.ps1"
if (-not (Test-Path $setEnv)) {
  throw "Set-GraphEnv.ps1 not found at $setEnv. Place it in /scripts and retry."
}

# Pass ConfigPath through to Set-GraphEnv so it finds the same config we use below
if ($ConfigPath) {
  . $setEnv -ConfigPath $ConfigPath
} else {
  . $setEnv
}

# --- Paths
$outputDir = Join-Path $repoRoot "output"
if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Force -Path $outputDir | Out-Null }

$csvOut   = Join-Path $outputDir "${Title}_master.csv"
$jsonOut  = Join-Path $outputDir "${Title}_master.json"
$statsOut = Join-Path $outputDir "${Title}_fetch_stats.json"

# --- Build arg arrays
$cfgArgs = @()
if ($ConfigPath) { $cfgArgs += @("--config", $ConfigPath) }
elseif (Test-Path (Join-Path $repoRoot "graph_config.json")) { $cfgArgs += @("--config", "graph_config.json") }

$dateArgs = @()
if ($Since)  { $dateArgs += @("--since",  $Since) }
if ($Months) { $dateArgs += @("--months", "$Months") }

$cloudArgs = @()
if ($Clouds -and $Clouds.Count -gt 0) {
  foreach ($c in $Clouds) { $cloudArgs += @("--cloud", $c) }
} else {
  # Default to Worldwide if not specified
  $cloudArgs += @("--cloud", "Worldwide (Standard Multi-Tenant)")
}

$miscArgs = @()
if ($NoGraph) { $miscArgs += @("--no-graph") }
if ($SeedIds) { $miscArgs += @("--seed-ids", $SeedIds) }

# --- Helper: run fetcher
function Invoke-Fetch {
  param(
    [ValidateSet('csv','json')]
    [string]$Emit,
    [string[]]$ExtraArgs
  )
  $base = @(
    (Join-Path $scriptDir "fetch_messages_graph.py")
  ) + $cfgArgs + $dateArgs + $cloudArgs + $miscArgs + @("--emit", $Emit) + $ExtraArgs

  # Show the exact invocation
  Write-Host "=== Invoking ($Emit) ===" -ForegroundColor Cyan
  Write-Host "$PythonExe $($base -join ' ')" -ForegroundColor DarkGray

  & $PythonExe $base
  if ($LASTEXITCODE -ne 0) {
    throw "fetch_messages_graph.py ($Emit) failed with exit code $LASTEXITCODE"
  }
}

# --- Run CSV (with stats)
Invoke-Fetch -Emit csv -ExtraArgs @("--out", $csvOut, "--stats-out", $statsOut)

# --- Run JSON
Invoke-Fetch -Emit json -ExtraArgs @("--out", $jsonOut)

# --- Summaries
Write-Host ""
Write-Host "=== Results ===" -ForegroundColor Green

# Try to derive row count from CSV quickly
[int]$rowCount = 0
if (Test-Path $csvOut) {
  try {
    $rowCount = ((Get-Content -LiteralPath $csvOut).Count - 1)
  } catch { $rowCount = 0 }
}

# Find stats file if present and print core counters
if (Test-Path $statsOut) {
  $stats = Get-Content -Raw -LiteralPath $statsOut | ConvertFrom-Json
  $srcSummary = ($stats.sources | ConvertTo-Json -Compress)
  Write-Host ("Rows={0} Sources={1} Errors={2}" -f $rowCount, $srcSummary, $stats.errors)
} else {
  Write-Host ("Rows={0}" -f $rowCount)
}

# File sizes
$csvSize = (Test-Path $csvOut)  ? (Get-Item $csvOut).Length  : 0
$jsonSize= (Test-Path $jsonOut) ? (Get-Item $jsonOut).Length : 0
Write-Host ("CSV: {0} ({1} bytes)"  -f $csvOut,  $csvSize)
Write-Host ("JSON: {0} ({1} bytes)" -f $jsonOut, $jsonSize)

# Optional stats dump
if ($ShowStats -and (Test-Path $statsOut)) {
  Write-Host ""
  Write-Host "=== Stats (raw) ===" -ForegroundColor Yellow
  Get-Content -LiteralPath $statsOut
}

# Show first few CSV lines as a smoke test
if (Test-Path $csvOut) {
  Write-Host ""
  Write-Host "=== CSV Head ===" -ForegroundColor Yellow
  Get-Content -LiteralPath $csvOut -TotalCount 5
}

Write-Host ""
Write-Host "Hints:" -ForegroundColor DarkCyan
Write-Host "• Public-only mode:          -NoGraph"
Write-Host "• Time window options:       -Since 'YYYY-MM-DD' or -Months 1"
Write-Host "• Multiple clouds example:   -Clouds 'Worldwide (Standard Multi-Tenant)','GCC'"
Write-Host "• Provide seed IDs:          -SeedIds '497910,4710,5000'"

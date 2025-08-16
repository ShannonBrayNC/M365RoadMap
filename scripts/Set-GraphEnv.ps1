<#
.SYNOPSIS
  Load graph_config.json and ensure Graph-related environment variables are set.

.DESCRIPTION
  - Reads ./graph_config.json (or a provided path)
  - Sets M365_* environment variables for convenience
  - Ensures the password env var named in pfx_password_env is populated (prompts if missing)
  - Prints a safe summary (never prints secrets)

.USAGE
  # One-time (per shell) before tests
  . "$PSScriptRoot/Set-GraphEnv.ps1"

  # Or explicitly
  . "$PSScriptRoot/Set-GraphEnv.ps1" -ConfigPath "$PSScriptRoot/../graph_config.json"

.PARAMETER ConfigPath
  Path to graph_config.json. Defaults to ./graph_config.json if present; otherwise tries script directory.

.PARAMETER Quiet
  Suppress summary output.
#>

[CmdletBinding()]
param(
  [string]$ConfigPath,
  [switch]$Quiet
)

function Resolve-ConfigPath {
  param([string]$Path)
  if ($Path -and (Test-Path -LiteralPath $Path)) { return (Resolve-Path -LiteralPath $Path).Path }
  # Try CWD
  if (Test-Path -LiteralPath ".\graph_config.json") { return (Resolve-Path ".\graph_config.json").Path }
  # Try alongside this script
  if ($PSScriptRoot -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot "graph_config.json"))) {
    return (Resolve-Path (Join-Path $PSScriptRoot "graph_config.json")).Path
  }
  throw "graph_config.json not found. Specify -ConfigPath or run from the repo root."
}

function ConvertFrom-SecureStringToPlain {
  param([SecureString]$Secure)
  $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try   { [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { if ($ptr -ne [IntPtr]::Zero) { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) } }
}

# --- Load config
$cfgPath = Resolve-ConfigPath -Path $ConfigPath
$cfg = Get-Content -Raw -LiteralPath $cfgPath | ConvertFrom-Json

# Defaults/sanitization
if (-not $cfg.pfx_password_env) { $cfg | Add-Member -NotePropertyName pfx_password_env -NotePropertyValue 'M365_PFX_PASSWORD' }

# --- Set convenience env vars (used by tools/diagnostics)
$env:M365_TENANT_ID      = "$($cfg.tenant_id)"
$env:M365_CLIENT_ID      = "$($cfg.client_id)"
$env:M365_AUTHORITY_BASE = "$($cfg.authority_base)"
$env:M365_GRAPHBASE      = "$($cfg.graph_base)"
$env:M365_CERTIFICATE_PATH = "$($cfg.pfx_path)"

# --- Ensure password env var is present in THIS session
$passEnvName = "$($cfg.pfx_password_env)"
$currentVal  = (Get-Item -Path "Env:$passEnvName" -ErrorAction SilentlyContinue).Value

if ([string]::IsNullOrWhiteSpace($currentVal)) {
  Write-Warning "Environment variable '$passEnvName' is not set for this PowerShell session."
  $sec = Read-Host -Prompt "Enter PFX password for env var '$passEnvName' (input hidden)" -AsSecureString
  $plain = ConvertFrom-SecureStringToPlain -Secure $sec
  if ([string]::IsNullOrEmpty($plain)) { throw "No password provided; cannot proceed." }
  Set-Item -Path "Env:$passEnvName" -Value $plain
  # Minimize lingering plaintext
  $plain = $null
}

if (-not $Quiet) {
  $star = '********'
  $pfxLen = if ($cfg.pfx_base64) { ($cfg.pfx_base64.ToString().Length) } else { 0 }
  Write-Host "Graph env ready:" -ForegroundColor Cyan
  Write-Host "  tenant_id        : $($cfg.tenant_id)"
  Write-Host "  client_id        : $($cfg.client_id)"
  Write-Host "  authority_base   : $($cfg.authority_base)"
  Write-Host "  graph_base       : $($cfg.graph_base)"
  Write-Host "  pfx_password_env : $passEnvName (set=$(-not [string]::IsNullOrEmpty((Get-Item env:$passEnvName).Value)))"
  Write-Host "  pfx_path         : $($cfg.pfx_path)"
  Write-Host "  pfx_base64 len   : $pfxLen"
}

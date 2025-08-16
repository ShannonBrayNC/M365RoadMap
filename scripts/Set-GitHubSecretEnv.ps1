<#!
.SYNOPSIS
  Map GitHub Actions secrets (present as step env vars) into the env names
  your tooling expects; optionally persist to later steps.

.DESCRIPTION
  - Reads values from the current process environment (what Actions exposes
    for this step). GitHub never returns secret values via API/CLI.
  - Copies/mirrors them to target names (e.g., TENANT, CLIENT, PFX_B64, etc).
  - Masks the values in logs (::add-mask::).
  - Optionally persists to $GITHUB_ENV so later steps see them too.
  - Prints only safe diagnostics (lengths/flags) — never the secret values.

.PARAMETER Prefix
  Optional prefix on the *source* names (e.g., "ROADMAP_").
  Example: if Prefix="ROADMAP_", reads ROADMAP_TENANT and writes TENANT.

.PARAMETER Persist
  Also append NAME=value lines to $GITHUB_ENV for later steps.

.PARAMETER Strict
  If set, throws when any expected secret is missing/empty.

.EXAMPLE
  pwsh -File scripts/Set-GitHubSecretEnv.ps1 -Persist -Strict

.NOTES
  Designed for GitHub Actions. Locally, pass values in your session:
    $env:TENANT='...' ; $env:CLIENT='...' ; pwsh -File scripts/Set-GitHubSecretEnv.ps1
!#>

[CmdletBinding()]
param(
  [string] $Prefix = "",
  [switch] $Persist,
  [switch] $Strict
)

function Write-Mask([string]$s) {
  if ([string]::IsNullOrEmpty($s)) { return }
  # Mask for Actions logs
  try { Write-Output "::add-mask::$s" } catch { }
}

function Get-Env([string]$name) {
  return [System.Environment]::GetEnvironmentVariable($name, 'Process')
}

function Set-Env([string]$name, [string]$value) {
  # Current step/session
  Set-Item -Path ("Env:{0}" -f $name) -Value $value
  # Optionally persist across later steps
  if ($Persist -and $env:GITHUB_ENV) {
    Add-Content -Path $env:GITHUB_ENV -Value ("{0}={1}" -f $name, $value)
  }
}

function Test-Base64([string]$s) {
  if ([string]::IsNullOrWhiteSpace($s)) { return $false }
  try { [Convert]::FromBase64String($s) | Out-Null; return $true } catch { return $false }
}

# Map of source-name -> target-name
$map = [ordered]@{
  # Core Graph auth
  ("{0}TENANT"             -f $Prefix) = "TENANT"
  ("{0}CLIENT"             -f $Prefix) = "CLIENT"
  ("{0}PFX_B64"            -f $Prefix) = "PFX_B64"
  ("{0}M365_PFX_PASSWORD"  -f $Prefix) = "M365_PFX_PASSWORD"

  # Optional toggles / filters
  ("{0}MSFT_CLOUD"         -f $Prefix) = "MSFT_CLOUD"     # e.g. "Worldwide (Standard Multi-Tenant)"
  ("{0}PRODUCTS"           -f $Prefix) = "PRODUCTS"       # e.g. "Teams,Intune,SharePoint"
  ("{0}PUBLIC_IDS"         -f $Prefix) = "PUBLIC_IDS"     # space/comma/semicolon-separated IDs

  # Optional extras (leave if you use them)
  ("{0}OPENAI_API_KEY"     -f $Prefix) = "OPENAI_API_KEY"
}

$missing = New-Object System.Collections.Generic.List[string]

foreach ($src in $map.Keys) {
  $dst = $map[$src]
  $val = Get-Env $src

  if ([string]::IsNullOrWhiteSpace($val)) {
    if ($Strict) { $missing.Add($src) }
    continue
  }

  # Set env and mask in logs
  Set-Env -name $dst -value $val
  Write-Mask $val

  # Safe diagnostics (lengths/flags only)
  switch ($dst) {
    "PFX_B64" {
      $isB64 = Test-Base64 $val
      $len   = ($val ?? "").Length
      Write-Host ("Set {0} (chars={1}, base64={2}) from {3}" -f $dst, $len, $isB64, $src)
    }
    default {
      $len = ($val ?? "").Length
      Write-Host ("Set {0} (chars={1}) from {2}" -f $dst, $len, $src)
    }
  }
}

if ($missing.Count -gt 0) {
  $msg = "Missing expected secrets: {0}" -f ($missing -join ", ")
  if ($Strict) { throw $msg } else { Write-Warning $msg }
}

# Normalize a few common conveniences
# Treat blank MSFT_CLOUD as General/Worldwide for downstream code that expects it.
if (-not $env:MSFT_CLOUD -or [string]::IsNullOrWhiteSpace($env:MSFT_CLOUD)) {
  Set-Env -name "MSFT_CLOUD" -value "Worldwide (Standard Multi-Tenant)"
  Write-Host "MSFT_CLOUD not provided; defaulted to 'Worldwide (Standard Multi-Tenant)'."
}

# Provide PFX_PASSWORD_ENV (= M365_PFX_PASSWORD) for scripts that read the indirection.
if (-not $env:PFX_PASSWORD_ENV -or [string]::IsNullOrWhiteSpace($env:PFX_PASSWORD_ENV)) {
  Set-Env -name "PFX_PASSWORD_ENV" -value "M365_PFX_PASSWORD"
  Write-Host "Set PFX_PASSWORD_ENV=M365_PFX_PASSWORD"
}

Write-Host "Environment mapping complete."

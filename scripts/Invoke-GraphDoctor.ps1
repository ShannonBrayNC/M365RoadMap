param(
  [string]$ConfigPath = "graph_config.json",
  # Optional override of the password env var name if not present in JSON
  [string]$PasswordEnvFallback = $(if ($env:PFX_PASSWORD_ENV) { $env:PFX_PASSWORD_ENV } else { "M365_PFX_PASSWORD" }),
  [switch]$NoGraph,   # just validate PFX & settings, skip token call
  [switch]$Verbose
)




function Fail($msg, $code = 2) {
  Write-Error $msg
  exit $code
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  Fail "Config not found: $ConfigPath"
}

$cfg = Get-Content -Raw $ConfigPath | ConvertFrom-Json

$tenant = $cfg.tenant_id
$client = $cfg.client_id
if (-not $tenant -or -not $client) {
  Fail "Missing tenant_id/client_id in $ConfigPath"
}

# Work out PFX base64
$pfxB64 = $cfg.pfx_base64
if (-not $pfxB64) {
  if ($cfg.pfx_path -and (Test-Path -LiteralPath $cfg.pfx_path)) {
    $pfxB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($cfg.pfx_path))
  } else {
    Fail "Neither pfx_base64 nor a valid pfx_path available in $ConfigPath"
  }
}

# Find which env var holds the password (e.g., M365_PFX_PASSWORD)
$pwdEnvName = if ($cfg.pfx_password_env) { [string]$cfg.pfx_password_env } else { $PasswordEnvFallback }
$pwd = (Get-Item -ErrorAction Ignore -Path Env:\$pwdEnvName).Value
if (-not $pwd) {
  Fail "Password env var '$pwdEnvName' is not set. In GitHub Actions, pass it in 'env:' or define it as a secret."
}

if ($Verbose) {
  Write-Host "TENANT  : $tenant"
  Write-Host "CLIENT  : $client"
  Write-Host "PFX_B64 : $($pfxB64.Length) chars"
  Write-Host "PWD ENV : $pwdEnvName (value hidden)"
  if ($cfg.pfx_path) { Write-Host "PFX path: $($cfg.pfx_path)" }
  if ($cfg.authority_base) { Write-Host "Auth base: $($cfg.authority_base)" }
}

$python = "python"
$script  = "scripts/graph_doctor.py"

$commonArgs = @(
  $script,
  "--tenant", $tenant,
  "--client", $client,
  "--pfx-b64", $pfxB64,
  "--pfx-pass", $pwd
)
if ($Verbose) { $commonArgs += "--verbose" }
if ($NoGraph) { $commonArgs += "--no-graph" }

& $python @commonArgs
exit $LASTEXITCODE


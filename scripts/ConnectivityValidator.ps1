# This script sets environment variables for M365 connectivity validation tests.
# It reads graph_config.json and uses the password from an environment secret.

# Load config
$cfg = Get-Content -Raw graph_config.json | ConvertFrom-Json

# Core IDs
$env:M365_TENANT_ID = $cfg.tenant_id
$env:M365_CLIENT_ID = $cfg.client_id

# Optional (not used by graph_doctor, but fine to keep)
$env:M365_AUTHORITY_BASE  = $cfg.authority_base
$env:M365_GRAPHBASE       = $cfg.graph_base

# PFX base64 — prefer JSON field, otherwise base64-encode the file if provided
if ($cfg.pfx_base64) {
  $env:M365_PFX_B64 = $cfg.pfx_base64
} elseif ($cfg.pfx_path -and (Test-Path -LiteralPath $cfg.pfx_path)) {
  $env:M365_PFX_B64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($cfg.pfx_path))
} else {
  Write-Error "Neither 'pfx_base64' nor a valid 'pfx_path' found in graph_config.json."
  exit 2
}

# PFX password:
# If the JSON specifies which env var holds the secret (e.g. M365_PFX_PASSWORD), read it.
$pwdEnv = if ($cfg.pfx_password_env) { $cfg.pfx_password_env } else { "M365_PFX_PASSWORD" }
$pwdVal = (Get-Item -ErrorAction Ignore -Path Env:\$pwdEnv).Value
if (-not $pwdVal) {
  Write-Error "The PFX password environment variable '$pwdEnv' is not set. In GitHub Actions, pass it via 'env:' or 'secrets'."
  exit 3
}
# Optionally copy into M365_PFX_PASSWORD for convenience (DO NOT echo to logs)
$env:M365_PFX_PASSWORD = $pwdVal

# Run the doctor
python scripts/graph_doctor.py `
  --tenant   $env:M365_TENANT_ID `
  --client   $env:M365_CLIENT_ID `
  --pfx-b64  $env:M365_PFX_B64 `
  --pfx-pass $env:M365_PFX_PASSWORD `
  --verbose
param(
  [string]$Subject = "CN=EchoMediaAi-Graph",
  [string]$PfxPath = "_compat.pfx",
  [string]$PasswordPlain = $env:M365_PFX_PASSWORD
)

# 0) Require password
if (-not $PasswordPlain) { throw "Set `$env:M365_PFX_PASSWORD first (e.g. 'EdenEcho!')." }
$pwd = ConvertTo-SecureString $PasswordPlain -AsPlainText -Force

# 1) Find or create an exportable cert
$cert = Get-ChildItem Cert:\CurrentUser\My |
  Where-Object { $_.Subject -eq $Subject } |
  Sort-Object NotAfter -Descending |
  Select-Object -First 1

if (-not $cert) {
  $cert = New-SelfSignedCertificate `
    -Subject $Subject `
    -KeyAlgorithm RSA -KeyLength 2048 `
    -KeyExportPolicy Exportable `
    -NotAfter (Get-Date).AddYears(2) `
    -CertStoreLocation "Cert:\CurrentUser\My"
  Write-Host "Created cert: $($cert.Thumbprint)"
} else {
  Write-Host "Using existing cert: $($cert.Thumbprint)"
}

# 2) Export PFX with a conservative algorithm first (widely compatible with Python/OpenSSL)
try {
  Export-PfxCertificate `
    -Cert $cert `
    -FilePath $PfxPath `
    -Password $pwd `
    -ChainOption EndEntityCertOnly `
    -CryptoAlgorithmOption TripleDES_SHA1 `
    -Force | Out-Null
  Write-Host "Exported PFX with TripleDES_SHA1 -> $PfxPath"
} catch {
  Write-Warning "TripleDES_SHA1 export failed: $($_.Exception.Message)"
  Write-Host  "Retrying with AES256_SHA256…"
  Export-PfxCertificate `
    -Cert $cert `
    -FilePath $PfxPath `
    -Password $pwd `
    -ChainOption EndEntityCertOnly `
    -CryptoAlgorithmOption AES256_SHA256 `
    -Force | Out-Null
  Write-Host "Exported PFX with AES256_SHA256 -> $PfxPath"
}

if (-not (Test-Path $PfxPath)) { throw "Export failed: $PfxPath was not created." }

# 3) Base64 encode PFX and update graph_config.json
$env:PFX_B64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($PfxPath))
Write-Host "PFX_B64 length: $($env:PFX_B64.Length)"

$configPath = "graph_config.json"
if (Test-Path $configPath) {
  $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
} else {
  $cfg = [ordered]@{
    tenant_id        = ""
    client_id        = ""
    pfx_base64       = ""
    pfx_password_env = "M365_PFX_PASSWORD"
    graph_base       = "https://graph.microsoft.com/v1.0"
    authority_base   = "https://login.microsoftonline.com"
  } | ConvertTo-Json
  $cfg | Set-Content $configPath -Encoding utf8
  $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
}

$cfg.pfx_base64       = $env:PFX_B64
$cfg.pfx_password_env = "M365_PFX_PASSWORD"
$cfg | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding utf8
Write-Host "Updated $configPath (pfx_base64 set)."

# 4) Quick sanity: show SHA1 thumbprint via certutil (optional)
try { certutil -dump $PfxPath | Select-String -Pattern 'Cert Hash(sha1)' -SimpleMatch | ForEach-Object { $_.Line } } catch {}

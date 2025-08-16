<# 
.SYNOPSIS
  Convert a PFX (with private key) to a public .cer (and optional .pem) for Azure App Registration.

.EXAMPLE
  .\Convert-PfxToCer.ps1 -PfxPath ..\_cfg.pfx -PasswordText $env:M365_PFX_PASSWORD -OutCerPath .\EchoMediaAi-Graph.cer

.EXAMPLE
  # Using base64 PFX (e.g., from graph_config.json)
  .\Convert-PfxToCer.ps1 -PfxBase64 $env:PFX_B64 -PasswordText $env:M365_PFX_PASSWORD -EmitPem

.NOTES
  Uses the X509Certificate2(byte[], SecureString, X509KeyStorageFlags) constructor (no Import()) to avoid
  "X509Certificate is immutable on this platform" errors on PowerShell 7+/modern .NET.
#>

[CmdletBinding()]
param(
  [Parameter(ParameterSetName='File', Mandatory=$true)]
  [string]$PfxPath,

  [Parameter(ParameterSetName='Base64', Mandatory=$true)]
  [string]$PfxBase64,

  [SecureString]$Password,
  [string]$PasswordText,                   # convenience: converts to SecureString internally
  [string]$OutCerPath,
  [switch]$EmitPem,
  [string]$OutPemPath,
  [switch]$Verify
)

# --- Helpers ---
function ConvertTo-Secure([string]$s) {
  if ([string]::IsNullOrWhiteSpace($s)) { return $null }
  return ConvertTo-SecureString -String $s -AsPlainText -Force
}

function Get-PasswordSecure {
  if ($Password) { return $Password }
  if ($PasswordText) { return ConvertTo-Secure $PasswordText }
  if ($env:M365_PFX_PASSWORD) { return ConvertTo-Secure $env:M365_PFX_PASSWORD }
  # last resort: prompt
  Write-Host "Enter PFX password:" -ForegroundColor Yellow
  return Read-Host -AsSecureString
}

# --- Load PFX bytes ---
try {
  [byte[]]$pfxBytes = $null
  switch ($PSCmdlet.ParameterSetName) {
    'File'   { 
      if (-not (Test-Path -LiteralPath $PfxPath)) { throw "PFX file not found: $PfxPath" }
      $pfxBytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $PfxPath))
    }
    'Base64' {
      if ([string]::IsNullOrWhiteSpace($PfxBase64)) { throw "PFX base64 string is empty." }
      $pfxBytes = [Convert]::FromBase64String($PfxBase64)
    }
    default { throw "Select either -PfxPath or -PfxBase64." }
  }
}
catch {
  throw "Failed to load PFX bytes: $($_.Exception.Message)"
}

# --- Get password as SecureString ---
$sec = Get-PasswordSecure
if (-not $sec) { throw "No PFX password provided or available." }

# --- Load certificate using constructor (no Import()) ---
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.Security.Cryptography

# Flags: Exportable in-memory key, no user/machine store writes
$xks = [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable `
     -bor [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet

try {
  $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($pfxBytes, $sec, $xks)
}
catch {
  throw "PFX load failed: $($_.Exception.Message)"
}

# --- Optional verify / print details ---
if ($Verify) {
  $sha1 = ($cert.Thumbprint.ToLower())
  $nb   = $cert.NotBefore.ToString('s')
  $na   = $cert.NotAfter.ToString('s')
  Write-Host "Certificate details:" -ForegroundColor Cyan
  Write-Host "  Subject        : $($cert.Subject)"
  Write-Host "  Issuer         : $($cert.Issuer)"
  Write-Host "  Not Before     : $nb"
  Write-Host "  Not After      : $na"
  Write-Host "  SHA1 Thumbprint: $sha1"
  Write-Host "  Private Key    : $($cert.HasPrivateKey)"
}

# --- Export .cer (DER) ---
try {
  $der = $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
  [IO.File]::WriteAllBytes((Resolve-Path -LiteralPath (Split-Path -Parent $OutCerPath) -ErrorAction SilentlyContinue) ? $OutCerPath : $OutCerPath, $der)
  Write-Host "Wrote CER (DER): $OutCerPath" -ForegroundColor Green
}
catch {
  throw "Export CER failed: $($_.Exception.Message)"
}

# --- Optional .pem ---
if ($EmitPem) {
  if (-not $OutPemPath) {
    $base = [IO.Path]::ChangeExtension($OutCerPath, $null)
    $OutPemPath = "$base.pem"
  }
  try {
    $b64 = [Convert]::ToBase64String($der)
    $pem = "-----BEGIN CERTIFICATE-----`n" +
           ($b64 -split "(.{1,64})" | Where-Object { $_ -and $_.Trim().Length -gt 0 } -join "`n") +
           "`n-----END CERTIFICATE-----`n"
    Set-Content -LiteralPath $OutPemPath -Value $pem -NoNewline
    Write-Host "Wrote PEM: $OutPemPath" -ForegroundColor Green
  }
  catch {
    throw "Export PEM failed: $($_.Exception.Message)"
  }
}

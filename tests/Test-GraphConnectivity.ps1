<# 
.SYNOPSIS
  End-to-end Microsoft Graph connectivity test with certificate auth.

.DESCRIPTION
  - Loads/imports your certificate (from PFX file or base64) into Cert:\CurrentUser\My
  - Prints cert details (subject, thumbprint, validity)
  - Connects to Microsoft Graph using the SDK (Connect-MgGraph) with certificate
  - Falls back to MSAL.PS to acquire a token if SDK path fails
  - Executes a test request: GET /v1.0/admin/serviceAnnouncement/messages?$top=5
  - Supports cloud routing for General/GCC/GCC High/DoD
  - Optionally exports .cer for Azure App registration upload

.PARAMETER TenantId
  Azure AD Tenant ID (GUID) or domain, e.g. contoso.onmicrosoft.com

.PARAMETER ClientId
  Azure App (Application) ID (GUID)

.PARAMETER PfxPath
  Optional path to a .pfx containing the app certificate (with private key)

.PARAMETER PfxBase64
  Optional base64 string of the PFX (e.g., from env var PFX_B64)  # pragma: allowlist secret

.PARAMETER PfxPassword
  SecureString password for the PFX (e.g., from env var M365_PFX_PASSWORD)  # pragma: allowlist secret

.PARAMETER Thumbprint
  If the certificate already exists in the store, provide thumbprint to use directly

.PARAMETER ExportCerPath
  Optional path to write a .cer (public cert) for Azure upload

.PARAMETER Cloud
  One of: General (default), GCC, 'GCC High', DoD

.PARAMETER SkipGraph
  If set, only validates certificate and exits without calling Graph

.EXAMPLE
  .\Test-GraphConnectivity.ps1 -TenantId $env:TENANT -ClientId $env:CLIENT `
    -PfxBase64 $env:PFX_B64 `
    -PfxPassword (ConvertTo-SecureString $env:M365_PFX_PASSWORD -AsPlainText -Force)

.NOTES
  Requires: PowerShell 7+, internet access; auto-installs Microsoft.Graph & MSAL.PS if missing.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$TenantId,

  [Parameter(Mandatory=$true)]
  [string]$ClientId,

  [Parameter()]
  [string]$PfxPath,

  [Parameter()]
  [string]$PfxBase64,             # pragma: allowlist secret

  [Parameter()]
  [SecureString]$PfxPassword,      # pragma: allowlist secret

  [Parameter()]
  [string]$Thumbprint,

  [Parameter()]
  [string]$ExportCerPath,

  [Parameter()]
  [ValidateSet('General','GCC','GCC High','DoD')]
  [string]$Cloud = 'General',

  [switch]$SkipGraph
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Section($Text) {
  Write-Host ""
  Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Ensure-Module {
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [string]$MinVersion
  )
  if (-not (Get-Module -ListAvailable -Name $Name)) {
    Write-Verbose "Installing module $Name..."
    $params = @{ Name=$Name; Scope='CurrentUser'; Force=$true }
    if ($MinVersion) { $params.MinimumVersion = $MinVersion }
    Install-Module @params -ErrorAction Stop
  } else {
    Write-Verbose "Module $Name already available."
  }
}

function Get-GraphEnvironment {
  param([string]$Cloud)
  switch ($Cloud.ToLower()) {
    'general'   { return @{ SdkEnv='Global';    Login='https://login.microsoftonline.com';    Graph='https://graph.microsoft.com' } }
    'gcc'       { return @{ SdkEnv='Global';    Login='https://login.microsoftonline.com';    Graph='https://graph.microsoft.com' } } # GCC uses commercial Graph
    'gcc high'  { return @{ SdkEnv='USGovHigh'; Login='https://login.microsoftonline.us';     Graph='https://graph.microsoft.us'   } }
    'dod'       { return @{ SdkEnv='USGovDoD';  Login='https://login.microsoftonline.us';     Graph='https://dod-graph.microsoft.us' } }
    default     { return @{ SdkEnv='Global';    Login='https://login.microsoftonline.com';    Graph='https://graph.microsoft.com' } }
  }
}

function Import-PfxIfNeeded {
  param(
    [string]$PfxPath,
    [string]$PfxBase64,
    [SecureString]$PfxPassword
  )
  # Prefer pre-existing Thumbprint if provided
  if ($script:Thumbprint) {
    Write-Verbose "Thumbprint provided; will attempt to use $Thumbprint from Cert:\CurrentUser\My"
    $cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Thumbprint -eq $script:Thumbprint }
    if ($null -ne $cert) { return $cert }
    Write-Warning "Thumbprint $Thumbprint not found in CurrentUser\My; will attempt import."
  }

  $pfxBytes = $null
  if ($PfxPath) {
    if (-not (Test-Path -LiteralPath $PfxPath)) {
      throw "PFX file not found: $PfxPath"
    }
    $pfxBytes = [System.IO.File]::ReadAllBytes($PfxPath)
  } elseif ($PfxBase64) {
    try {
      $pfxBytes = [Convert]::FromBase64String($PfxBase64)  # pragma: allowlist secret
    } catch {
      throw "PFX_B64 is not valid base64: $($_.Exception.Message)"
    }
  } else {
    throw "Provide either -PfxPath or -PfxBase64 (or set -Thumbprint to use an existing cert)."
  }

  if (-not $PfxPassword) {
    throw "A PFX password is required for import (use -PfxPassword SecureString)."
  }

  # Import into CurrentUser\My
  $tmpFile = [System.IO.Path]::GetTempFileName()
  try {
    [System.IO.File]::WriteAllBytes($tmpFile, $pfxBytes)
    $importParams = @{
      FilePath = $tmpFile
      CertStoreLocation = 'Cert:\CurrentUser\My'
      Password = $PfxPassword
    }
    $cert = Import-PfxCertificate @importParams
  } finally {
    Remove-Item -LiteralPath $tmpFile -ErrorAction SilentlyContinue
  }

  if (-not $cert) { throw "Import-PfxCertificate returned no certificate." }
  if ($cert.Count -gt 1) { $cert = $cert[0] }

  return $cert
}

function Show-CertDetails {
  param([System.Security.Cryptography.X509Certificates.X509Certificate2]$Cert)
  Write-Host "Subject: $($Cert.Subject)"
  Write-Host "Thumbprint: $($Cert.Thumbprint)"
  Write-Host ("NotBefore: {0:yyyy-MM-dd HH:mm:ss K}" -f $Cert.NotBefore)
  Write-Host ("NotAfter : {0:yyyy-MM-dd HH:mm:ss K}" -f $Cert.NotAfter)
  Write-Host "HasPrivateKey: $($Cert.HasPrivateKey)"
  if ($Cert.NotAfter -lt (Get-Date).AddDays(30)) {
    Write-Warning "Certificate expires within 30 days."
  }
}

function Export-CerIfRequested {
  param(
    [System.Security.Cryptography.X509Certificates.X509Certificate2]$Cert,
    [string]$Path
  )
  if (-not $Path) { return }
  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

  $bytes = $Cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
  [System.IO.File]::WriteAllBytes($Path, $bytes)
  Write-Host "Exported CER to: $Path"
}

function Connect-GraphSDK {
  param(
    [string]$TenantId,
    [string]$ClientId,
    [string]$Thumbprint,
    [string]$SdkEnv
  )
  # Microsoft.Graph.Authentication will be installed via Microsoft.Graph meta if missing
  Ensure-Module -Name 'Microsoft.Graph' -MinVersion '2.18.0'
  Import-Module Microsoft.Graph -ErrorAction Stop

  # In App-only mode, scopes are implied by app roles granted; Connect-MgGraph doesn’t need -Scopes.
  $connectParams = @{
    TenantId = $TenantId
    ClientId = $ClientId
    CertificateThumbprint = $Thumbprint
    NoWelcome = $true
    Environment = $SdkEnv
  }
  Write-Verbose "Connecting to Graph SDK (Env=$SdkEnv) with thumbprint $Thumbprint ..."
  Connect-MgGraph @connectParams | Out-Null

  $ctx = Get-MgContext
  if (-not $ctx) { throw "Get-MgContext returned null after Connect-MgGraph." }
  Write-Host "Graph SDK connected. AppId=$($ctx.ClientId) Tenant=$($ctx.TenantId) Cloud=$($ctx.Environment)"
}

function Invoke-GraphSDKTest {
  [CmdletBinding()]
  param([string]$BaseGraph)

  $uri = "$BaseGraph/v1.0/admin/serviceAnnouncement/messages`?$top=5&`$select=id,title,lastModifiedDateTime,severity,isMajorChange,services"
  Write-Verbose "Calling: $uri"
  $resp = Invoke-MgGraphRequest -Method GET -Uri $uri
  if (-not $resp.value) { throw "Empty response from serviceAnnouncement/messages." }

  $rows = $resp.value | Select-Object id, title, lastModifiedDateTime, severity, isMajorChange,
                                      @{n='services';e={$_.services -join '; '}}
  Write-Host ""
  Write-Host "Top 5 Message center items (SDK):" -ForegroundColor Green
  $rows | Format-Table -AutoSize

  return $true
}

function Acquire-TokenMSAL {
  param(
    [string]$TenantId,
    [string]$ClientId,
    [System.Security.Cryptography.X509Certificates.X509Certificate2]$Cert,
    [string]$LoginHost,  # e.g., https://login.microsoftonline.com or .us
    [string]$Scope       # e.g., https://graph.microsoft.com/.default
  )
  Ensure-Module -Name 'MSAL.PS' -MinVersion '4.39.0'
  Import-Module MSAL.PS -ErrorAction Stop

  $auth = "$LoginHost/$TenantId"
  Write-Verbose "Acquiring token via MSAL.PS (authority=$auth, scope=$Scope)..."
  $tok = Get-MsalToken -ClientId $ClientId -TenantId $TenantId -ClientCertificate $Cert -Authority $auth -Scopes $Scope
  if (-not $tok.AccessToken) { throw "MSAL returned no access token." }
  return $tok.AccessToken
}

function Invoke-GraphRestTest {
  param(
    [string]$AccessToken,
    [string]$BaseGraph
  )
  $uri = "$BaseGraph/v1.0/admin/serviceAnnouncement/messages`?$top=5&`$select=id,title,lastModifiedDateTime,severity,isMajorChange,services"
  Write-Verbose "Calling (REST): $uri"
  $headers = @{ Authorization = "Bearer $AccessToken" }  # pragma: allowlist secret
  $data = Invoke-RestMethod -Method GET -Uri $uri -Headers $headers -ErrorAction Stop
  if (-not $data.value) { throw "Empty response from serviceAnnouncement/messages (REST)." }

  $rows = $data.value | Select-Object id, title, lastModifiedDateTime, severity, isMajorChange,
                                      @{n='services';e={$_.services -join '; '}}
  Write-Host ""
  Write-Host "Top 5 Message center items (REST):" -ForegroundColor Yellow
  $rows | Format-Table -AutoSize
  return $true
}

# ---------------------------
# MAIN
# ---------------------------
try {
  Write-Section "Resolve Cloud Environment"
  $envMap = Get-GraphEnvironment -Cloud $Cloud
  $sdkEnv   = $envMap.SdkEnv
  $login    = $envMap.Login
  $baseGraph= $envMap.Graph
  Write-Host "Cloud: $Cloud | SDK Env: $sdkEnv | Login: $login | Graph: $baseGraph"

  Write-Section "Certificate Load/Import"
  $cert = $null
  if ($Thumbprint) {
    # Try direct lookup first
    $cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Thumbprint -eq $Thumbprint }
    if (-not $cert) {
      Write-Warning "Thumbprint not found in Cert:\CurrentUser\My; attempting import from PFX inputs..."
      $cert = Import-PfxIfNeeded -PfxPath $PfxPath -PfxBase64 $PfxBase64 -PfxPassword $PfxPassword
    }
  } else {
    $cert = Import-PfxIfNeeded -PfxPath $PfxPath -PfxBase64 $PfxBase64 -PfxPassword $PfxPassword
  }

  if ($cert -is [System.Array]) { $cert = $cert[0] }
  if (-not $cert) { throw "Unable to obtain certificate." }

  Show-CertDetails -Cert $cert

  if ($ExportCerPath) {
    Export-CerIfRequested -Cert $cert -Path $ExportCerPath
  }

  if ($SkipGraph) {
    Write-Host "SkipGraph was specified; certificate validation complete." -ForegroundColor Green
    exit 0
  }

  Write-Section "Graph SDK Connection Test"
  $connected = $false
  try {
    Connect-GraphSDK -TenantId $TenantId -ClientId $ClientId -Thumbprint $cert.Thumbprint -SdkEnv $sdkEnv
    $null = Invoke-GraphSDKTest -BaseGraph $baseGraph
    $connected = $true
  } catch {
    Write-Warning "Graph SDK path failed: $($_.Exception.Message)"
  }

  if (-not $connected) {
    Write-Section "MSAL.PS Fallback Token Test"
    # Scope must be resource/.default for app-only
    $scope = ($baseGraph.TrimEnd('/') + '/.default')
    $token = Acquire-TokenMSAL -TenantId $TenantId -ClientId $ClientId -Cert $cert -LoginHost $login -Scope $scope
    $null = Invoke-GraphRestTest -AccessToken $token -BaseGraph $baseGraph
    Write-Host "MSAL.PS fallback succeeded." -ForegroundColor Green
  } else {
    Write-Host "Graph SDK path succeeded." -ForegroundColor Green
  }

  Write-Host ""
  Write-Host "All tests completed successfully." -ForegroundColor Green
  exit 0
}
catch {
  Write-Error $_.Exception.Message
  if ($PSBoundParameters.Verbose) {
    Write-Error $_.ScriptStackTrace
  }
  exit 1
}

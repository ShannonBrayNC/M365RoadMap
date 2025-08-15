# Thumbprint you showed earlier
$thumb  = '466E0F0C5A41305C083711773F0FC5F70530BE16'
$outCer =  'EchoMediaAI.M365RoadMap.cer'


# Try CurrentUser\My first, fall back to LocalMachine\My
$cert = Get-Item "Cert:\CurrentUser\My\$thumb" -ErrorAction SilentlyContinue
if (-not $cert) { $cert = Get-Item "Cert:\LocalMachine\My\$thumb" }

if (-not $cert) { throw "Cert with thumbprint $thumb not found in MY store." }

# Export a DER-encoded .cer (public key only)
Export-Certificate -Cert $cert -FilePath ..\$outCer -Type CERT -Force | Out-Null
Write-Host "Wrote $outCer"

# (Optional) sanity check: file SHA1 should match the cert thumbprint for DER .cer
$hash = (Get-FileHash $outCer -Algorithm SHA1).Hash.ToUpper()
"File SHA1 : $hash"
# If you just recreated graph_config.json, do this:
$env:M365_PFX_PASSWORD = "<your PFX password>"   # set in *this* shell
python scripts/fetch_messages_graph.py `
  --config graph_config.json `
  --no-window --emit csv --out output/nofilter.csv




# --- EDIT THESE 3 VALUES ---
$TenantId = "38ac7b7f-65e1-4a2a-8e3a-7bbe18659ebe"   # e.g. 38ac7b7f-... or contoso.onmicrosoft.com
$ClientId = "5adca85e-5309-4f49-8c8d-044fccc637f0"
$PfxPath  = "C:\echomediaai\EchoMediaAi_Graph.pfx"

# --- Optional: change endpoints if you're in GCC High / DoD ---
$GraphBase     = "https://graph.microsoft.com/v1.0"      # use https://graph.microsoft.us/v1.0 for GCC High/DoD
$AuthorityBase = "https://login.microsoftonline.com"      # use https://login.microsoftonline.us for GCC High/DoD

# --- Build base64 and write JSON ---
$PfxB64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($PfxPath))
$cfg = [ordered]@{
  tenant_id        = $TenantId
  client_id        = $ClientId
  pfx_base64       = $PfxB64
  pfx_password_env = "M365_PFX_PASSWORD"
  graph_base       = $GraphBase
  authority_base   = $AuthorityBase
}
$cfg | ConvertTo-Json -Depth 5 | Out-File -LiteralPath "graph_config.json" -Encoding utf8
Write-Host "graph_config.json written." -ForegroundColor Green

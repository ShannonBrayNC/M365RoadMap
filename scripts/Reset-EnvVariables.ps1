# Clear the bad ones first
Remove-Item Env:GRAPH_TENANT_ID -ErrorAction SilentlyContinue
Remove-Item Env:TENANT          -ErrorAction SilentlyContinue
Remove-Item Env:GRAPH_CLIENT_ID -ErrorAction SilentlyContinue
Remove-Item Env:CLIENT          -ErrorAction SilentlyContinue
Remove-Item Env:M365_PFX_BASE64 -ErrorAction SilentlyContinue
Remove-Item Env:PFX_B64         -ErrorAction SilentlyContinue

# Set correct values (GUIDs or tenant.onmicrosoft.com)
$env:M365_TENANT_ID = "38ac7b7f-65e1-4a2a-8e3a-7bbe18659ebe"
$env:M365_CLIENT_ID = "5adca85e-5309-4f49-8c8d-044fccc637f0"
$env:M365_PFX_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\echomediaai\_cfg.pfx"))
$env:M365_PFX_PASSWORD = "EdenEcho!"

python scripts/fetch_messages_graph.py --emit csv --out output/nofilter.csv

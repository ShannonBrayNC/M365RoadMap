# Show which env name your code will read (don’t print the password!)
$cfg = Get-Content -Raw graph_config.json | ConvertFrom-Json

cls


$cfg.authority_base
$cfg.client_id
$cfg.tenant_id
$cfg.graph_base
$cfg.pfx_path
$cfg.pfx_password_env


$env:M365_PFX_PASSWORD
$env:GRAPH_CLIENT_ID
$env:GRAPH_TENANT_ID
$env:GRAPH_CERTIFICATE_NAME
$env:GRAPH_SCOPES


$bytes = [Convert]::FromBase64String($cfg.pfx_base64)
[IO.File]::WriteAllBytes(".\_diag.pfx", $bytes)
certutil -dump .\_diag.pfx -p $env:M365_PFX_PASSWORD



# 1) Quick diag (confirms token path is unblocked)
python scripts/diag_graph.py --config graph_config.json --top 3

# 2) Fetch with no date window (multi-cloud is fine)
python scripts/fetch_messages_graph.py `
  --config graph_config.json `
  --no-window `
  --cloud "General" --cloud "GCC" --cloud "GCC High" --cloud "DoD" `
  --emit csv --out output/roadmap_report_master.csv `
  --stats-out output/fetch_stats.json
  

# 3) Generate the final report (sample)
python scripts/generate_feature_reports.py `
  --title "Roadmap Feature Report" `
  --master output/roadmap_report_master.csv `
  --fetch-public `
  --out output/roadmap_report.md


  certutil -dump _diag.pfx -p $env:M365_PFX_PASSWORD

  
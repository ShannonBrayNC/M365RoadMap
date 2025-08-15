$CLOUD = 'Worldwide (Standard Multi-Tenant)'

python .\scripts\fetch_messages_graph.py `
  --config .\graph_config.json `
  --cloud "$CLOUD" `
  --no-public-scrape `
  --emit csv --out .\output\roadmap_report_master.csv `
  --stats-out .\output\fetch_stats.json

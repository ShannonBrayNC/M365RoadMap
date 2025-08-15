$CLOUD = 'Worldwide (Standard Multi-Tenant)'

python -m scripts.fetch_messages_graph.py `
  --config .\graph_config.json `
  --cloud "$CLOUD" `
  --no-public-scrape `
  --emit csv --out .\output\roadmap_report_master.csv `
  --stats-out .\output\fetch_stats.json


  python  -m scripts.generate_report.py `
  --title "Roadmap Report" `
  --master .\output\roadmap_report_master.csv `
  --out .\output\roadmap_report.md `
  --cloud "$CLOUD"

python -m scripts.md_to_html.py .\output\roadmap_report.md .\output\roadmap_report.html

$params = @(
  '--config','graph_config.json',
  '--cloud','Worldwide (Standard Multi-Tenant)',
  '--emit','csv','--out','output/roadmap_report_master.csv',
  '--stats-out','output/fetch_stats.json'
)
python scripts/fetch_messages_graph.py @params


$CLOUD = 'Worldwide (Standard Multi-Tenant)'

python scripts/fetch_messages_graph.py `
  --config graph_config.json `
  --cloud "$CLOUD" `
  --emit csv --out output/roadmap_report_master.csv `
  --stats-out output/fetch_stats.json

python scripts/generate_report.py `
  --title "Roadmap Report" `
  --master output/roadmap_report_master.csv `
  --out output/roadmap_report.md `
  --cloud "$CLOUD"

python scripts/md_to_html.py output/roadmap_report.md output/roadmap_report.html

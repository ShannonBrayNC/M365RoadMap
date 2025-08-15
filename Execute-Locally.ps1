# 1) Install
.\.venv\Scripts\pip.exe install -r requirements.txt

# 2) Build master (fetch)
$env:PFX_PASSWORD_ENV="M365_PFX_PASSWORD"
$env:M365_PFX_PASSWORD="M365_PFX_PASSWORD"
python scripts/fetch_messages_graph.py --emit csv --out output/roadmap_report_master.csv

# 3) Generate final tailored report (no AI)
python scripts/generate_feature_reports.py `
  --title "Roadmap Feature Report" `
  --master output/roadmap_report_master.csv `
  --fetch-public `
  --out output/roadmap_report.md

# (Optional) With AI
$env:OPENAI_API_KEY="OPENAI_API_KEY"
python scripts/generate_feature_reports.py `
  --master output/roadmap_report_master.csv `
  --fetch-public `
  --use-openai --model gpt-4o-mini `
  --prompt prompts/feature_summarize_tailored.md `
  --out output/roadmap_report.md

# 4) Run tests
pytest -q

# v2 Python Joiner + Streamlit Patch

This patch adds:
- `scripts/cli/generate_report.py` → writes `output/enriched.json` + `output/roadmap_report.html`
- `scripts/enrich/merge_items.py` / `types.py` → joiner + models
- `app/streamlit_app.py` → loads `output/enriched.json`, with Refresh button, bubble chart, expanders, and link chips
- `.github/workflows/data.yml` → CI to build data, upload artifact, and (optional) publish `roadmap_report.html` to GitHub Pages

## Local usage

```bash
python -m pip install -r requirements.txt
# Optionally set Graph creds; otherwise free mode will be used
set TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
set CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
set CLIENT_SECRET=your_secret

python -m scripts.cli.generate_report --mode auto --with-web
streamlit run app/streamlit_app.py
```

## Notes
- Roadmap seed is loaded from `output/roadmap_report_master.json` or `data/M365RoadMap_Test.json` if present; else a small sample is used.
- If Graph auth fails, the CLI gracefully degrades to `--mode free` and still produces `output/enriched.json`.
- The Streamlit UI reads only the single JSON feed; no server required.
